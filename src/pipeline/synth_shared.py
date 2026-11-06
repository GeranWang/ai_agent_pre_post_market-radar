"""Building blocks shared by the two synthesis stages.

`synthesize.py` (pre-market) and `synthesize_postclose.py` (post-close) are
different reports, but they read the same `RawMaterial` and talk to the same
model through the same forced-tool contract. Everything that is genuinely the
same lives here:

  * **tool-schema fragments** — telemetry / filtered / source_quality / event
    entries are byte-identical between the two reports
  * **prompt blocks** — how a holdings list, an economic calendar, or a set of
    per-asset summaries is rendered into prompt text
  * **the call → validate → retry loop**, including the salvage of models that
    return a nested object as a JSON *string*

Deliberately NOT shared: the prose around the data. The two prompts introduce
their macro readings with different wording because they mean different things
("pre-market snapshot" vs "close readings"), so each module formats its own
label lines from the values computed here. Sharing computation is a fix;
sharing prose would be a bug waiting to happen.
"""
import json
from pathlib import Path

from pydantic import BaseModel, ValidationError
from rich.console import Console

from src.pipeline.llm import NoToolCall, call_tool
from src.schemas.per_asset import PerAssetSummary
from src.schemas.raw import RawMaterial
from src.sources.yfinance_prices import MARKET_BENCHMARK, SessionMove

console = Console()
ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = ROOT / "output/intermediate"

MAX_RETRIES = 2
# Chinese prose + spelled-out terms make the brief long; 4096 truncated the tool
# call before source_quality. 8192 was fine for clean tool output, but when a model
# stringifies a list field the payload roughly doubles and overruns mid-array —
# the truncated string then fails list validation. 16384 absorbs that case, and
# coerce_json_strings salvages anything that still truncates.
MAX_TOKENS = 16384


# ---------------------------------------------------------------------------
# tool-schema fragments (identical across both reports)
# ---------------------------------------------------------------------------

CONFIDENCE = {"type": "string", "enum": ["Low", "Medium", "High"]}

TELEMETRY_ARRAY = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "key":   {"type": "string"},
            "value": {"type": "string"},
            "unit":  {"type": "string"},
            "delta": {"type": "string"},
            "flag":  {"type": "boolean"},
            "note":  {"type": "string"},
        },
        "required": ["key", "value", "unit", "delta", "flag"],
    },
}

# Pre-market calls this "events" (next 72h); post-close calls it "tomorrow".
# Same shape, same meaning: a dated catalyst with a priority.
EVENT_ARRAY = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "time":     {"type": "string"},
            "event":    {"type": "string"},
            "affected": {"type": "string"},
            "why":      {"type": "string"},
            "priority": {"type": "string", "enum": ["LOW", "MED", "HIGH"]},
        },
        "required": ["time", "event", "affected", "why", "priority"],
    },
}

FILTERED_ARRAY = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "headline": {"type": "string"},
            "reason":   {"type": "string"},
        },
        "required": ["headline", "reason"],
    },
}

SOURCE_QUALITY_OBJECT = {
    "type": "object",
    "properties": {
        "official":          {"type": "integer"},
        "tier1":             {"type": "integer"},
        "secondary":         {"type": "integer"},
        "inference":         {"type": "integer"},
        "report_confidence": CONFIDENCE,
        "limitation":        {"type": "string"},
    },
    "required": ["official", "tier1", "secondary", "inference", "report_confidence"],
}


# ---------------------------------------------------------------------------
# prompt blocks
# ---------------------------------------------------------------------------

def holdings_block(config: dict, macro_themes: bool = True) -> str:
    """Holdings + watchlist (+ macro themes) as prompt lines.

    Only fields the user actually supplied are emitted. With tickers.yaml the
    user gives just a ticker — name/sector/role stay blank and must be inferred
    by the model, not steered by us.
    """
    lines = []
    for h in config.get("holdings", []):
        line = f"- {h['ticker']}"
        if h.get("name"):
            line += f": {h['name']}"
        extras = [f"{k}: {h[k]}" for k in ("sector", "role") if h.get(k)]
        if extras:
            line += " | " + " | ".join(extras)
        lines.append(line)

    watchlist = config.get("watchlist", [])
    if watchlist:
        lines.append(f"Watchlist: {', '.join(w['ticker'] for w in watchlist)}")
    themes = config.get("macro_themes", [])
    if macro_themes and themes:
        lines.append(f"Macro themes: {', '.join(themes)}")
    return "\n".join(lines)


