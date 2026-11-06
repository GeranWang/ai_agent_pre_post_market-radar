import json
from pathlib import Path

from jinja2 import Template
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from src.pipeline.llm import NoToolCall, call_tool, model_for
from src.schemas.per_asset import PerAssetSummary
from src.schemas.raw import RawMaterial

console = Console()
ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = ROOT / "output/intermediate"
PROMPT_TEMPLATE = (ROOT / "src/prompts/per_asset.md").read_text()

MODEL = model_for("per_asset")
MAX_RETRIES = 2

TOOL_SCHEMA = {
    "name": "submit_asset_summary",
    "description": "Submit the structured summary for a single portfolio asset.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker":               {"type": "string"},
            "state":                {"type": "string", "enum": ["Nominal", "Watch", "Alert"]},
            "has_material_news":    {"type": "boolean"},
            "sentiment":            {"type": "string", "enum": ["bullish", "bearish", "neutral", "mixed"]},
            "key_events":           {"type": "array", "items": {"type": "string"}},
            "portfolio_relevance":  {"type": "string"},
            "second_order_tickers": {"type": "array", "items": {"type": "string"}},
            "skip_reason":          {"type": "string"},
            "freshness":            {"type": "string", "enum": ["NEW", "RECENT", "STALE", "NONE"]},
            "source_quality":       {"type": "string", "enum": ["Official", "Tier-1", "Secondary", "Low-confidence", "None"]},
        },
        "required": ["ticker", "state", "has_material_news", "sentiment", "key_events",
                     "portfolio_relevance", "second_order_tickers", "skip_reason",
                     "freshness", "source_quality"],
    },
}


def _price_action_block(ticker: str, raw: RawMaterial) -> str:
    """The real daily moves, so price-action headlines get dated by the market
    rather than by their publish date (see fetch_recent_sessions)."""
    rows = raw.recent_sessions.get(ticker, [])
    if not rows:
        return "### Price action\n(no daily closes available — do not infer moves from headlines)"
    post = raw.report_type == "postclose"
    label = "today's session — the one this report recaps" if post else "latest completed session"
    lines = ["### Price action (ground truth from market data — daily closes)"]
    for r in rows:
        chg = f"{r.change_pct:+.2f}%" if r.change_pct is not None else "—"
        mark = f"  ← {label}" if r.date == raw.last_session else ""
        lines.append(f"- {r.date}: close {r.close} ({chg}){mark}")
    if not post:
        q = next((q for q in raw.premarket_quotes if q.ticker == ticker), None)
        if q and q.premarket_change_pct is not None:
            lines.append(f"- pre-market now: {q.premarket_change_pct:+.2f}% vs the last close")
    lines.append(
        "Date every price-move claim with these numbers, not with a story's publish "
        "date: a story usually lands the day AFTER the move it describes. Attribute a "
        "move to the session whose change actually matches it, and never describe a "
        "session with a move its number contradicts."
    )
    return "\n".join(lines)


def _build_news_block(ticker: str, raw: RawMaterial) -> str:
    lines = []

    # ETF theme context: a fund has no earnings of its own, so its "news" is its
    # theme + its constituents' news (the [via SYMBOL] items below).
    profile = raw.etf_profiles.get(ticker)
    if profile and profile.is_etf:
        holdings = ", ".join(profile.holdings[:8]) if profile.holdings else "—"
        lines.append(
            f"### Fund profile\n"
            f"{ticker} is an ETF: {profile.long_name or ticker} · category: "
            f"{profile.category or 'n/a'}.\n"
            f"Top holdings: {holdings}.\n"
            f"This fund has no earnings of its own — its news IS the news of its theme "
            f"and constituents. Items tagged [via SYMBOL] are a holding's news standing "
            f"in for the fund's exposure; treat them as the fund's news. If the fund "
            f"tracks a physical commodity (e.g. gold) and has no direct/constituent "
            f"news, read it from its theme + the macro backdrop (dollar, real rates) "
            f"rather than declaring 'no news'.\n"
        )

    lines.append(_price_action_block(ticker, raw))

    session_note = (f" · latest trading session: {raw.last_session}"
                    if raw.last_session else "")
    news_items = raw.company_news.get(ticker, [])
    if news_items:
        lines.append(f"### News (report date: {raw.date} ET{session_note})")
        if raw.report_type == "postclose":
            lines.append(
                f"Items span the last ~5 trading sessions, each dated. This is a "
                f"post-close recap of the {raw.date} session: items dated {raw.date} "
                f"(including after-hours) are PRIMARY. Items dated BEFORE {raw.date} "
                f"are background context — they describe earlier sessions."
            )
        else:
            lines.append(
                f"Items span the last ~5 trading sessions, each dated. The freshest edge "
                f"is the latest session's close ({raw.last_session or 'last close'}) → now: "
                f"items dated ON OR AFTER {raw.last_session or 'the last session'} — "
                f"INCLUDING weekend / overnight news dated after it — are the freshest "
                f"PRIMARY material, NOT stale. Items dated BEFORE it are background context."
            )
        lines.append(
            "Each item is tagged [publisher · source_type]. source_type is "
            "PRE-COMPUTED deterministically — USE IT, do not re-grade from the "
            "publisher name. Note: Finnhub only reports the hosting platform "
            "(usually Yahoo / SeekingAlpha = secondary_media aggregators), not the "
            "original wire, so most items are secondary and none should be treated "
            "as tier-1 primary reporting."
        )
        for item in news_items:
            # published_at lets the model judge freshness; source_type is the
            # deterministic tier the model must reuse (no guessing from the name).
            tag = f" [via {item.via}]" if getattr(item, "via", "") else ""
            st = getattr(item, "source_type", "unknown")
            lines.append(f"- [{item.source} · {st}]{tag} ({item.published_at[:10]}) {item.headline}")
            if item.summary:
                lines.append(f"  {item.summary[:200]}")
    else:
        lines.append("### News\n(no news in the window)")

    filings = raw.sec_filings.get(ticker, [])
    if filings:
        lines.append("\n### SEC Filings (source_type: primary_official · is_primary_source: true)")
        for f in filings:
            lines.append(f"- {f.form_type} filed {f.filed_at}: {f.description}")

    return "\n".join(lines)


