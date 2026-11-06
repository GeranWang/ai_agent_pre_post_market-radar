"""LLM call 2 (post-close variant): synthesize the evening 收盘总结 brief.

Mirrors `synthesize.py` but produces a `PostCloseBrief` and, when the same trading
day's pre-market brief exists on disk, feeds it in so the LLM can grade the morning's
calls (the 复盘对账 scorecard). Prompt blocks, tool-schema fragments, and the
validate/retry loop come from synth_shared.
"""
import json
from pathlib import Path

from jinja2 import Template
from rich.console import Console

from src.pipeline.llm import model_for
from src.pipeline.synth_shared import (
    CONFIDENCE, EVENT_ARRAY, FILTERED_ARRAY, MAX_TOKENS, OUTPUT_DIR,
    SOURCE_QUALITY_OBJECT, TELEMETRY_ARRAY, call_and_validate, earnings_block,
    econ_block, holdings_block, macro_readings, macro_releases_block,
    per_asset_block, recent_moves_block, save_brief,
)
from src.schemas.postclose import PostCloseBrief
from src.schemas.per_asset import PerAssetSummary
from src.schemas.raw import RawMaterial

console = Console()
ROOT = Path(__file__).parent.parent.parent
PROMPT_TEMPLATE = (ROOT / "src/prompts/synthesize_postclose.md").read_text()

MODEL = model_for("synthesize")

TOOL_SCHEMA = {
    "name": "submit_postclose_brief",
    "description": "Submit the fully structured post-close (收盘总结) brief.",
    "input_schema": {
        "type": "object",
        "properties": {
            "date":         {"type": "string"},
            "signal_state": {"type": "string", "enum": ["NOMINAL", "AMBER", "RED"]},
            "close_pulse": {
                "type": "object",
                "properties": {
                    "bias":       {"type": "string"},
                    "themes":     {"type": "array", "items": {"type": "string"}},
                    "takeaway":   {"type": "string"},
                    "confidence": CONFIDENCE,
                    "caveat":     {"type": "string"},
                },
                "required": ["bias", "themes", "takeaway", "confidence"],
            },
            "scorecard": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item":         {"type": "string"},
                        "morning_view": {"type": "string"},
                        "actual":       {"type": "string"},
                        "verdict":      {"type": "string", "enum": ["命中", "落空", "中性", "待续"]},
                    },
                    "required": ["item", "morning_view", "actual", "verdict"],
                },
            },
            "scorecard_note": {"type": "string"},
            "telemetry": TELEMETRY_ARRAY,
            "movers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"ticker": {"type": "string"}, "note": {"type": "string"}},
                    "required": ["ticker", "note"],
                },
            },
            "assets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker":        {"type": "string"},
                        "role":          {"type": "string"},
                        "state":         {"type": "string", "enum": ["Nominal", "Watch", "Alert"]},
                        "what_happened": {"type": "string"},
                        "read":          {"type": "string"},
                        "watch":         {"type": "string"},
                        "confidence":    CONFIDENCE,
                        "meta":          {"type": "object", "additionalProperties": {"type": "string"}},
                    },
                    "required": ["ticker", "role", "state", "what_happened", "read", "watch", "confidence", "meta"],
                },
            },
            "after_hours": {"type": "array", "items": {"type": "string"}},
            "tomorrow": EVENT_ARRAY,
            "filtered": FILTERED_ARRAY,
            "source_quality": SOURCE_QUALITY_OBJECT,
        },
        "required": ["date", "signal_state", "close_pulse", "telemetry", "assets", "source_quality"],
    },
}


def _load_morning_brief(date: str) -> dict | None:
    """The same trading day's pre-market brief, if it's on disk (for cross-compare).
    Tries the typed name first, then the legacy untyped one (early premarket files)."""
    for name in (f"brief_premarket_{date}.json", f"brief_{date}.json"):
        p = OUTPUT_DIR / name
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                return None
    return None


def _morning_block(morning: dict | None) -> str:
    if not morning:
        return ("(NO pre-market brief on disk for this day — leave `scorecard` empty and set "
                "`scorecard_note` to \"无当日晨报可对比\". Do not fabricate what the morning said.)")
    mp = morning.get("market_pulse", {})
    pr = morning.get("portfolio_read", {})
    lines = ["This is THIS MORNING's pre-market brief for the same day. Grade each expectation "
             "against what actually happened today (verdict: 命中 / 落空 / 中性 / 待续).",
             f"- Key question: {mp.get('key_question', '')}",
             f"- 命门 (swing): {pr.get('swing', '')}"]
    for w in pr.get("watch", []):
        lines.append(f"- Morning watch: {w}")
    for s in morning.get("top_signals", [])[:5]:
        lines.append(f"- Morning signal (rank {s.get('rank')}): {s.get('signal', '')} — {s.get('why', '')}")
    for a in morning.get("assets", []):
        if a.get("watch"):
            lines.append(f"- Morning {a.get('ticker')} watch: {a.get('watch')}")
    return "\n".join(lines)


