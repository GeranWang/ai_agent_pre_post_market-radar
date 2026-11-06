"""LLM call 2 (pre-market): synthesize the morning brief from per-asset summaries.

The quality lever of the product. Prompt blocks, tool-schema fragments, and the
validate/retry loop are shared with the post-close variant — see synth_shared.
"""
from pathlib import Path

from jinja2 import Template
from rich.console import Console

from src.pipeline.llm import model_for
from src.pipeline.synth_shared import (
    CONFIDENCE, EVENT_ARRAY, FILTERED_ARRAY, MAX_TOKENS, SOURCE_QUALITY_OBJECT,
    TELEMETRY_ARRAY, call_and_validate, earnings_block, econ_block, holdings_block,
    macro_readings, macro_releases_block, per_asset_block, recent_moves_block, save_brief,
)
from src.schemas.brief import DailyBrief
from src.schemas.per_asset import PerAssetSummary
from src.schemas.raw import RawMaterial

console = Console()
ROOT = Path(__file__).parent.parent.parent
PROMPT_TEMPLATE = (ROOT / "src/prompts/synthesize.md").read_text()

MODEL = model_for("synthesize")

TOOL_SCHEMA = {
    "name": "submit_daily_brief",
    "description": "Submit the fully structured Pre-market Radar brief.",
    "input_schema": {
        "type": "object",
        "properties": {
            "date":         {"type": "string"},
            "signal_state": {"type": "string", "enum": ["NOMINAL", "AMBER", "RED"]},
            "market_pulse": {
                "type": "object",
                "properties": {
                    "bias":         {"type": "string"},
                    "themes":       {"type": "array", "items": {"type": "string"}},
                    "key_question": {"type": "string"},
                    "confidence":   CONFIDENCE,
                    "caveat":       {"type": "string"},
                },
                "required": ["bias", "themes", "key_question", "confidence"],
            },
            "portfolio_read": {
                "type": "object",
                "properties": {
                    "posture": {"type": "string"},
                    "interactions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind":     {"type": "string", "enum": ["Shared driver", "Hedge failure", "Concentration", "Divergence"]},
                                "holdings": {"type": "array", "items": {"type": "string"}},
                                "note":     {"type": "string"},
                            },
                            "required": ["kind", "holdings", "note"],
                        },
                    },
                    "ripple": {"type": "string"},
                    "swing":  {"type": "string"},
                    "watch":  {"type": "array", "items": {"type": "string"}},
                },
                "required": ["posture", "interactions", "swing", "watch"],
            },
            "telemetry": TELEMETRY_ARRAY,
            "top_signals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rank":     {"type": "integer"},
                        "signal":   {"type": "string"},
                        "affected": {"type": "array", "items": {"type": "string"}},
                        "why":      {"type": "string"},
                        "label": {
                            "type": "object",
                            "properties": {
                                "freshness": {"type": "string", "enum": ["LIVE", "NEW", "RECENT", "STALE"]},
                                "source":    {"type": "string", "enum": ["Official", "Tier-1", "Secondary", "Low-confidence", "Inference"]},
                                "impact":    {"type": "string", "enum": ["High", "Medium", "Low", "Background"]},
                            },
                            "required": ["freshness", "source", "impact"],
                        },
                        "confidence": CONFIDENCE,
                    },
                    "required": ["rank", "signal", "affected", "why", "label", "confidence"],
                },
            },
            "assets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker":     {"type": "string"},
                        "role":       {"type": "string"},
                        "state":      {"type": "string", "enum": ["Nominal", "Watch", "Alert"]},
                        "news":       {"type": "string"},
                        "impact":     {"type": "string"},
                        "watch":      {"type": "string"},
                        "confidence": CONFIDENCE,
                        "meta":       {"type": "object", "additionalProperties": {"type": "string"}},
                    },
                    # NOTE: price / change_pct are intentionally NOT requested from the LLM.
                    # They are facts injected from raw pre-market data after synthesis,
                    # so the model can never fabricate a price.
                    "required": ["ticker", "role", "state", "news", "impact", "watch", "confidence", "meta"],
                },
            },
            "events": EVENT_ARRAY,
            "filtered": FILTERED_ARRAY,
            "source_quality": SOURCE_QUALITY_OBJECT,
        },
        "required": ["date", "signal_state", "market_pulse", "portfolio_read", "telemetry",
                     "top_signals", "assets", "events", "filtered", "source_quality"],
    },
}


