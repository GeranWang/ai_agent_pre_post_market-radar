import json
from datetime import date, timedelta
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.schemas.raw import RawMaterial
from src.sources.etf import fetch_etf_profiles, newsable_holdings
from src.sources.finnhub import fetch_company_news, fetch_earnings_calendar
from src.sources.forexfactory import fetch_economic_calendar
from src.sources.fred import enrich_with_actuals, latest_macro_readings
from src.sources.macro import fetch_macro_snapshot
from src.sources.sec_edgar import fetch_recent_filings
from src.sources.yfinance_prices import fetch_premarket, fetch_session_result, last_session_date

console = Console()
ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = ROOT / "output/intermediate"


# How many trading sessions of history the content window covers. The brief
# still focuses on the latest session, but a single day's news often ties back
# to earlier threads, so synthesis benefits from a few prior sessions of
# context. Over-fetch is safe — the freshness label + relevance gate down-rank
# stale items, so older news stays as background rather than headline material.
CONTENT_WINDOW_SESSIONS = 5


def _resolve_anchor(today: date, anchor: date | None = None) -> date:
    """The latest *completed* session date — the newest edge of the content
    window and the primary/background boundary the prompts use.

    Read empirically from the last completed market price (ground truth —
    auto-handles weekends, holidays, half-days, unscheduled closures) instead of
    modelling a holiday calendar. Two cases force a fallback to the previous
    weekday: the price feed is unavailable, or it reports `today` (the pipeline
    was run after today's open, so regularMarketTime has flipped to today). In
    both we step back to yesterday and skip the weekend. Always returns a date
    strictly before `today`.
    """
    if anchor is None:
        anchor = last_session_date()
    if anchor is None or anchor >= today:
        anchor = today - timedelta(days=1)
        while anchor.weekday() >= 5:
            anchor -= timedelta(days=1)
    return anchor


def _content_window_days(today: date, sessions: int = CONTENT_WINDOW_SESSIONS,
                         anchor: date | None = None) -> int:
    """Days to look back so the news/filings window covers the previous
    `sessions` trading sessions.

    The content window's newest edge is "previous market close → now", not
    "today" (see `_resolve_anchor`). We can only empirically pin the *latest*
    session, so the additional `sessions - 1` of history are stepped back with
    weekday math and padded with a small buffer to absorb holidays we don't
    model. Slight over-fetch is safe — the freshness label + relevance gate
    down-rank stale items.
    """
    start = _resolve_anchor(today, anchor)
    remaining = max(sessions - 1, 0)
    while remaining:
        start -= timedelta(days=1)
        if start.weekday() < 5:  # count weekdays only as proxy sessions
            remaining -= 1

    holiday_buffer = 2 if sessions > 1 else 0
    return (today - start).days + holiday_buffer