def _call_llm(prompt: str, ticker: str) -> PerAssetSummary:
    last_error: str = ""

    for attempt in range(1, MAX_RETRIES + 2):
        messages = [{"role": "user", "content": prompt}]
        if last_error:
            messages.append({"role": "assistant", "content": "I'll correct the previous error."})
            messages.append({"role": "user", "content": f"Previous attempt failed validation: {last_error}. Please fix and resubmit."})

        try:
            args = call_tool(MODEL, messages, TOOL_SCHEMA, max_tokens=1024)
        except NoToolCall as e:
            last_error = str(e)
            continue

        try:
            return PerAssetSummary(**args)
        except ValidationError as e:
            last_error = str(e)

    raise RuntimeError(f"[{ticker}] LLM validation failed after {MAX_RETRIES + 1} attempts: {last_error}")


def run_per_asset(raw: RawMaterial, holdings_config: dict) -> dict[str, PerAssetSummary]:
    holdings_map = {h["ticker"]: h for h in holdings_config.get("holdings", [])}
    watchlist_map = {w["ticker"]: {"ticker": w["ticker"], "name": w["ticker"],
                                   "sector": "watchlist", "role": "watchlist"}
                     for w in holdings_config.get("watchlist", [])}
    all_assets = {**holdings_map, **watchlist_map}

    console.rule(f"[bold cyan]Per-asset summaries — {raw.date} ({MODEL})")

    summaries: dict[str, PerAssetSummary] = {}

    for ticker, asset_info in all_assets.items():
        news_block = _build_news_block(ticker, raw)
        prompt = Template(PROMPT_TEMPLATE).render(
            ticker=ticker,
            name=asset_info.get("name", ticker),
            sector=asset_info.get("sector", ""),
            role=asset_info.get("role", ""),
            news_and_filings=news_block,
        )

        try:
            summary = _call_llm(prompt, ticker)
            summaries[ticker] = summary

            badge = "📰" if summary.has_material_news else "—"
            sentiment_color = {"bullish": "green", "bearish": "red",
                               "neutral": "white", "mixed": "yellow"}.get(summary.sentiment, "white")
            console.print(
                f"  {badge} [bold]{ticker}[/bold]  "
                f"[{sentiment_color}]{summary.sentiment}[/{sentiment_color}]  "
                f"{len(summary.key_events)} events  "
                + (f"→ also affects: {', '.join(summary.second_order_tickers)}" if summary.second_order_tickers else "")
            )

        except Exception as e:
            console.print(f"  [red]✗ {ticker}: {e}")

    _save(summaries, raw.date, raw.report_type)
    _print_table(summaries)
    return summaries


def _save(summaries: dict[str, PerAssetSummary], date: str, report_type: str = "premarket") -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"per_asset_{report_type}_{date}.json"
    data = {ticker: s.model_dump() for ticker, s in summaries.items()}
    out_path.write_text(json.dumps(data, indent=2))
    console.print(f"\n[bold green]Saved → {out_path}")


def _print_table(summaries: dict[str, PerAssetSummary]) -> None:
    console.rule("[bold]Summary")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Ticker", width=7)
    table.add_column("Sentiment", width=10)
    table.add_column("Material", width=8)
    table.add_column("Key events", width=60)

    for ticker, s in summaries.items():
        color = {"bullish": "green", "bearish": "red",
                 "neutral": "white", "mixed": "yellow"}.get(s.sentiment, "white")
        events_preview = " / ".join(s.key_events[:2])[:60] if s.key_events else s.skip_reason[:60]
        table.add_row(
            ticker,
            f"[{color}]{s.sentiment}[/{color}]",
            "yes" if s.has_material_news else "no",
            events_preview,
        )

    console.print(table)