def _build_prompt(raw: RawMaterial, summaries: dict[str, PerAssetSummary], holdings_config: dict) -> str:
    premarket_lines = []
    for q in raw.premarket_quotes:
        chg = f"{q.premarket_change_pct:+.2f}%" if q.premarket_change_pct is not None else "—"
        premarket_lines.append(f"- {q.ticker}: prev_close={q.previous_close}, chg={chg}")

    macro = raw.macro_snapshot
    r = macro_readings(macro)
    macro_lines = [
        "Use these EXACT value/delta pairs for the telemetry section — do not invent, round differently, or adjust them.",
        "If a value is \"n/a\", set that telemetry reading to value=\"n/a\", unit=\"\", delta=\"data unavailable\", flag=false.",
        f"- DGS2  (2Y Treasury, unit=%): value={r['DGS2'][0]}  delta={r['DGS2'][1]}",
        f"- DGS10 (10Y Treasury, unit=%): value={r['DGS10'][0]}  delta={r['DGS10'][1]}",
        f"- DXY   (US Dollar Index, unit=\"\"): value={r['DXY'][0]}  delta={r['DXY'][1]}",
        f"- VIX   (unit=\"\"): value={r['VIX'][0]}  delta={r['VIX'][1]}",
    ]
    if macro.note:
        macro_lines.append(f"(source note: {macro.note})")

    return Template(PROMPT_TEMPLATE).render(
        date=raw.date,
        last_session=raw.last_session or raw.date,
        special_day="(to be determined by you)",
        holdings_block=holdings_block(holdings_config),
        premarket_block="\n".join(premarket_lines),
        recent_moves_block=recent_moves_block(raw),
        macro_block="\n".join(macro_lines),
        macro_releases_block=macro_releases_block(
            raw, "(no official macro readings available — BLS and FRED both unavailable)"),
        econ_block=econ_block(raw, [
            "⚠ NO ECONOMIC CALENDAR DATA available for today (source returned nothing).",
            "DO NOT invent CPI, NFP, PCE, FOMC, or any scheduled release or its figures.",
        ]),
        earnings_block=earnings_block(raw),
        per_asset_block=per_asset_block(summaries),
    )


def run_synthesize(raw: RawMaterial, summaries: dict[str, PerAssetSummary], holdings_config: dict) -> DailyBrief:
    prompt = _build_prompt(raw, summaries, holdings_config)

    console.rule(f"[bold cyan]Synthesis — {raw.date} ({MODEL})")
    console.print(f"Input: {len(summaries)} per-asset summaries, "
                  f"{len(raw.economic_calendar)} econ events, "
                  f"{len(raw.earnings_calendar)} earnings")

    brief = call_and_validate(MODEL, prompt, TOOL_SCHEMA, DailyBrief,
                              label="Synthesis", max_tokens=MAX_TOKENS)
    brief.report_type = raw.report_type   # injected, not LLM-authored
    _inject_prices(brief, raw)
    save_brief(brief, raw.date, raw.report_type)
    _print_brief(brief)
    return brief


def _inject_prices(brief: DailyBrief, raw: RawMaterial) -> None:
    """Overwrite each asset's price/change_pct with real pre-market data.

    Prices are facts and must come from yfinance, never the LLM. If a quote
    is missing (e.g. run before pre-market opens, or fetch failed), the fields
    stay None and the renderer shows them as unavailable rather than 0.00.
    """
    quotes = {q.ticker: q for q in raw.premarket_quotes}
    for asset in brief.assets:
        q = quotes.get(asset.ticker)
        if q is None:
            asset.price = None
            asset.change_pct = None
            continue
        asset.price = q.premarket_price if q.premarket_price is not None else q.previous_close
        asset.change_pct = q.premarket_change_pct


def _print_brief(brief: DailyBrief) -> None:
    console.rule("[bold]Brief preview")
    sig_color = "yellow" if brief.signal_state == "AMBER" else ("red" if brief.signal_state == "RED" else "white")
    console.print(f"[bold]{brief.mission_designator}[/bold] · {brief.date}  "
                  f"Signal: [{sig_color}]{brief.signal_state}[/{sig_color}]")

    mp = brief.market_pulse
    console.print(f"\n[bold]Market Pulse[/bold] · bias: {mp.bias} · conf: {mp.confidence}")
    console.print(f"[dim italic]Q: {mp.key_question[:120]}[/dim italic]")

    console.print(f"\n[bold]Telemetry[/bold]")
    for t in brief.telemetry:
        flag_str = " [yellow]flag[/yellow]" if t.flag else ""
        console.print(f"  {t.key:6s} {t.value}{t.unit}  {t.delta}{flag_str}")

    console.print(f"\n[bold]Top Signals ({len(brief.top_signals)})[/bold]")
    for sig in brief.top_signals:
        console.print(
            f"  [yellow]{sig.rank}[/yellow] {sig.signal[:70]}  "
            f"[dim]({sig.label.source}·{sig.label.freshness}·{sig.label.impact})[/dim]"
        )

    console.print(f"\n[bold]Assets ({len(brief.assets)})[/bold]")
    for a in brief.assets:
        state_color = "yellow" if a.state == "Watch" else ("red" if a.state == "Alert" else "dim")
        chg = f"{a.change_pct:+.1f}%" if a.change_pct is not None else "  — "
        console.print(
            f"  [{state_color}]{a.state:8s}[/{state_color}] [bold]{a.ticker}[/bold]"
            f"  {chg}  {a.role}"
        )

    console.print(f"\n[bold]Event Watch ({len(brief.events)})[/bold]")
    for e in brief.events:
        pri_color = "yellow" if e.priority == "HIGH" else "dim"
        console.print(
            f"  [{pri_color}]{e.priority:4s}[/{pri_color}]  {e.time}  "
            f"[bold]{e.affected}[/bold]  {e.event[:50]}"
        )

    sq = brief.source_quality
    console.print(
        f"\n[dim]Interactions: {len(brief.portfolio_read.interactions)} · Portfolio watch: {len(brief.portfolio_read.watch)} · Filtered: {len(brief.filtered)} · "
        f"Sources: {sq.official} official / {sq.tier1} tier-1 / {sq.secondary} secondary / "
        f"{sq.inference} inference · report conf: {sq.report_confidence}[/dim]")