def _build_prompt(raw: RawMaterial, summaries: dict[str, PerAssetSummary],
                  config: dict, morning: dict | None) -> str:
    # Close prices + full-day move (+ after-hours) — facts; injected later too.
    price_lines = []
    for q in raw.session_quotes:
        day = f"{q.day_change_pct:+.2f}%" if q.day_change_pct is not None else "—"
        ah = f", after-hours={q.after_hours_change_pct:+.2f}%" if q.after_hours_change_pct is not None else ""
        price_lines.append(f"- {q.ticker}: close={q.close_price}, day={day}{ah}")
    if not price_lines:
        price_lines = ["(close prices unavailable — session may not have settled; degrade gracefully)"]

    r = macro_readings(raw.macro_snapshot)
    macro_lines = [
        "Use these EXACT value/delta pairs for telemetry — these are the close readings.",
        f"- DGS2 (2Y, unit=%): value={r['DGS2'][0]} delta={r['DGS2'][1]}",
        f"- DGS10 (10Y, unit=%): value={r['DGS10'][0]} delta={r['DGS10'][1]}",
        f"- DXY (unit=\"\"): value={r['DXY'][0]} delta={r['DXY'][1]}",
        f"- VIX (unit=\"\"): value={r['VIX'][0]} delta={r['VIX'][1]}",
    ]

    return Template(PROMPT_TEMPLATE).render(
        date=raw.date,
        # macro_themes belong to the morning's forward-looking framing; the
        # post-close report reads what already happened.
        holdings_block=holdings_block(config, macro_themes=False),
        close_prices_block="\n".join(price_lines),
        recent_moves_block=recent_moves_block(raw),
        macro_block="\n".join(macro_lines),
        macro_releases_block=macro_releases_block(raw, "(no official macro readings available)"),
        econ_block=econ_block(raw, ["(no economic calendar data — do not invent releases)"],
                              show_impact=False),
        earnings_block=earnings_block(raw, with_eps=False),
        per_asset_block=per_asset_block(summaries, with_freshness=False),
        morning_brief_block=_morning_block(morning),
    )


def _inject_session_prices(brief: PostCloseBrief, raw: RawMaterial) -> None:
    """Close price / day-change are facts from yfinance, never the LLM."""
    q = {s.ticker: s for s in raw.session_quotes}
    for a in brief.assets:
        s = q.get(a.ticker)
        a.close_price = s.close_price if s else None
        a.change_pct = s.day_change_pct if s else None
    for m in brief.movers:
        s = q.get(m.ticker)
        m.change_pct = s.day_change_pct if s else None


def run_synthesize_postclose(raw: RawMaterial, summaries: dict[str, PerAssetSummary],
                             config: dict) -> PostCloseBrief:
    morning = _load_morning_brief(raw.date)
    prompt = _build_prompt(raw, summaries, config, morning)

    console.rule(f"[bold cyan]Post-close synthesis — {raw.date} ({MODEL})")
    console.print(f"Cross-compare: {'morning brief FOUND' if morning else 'no morning brief'}")

    brief = call_and_validate(MODEL, prompt, TOOL_SCHEMA, PostCloseBrief,
                              label="Post-close synthesis", max_tokens=MAX_TOKENS)
    brief.report_type = "postclose"
    _inject_session_prices(brief, raw)
    save_brief(brief, raw.date, "postclose")
    _print_brief(brief)
    return brief


def _print_brief(brief: PostCloseBrief) -> None:
    console.rule("[bold]Post-close preview")
    cp = brief.close_pulse
    console.print(f"[bold]{brief.date}[/bold]  Signal: {brief.signal_state}")
    console.print(f"Close Pulse · {cp.bias} · {cp.takeaway}")
    if brief.scorecard:
        console.print(f"[bold]复盘对账 ({len(brief.scorecard)}):[/bold]")
        for s in brief.scorecard:
            console.print(f"  [{s.verdict}] {s.item} → {s.actual[:60]}")
    elif brief.scorecard_note:
        console.print(f"复盘对账: {brief.scorecard_note}")
    console.print(f"Movers: {len(brief.movers)} · Assets: {len(brief.assets)} · "
                  f"After-hours: {len(brief.after_hours)} · Tomorrow: {len(brief.tomorrow)}")