def _bp(cur, prev) -> tuple[str, str]:
    """Treasury yield → basis-point delta."""
    if cur is None:
        return "n/a", "data unavailable"
    if prev is None:
        return f"{cur:.2f}", "level"
    return f"{cur:.2f}", f"{(cur - prev) * 100:+.0f}bp"


def _pct(cur, prev) -> tuple[str, str]:
    """Index level → percent delta."""
    if cur is None:
        return "n/a", "data unavailable"
    if not prev:
        return f"{cur:.2f}", "level"
    return f"{cur:.2f}", f"{(cur - prev) / prev * 100:+.2f}%"


def _pts(cur, prev) -> tuple[str, str]:
    """VIX → point delta."""
    if cur is None:
        return "n/a", "data unavailable"
    if prev is None:
        return f"{cur:.2f}", "level"
    return f"{cur:.2f}", f"{cur - prev:+.1f}"


def macro_readings(macro) -> dict[str, tuple[str, str]]:
    """The four telemetry readings as {key: (value, delta)} display strings.

    Callers format their own label lines — the numbers are shared, the wording
    around them is each report's own.
    """
    return {
        "DGS2":  _bp(macro.dgs2, macro.dgs2_prev),
        "DGS10": _bp(macro.dgs10, macro.dgs10_prev),
        "DXY":   _pct(macro.dxy, macro.dxy_prev),
        "VIX":   _pts(macro.vix, macro.vix_prev),
    }


def recent_moves_block(raw: RawMaterial) -> str:
    """Daily moves over the window for the market benchmark and every holding —
    the cross-asset tape the attribution check reads. The benchmark row is there
    whatever the user holds, so "is it just the market?" can always be asked."""
    def moves(rows: list[SessionMove]) -> str:
        return " · ".join(f"{r.date[5:]} {r.change_pct:+.2f}%" for r in rows
                          if r.change_pct is not None)

    lines = []
    if raw.market_reference:
        lines.append(f"- MARKET ({MARKET_BENCHMARK}, US equity benchmark): {moves(raw.market_reference)}")
    for ticker, rows in raw.recent_sessions.items():
        if rows:
            lines.append(f"- {ticker}: {moves(rows)}")
    return "\n".join(lines or ["(no daily closes available — do not infer cross-asset moves)"])


def macro_releases_block(raw: RawMaterial, fallback: str) -> str:
    """Latest official readings (FRED), which override any news-quoted figure."""
    lines = [f"- {r.label}: {r.value} (ref month {r.ref_month}, FRED {r.series_id})"
             for r in raw.macro_releases]
    return "\n".join(lines or [fallback])


def econ_block(raw: RawMaterial, fallback: list[str], show_impact: bool = True) -> str:
    """US / high-impact economic calendar entries, capped at 20."""
    lines = []
    relevant = [e for e in raw.economic_calendar
                if e.impact in ("high", "medium", "3") or e.country == "US"]
    for e in relevant[:20]:
        imp = (f" [{e.impact.upper()}]" if e.impact else "") if show_impact else ""
        actual = f" actual={e.actual}" if e.actual else ""
        estimate = f" est={e.estimate}" if e.estimate else ""
        prev = f" prev={e.previous}" if e.previous else ""
        lines.append(f"- {e.time or 'TBD'} ET {e.country}: {e.event}{imp}{actual}{estimate}{prev}")
    return "\n".join(lines or fallback)


def earnings_block(raw: RawMaterial, with_eps: bool = True) -> str:
    """Today's earnings calendar, capped at 15."""
    lines = []
    for e in raw.earnings_calendar[:15]:
        eps = (f" eps_est={e.eps_estimate}" if e.eps_estimate else "") if with_eps else ""
        lines.append(f"- {e.ticker} ({e.company}) {e.hour or ''}{eps}")
    return "\n".join(lines or ["(no earnings today)"])