def collect_all(holdings_config: dict, report_date: date,
                report_type: str = "premarket") -> RawMaterial:
    tickers = [h["ticker"] for h in holdings_config.get("holdings", [])]
    watchlist = [w["ticker"] for w in holdings_config.get("watchlist", [])]
    all_tickers = tickers + watchlist

    # report_date (an ET trading day) is decided by the dispatcher, not recomputed here.
    today = report_date
    date_str = today.isoformat()
    # Anchor = latest completed session (previous close). Resolved once here and
    # reused both for the lookback math and as the primary-window boundary the
    # prompts use to down-rank older sessions. _resolve_anchor normalizes the
    # after-open / feed-down cases, so this is always a date before today.
    last_session = _resolve_anchor(today)
    lookback_days = _content_window_days(today, anchor=last_session)

    console.rule(f"[bold cyan]Collect — {date_str}")
    if lookback_days > 1:
        window_start = (today - timedelta(days=lookback_days)).isoformat()
        console.print(f"[dim]Content window spans {lookback_days}d "
                      f"(~{CONTENT_WINDOW_SESSIONS} sessions, since {window_start}) — "
                      f"latest session + prior context")

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:

        premarket_quotes = []
        session_quotes = []
        if report_type == "postclose":
            task = progress.add_task("Fetching session close prices (yfinance)...", total=None)
            session_quotes = fetch_session_result(all_tickers, today)
            progress.update(task, description=f"[green]✓ Close prices — {len(session_quotes)} tickers")
            progress.stop_task(task)
        else:
            task = progress.add_task("Fetching pre-market prices (yfinance)...", total=None)
            premarket_quotes = fetch_premarket(all_tickers)
            progress.update(task, description=f"[green]✓ Pre-market prices — {len(premarket_quotes)} tickers")
            progress.stop_task(task)

        task = progress.add_task("Fetching economic calendar (ForexFactory)...", total=None)
        economic_calendar = enrich_with_actuals(fetch_economic_calendar(date_str), date_str)
        progress.update(task, description=f"[green]✓ Economic calendar — {len(economic_calendar)} events")
        progress.stop_task(task)

        task = progress.add_task("Fetching earnings calendar (Finnhub)...", total=None)
        earnings_calendar = fetch_earnings_calendar(date_str)
        progress.update(task, description=f"[green]✓ Earnings calendar — {len(earnings_calendar)} events")
        progress.stop_task(task)

        task = progress.add_task("Fetching macro snapshot (Treasury + yfinance)...", total=None)
        macro_snapshot = fetch_macro_snapshot()
        have = [k for k, v in (("DGS2", macro_snapshot.dgs2), ("DGS10", macro_snapshot.dgs10),
                               ("DXY", macro_snapshot.dxy), ("VIX", macro_snapshot.vix)) if v is not None]
        status = ", ".join(have) if have else "none available"
        progress.update(task, description=f"[green]✓ Macro snapshot — {status}")
        progress.stop_task(task)

        task = progress.add_task("Fetching latest macro releases (FRED)...", total=None)
        macro_releases = latest_macro_readings()
        progress.update(task, description=f"[green]✓ Macro releases — {len(macro_releases)} official readings")
        progress.stop_task(task)

        # Resolve which holdings are ETFs and what they hold, so we can enrich a
        # fund's thin ticker-news with its constituents' news (data-driven, no
        # hardcoded theme map). See sources/etf.py.
        task = progress.add_task("Resolving ETF profiles...", total=None)
        etf_profiles = fetch_etf_profiles(all_tickers)
        n_etf = sum(1 for p in etf_profiles.values() if p.is_etf)
        progress.update(task, description=f"[green]✓ ETF profiles — {n_etf} ETFs (constituent news enabled)")
        progress.stop_task(task)

        company_news: dict = {}
        sec_filings: dict = {}

        # Fetch each unique symbol's news at most once — an underlying (e.g. NVDA)
        # can be a constituent of several ETFs (SPY, SMH).
        _news_cache: dict[str, list] = {}

        def _news_for(symbol: str, warn: bool = True) -> list:
            if symbol not in _news_cache:
                try:
                    _news_cache[symbol] = fetch_company_news(symbol, days_back=lookback_days)
                except Exception as e:
                    _news_cache[symbol] = []
                    # Constituent enrichment is best-effort and a fund's holdings
                    # routinely include cash / money-market symbols Finnhub doesn't
                    # cover (a 4xx) — that's expected, so we stay quiet for those and
                    # only warn when a holding's OWN direct news fetch fails.
                    if warn:
                        progress.console.print(f"[yellow]  ! {symbol} news fetch failed ({type(e).__name__}); continuing without it")
            return _news_cache[symbol]

        for ticker in all_tickers:
            task = progress.add_task(f"Fetching news + filings — {ticker}...", total=None)

            # Each source is best-effort: a transient network/proxy failure on one
            # ticker degrades to empty and the run continues rather than aborting.
            news = list(_news_for(ticker))

            # For an ETF, merge in the news of its top holdings (freshest-first,
            # deduped). This turns "no news for SMH" into the semiconductor
            # constituents' actual news, and GDX into gold-miner news.
            profile = etf_profiles.get(ticker)
            n_constituent = 0
            if profile and profile.is_etf:
                seen = {(n.headline or n.url) for n in news}
                for holding in newsable_holdings(profile, cap=5):
                    # Take only the few freshest per holding so one mega-cap (e.g.
                    # NVDA in SPY) can't crowd out the other constituents — a broad
                    # ETF should read across its holdings, not mirror its top name.
                    h_items = sorted(_news_for(holding, warn=False),
                                     key=lambda n: n.published_at, reverse=True)
                    added = 0
                    for item in h_items:
                        if added >= 4:
                            break
                        key = item.headline or item.url
                        if key in seen:
                            continue
                        seen.add(key)
                        news.append(item.model_copy(update={"via": holding}))
                        added += 1
                        n_constituent += 1
                news.sort(key=lambda n: n.published_at, reverse=True)
                news = news[:20]  # cap to control token budget; freshest kept
            company_news[ticker] = news

            try:
                filings = fetch_recent_filings(ticker, days_back=lookback_days)
            except Exception as e:
                filings = []
                progress.console.print(f"[yellow]  ! {ticker} filings fetch failed ({type(e).__name__}); continuing without it")
            sec_filings[ticker] = filings

            extra = f" (+{n_constituent} via holdings)" if n_constituent else ""
            progress.update(task, description=f"[green]✓ {ticker} — {len(news)} news{extra}, {len(filings)} filings")
            progress.stop_task(task)

    raw = RawMaterial(
        report_type=report_type,
        date=date_str,
        last_session=last_session.isoformat(),
        premarket_quotes=premarket_quotes,
        session_quotes=session_quotes,
        company_news=company_news,
        sec_filings=sec_filings,
        economic_calendar=economic_calendar,
        earnings_calendar=earnings_calendar,
        macro_snapshot=macro_snapshot,
        macro_releases=macro_releases,
        etf_profiles=etf_profiles,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"raw_{report_type}_{date_str}.json"
    out_path.write_text(raw.model_dump_json(indent=2))
    console.print(f"\n[bold green]Saved → {out_path}")

    _print_summary(raw)
    return raw


def _print_summary(raw: RawMaterial) -> None:
    from rich.table import Table

    post = raw.report_type == "postclose"
    console.rule(f"[bold]{'Close' if post else 'Pre-market'} snapshot")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Ticker", width=8)
    table.add_column("Close" if post else "Prev Close", justify="right")
    table.add_column("Day %" if post else "Chg %", justify="right")
    if post:
        table.add_column("A/H %", justify="right")
    table.add_column("News", justify="right")
    table.add_column("Filings", justify="right")

    if post:
        for q in raw.session_quotes:
            chg = q.day_change_pct
            chg_str = f"{chg:+.2f}%" if chg is not None else "—"
            color = "green" if (chg or 0) >= 0 else "red"
            ah = q.after_hours_change_pct
            ah_str = f"{ah:+.2f}%" if ah is not None else "—"
            nc = len(raw.company_news.get(q.ticker, []))
            fc = len(raw.sec_filings.get(q.ticker, []))
            table.add_row(q.ticker, f"{q.close_price:.2f}" if q.close_price else "—",
                          f"[{color}]{chg_str}[/{color}]", ah_str,
                          str(nc) if nc else "—", str(fc) if fc else "—")
    else:
        for q in raw.premarket_quotes:
            chg = q.premarket_change_pct
            chg_str = f"{chg:+.2f}%" if chg is not None else "—"
            color = "green" if (chg or 0) >= 0 else "red"
            news_count = len(raw.company_news.get(q.ticker, []))
            filing_count = len(raw.sec_filings.get(q.ticker, []))
            table.add_row(q.ticker, f"{q.previous_close:.2f}" if q.previous_close else "—",
                          f"[{color}]{chg_str}[/{color}]",
                          str(news_count) if news_count else "—",
                          str(filing_count) if filing_count else "—")

    console.print(table)
    console.print(f"Economic events: {len(raw.economic_calendar)}  |  Earnings today: {len(raw.earnings_calendar)}")
    if raw.macro_snapshot.note:
        console.print(f"[yellow]Macro: {raw.macro_snapshot.note}")