def per_asset_block(summaries: dict[str, PerAssetSummary], with_freshness: bool = True) -> str:
    """Per-asset stage output, one section per ticker.

    freshness / source_quality were graded by the per-asset stage from the real
    headlines (published_at + outlet); the synthesis stage reuses them when
    labelling Top Signals instead of re-deriving them.
    """
    sections = []
    for ticker, s in summaries.items():
        if not s.has_material_news:
            sections.append(f"### {ticker} [NO MATERIAL NEWS] — {s.skip_reason}")
            continue
        fresh = f" · freshness={s.freshness}" if with_freshness else ""
        cross = (f" | cross-affects: {', '.join(s.second_order_tickers)}"
                 if s.second_order_tickers else "")
        sections.append(
            f"### {ticker} [{s.sentiment.upper()}]{fresh} · source={s.source_quality}\n"
            f"Events: {'; '.join(s.key_events)}\n"
            f"Relevance: {s.portfolio_relevance}{cross}"
        )
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# flaky-output salvage
# ---------------------------------------------------------------------------

def _repair_truncated_json(s: str):
    """Best-effort recovery of a JSON array/object string cut off mid-structure.

    When a model stringifies a list field AND that escaped string overruns
    max_tokens, the value arrives truncated and unparseable. Salvage every
    complete leading element by closing the container at the last point where
    bracket depth returned to the container level (outside of any string), then
    parse that. Returns the parsed value, or None if nothing can be recovered.

    Only complete elements survive — a half-written trailing object is dropped.
    Good enough for top_signals/assets/events (arrays of objects); primitive
    trailing fields of an object are not recovered, but those sections are tiny
    and effectively never truncate.
    """
    outer = "]" if s[:1] == "[" else "}"
    depth = 0
    in_str = False
    escaped = False
    last_safe = None  # index (exclusive) just after a complete container-level element
    for i, ch in enumerate(s):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 1:  # a nested element just closed back to the outer container
                last_safe = i + 1
    if last_safe is None:
        return None
    try:
        return json.loads(s[:last_safe] + outer)
    except (json.JSONDecodeError, ValueError):
        return None


def coerce_json_strings(value):
    """Repair flaky tool-call output.

    Models occasionally return a nested object/array as a JSON *string* instead
    of a real object (e.g. source_quality='{"official": 1, ...}'). Walk the input
    and parse any string that is actually JSON back into a dict/list. Strings that
    are not JSON (normal prose) are returned untouched. A stringified array that
    was also truncated by max_tokens is repaired to its complete leading elements.
    """
    if isinstance(value, str):
        s = value.strip()
        if s[:1] in ("{", "["):
            try:
                return coerce_json_strings(json.loads(s))
            except (json.JSONDecodeError, ValueError):
                repaired = _repair_truncated_json(s)
                if repaired is not None:
                    return coerce_json_strings(repaired)
                return value
        return value
    if isinstance(value, dict):
        return {k: coerce_json_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [coerce_json_strings(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# call → validate → retry
# ---------------------------------------------------------------------------

def call_and_validate(model: str, prompt: str, tool_schema: dict,
                      schema_cls: type[BaseModel], label: str,
                      max_tokens: int = MAX_TOKENS, max_retries: int = MAX_RETRIES):
    """Force the tool call and validate it into `schema_cls`, retrying on failure.

    A schema violation is fed back to the model verbatim — telling it exactly what
    Pydantic rejected is far more effective than re-sending the same prompt.
    """
    last_error = ""
    for attempt in range(1, max_retries + 2):
        if attempt > 1:
            console.print(f"[yellow]Retry {attempt - 1}/{max_retries}: {last_error[:120]}")

        messages = [{"role": "user", "content": prompt}]
        if last_error:
            messages.append({"role": "assistant", "content": "I'll fix the schema error."})
            messages.append({"role": "user",
                             "content": f"Validation failed: {last_error}\nPlease resubmit with corrections."})

        try:
            args = call_tool(model, messages, tool_schema, max_tokens=max_tokens)
        except NoToolCall as e:
            last_error = str(e)
            continue

        try:
            return schema_cls(**coerce_json_strings(args))
        except ValidationError as e:
            last_error = str(e)

    raise RuntimeError(f"{label} failed after {max_retries + 1} attempts: {last_error}")


def save_brief(brief: BaseModel, date: str, report_type: str) -> Path:
    """Persist the validated brief. Every stage writes its output to disk —
    debugging a quality problem without the intermediate is guesswork."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"brief_{report_type}_{date}.json"
    out_path.write_text(brief.model_dump_json(indent=2))
    console.print(f"[bold green]Saved → {out_path.name}")
    return out_path
