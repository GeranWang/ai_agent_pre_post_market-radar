"""ETF profile resolution via yfinance — data-driven, no hardcoded ticker→theme map.

For an ETF, per-ticker company news is usually empty or junk (nobody writes news
about the fund symbol itself). What a holder actually cares about is the fund's
*theme* and its *underlying constituents*. yfinance exposes both live:

  - info.quoteType / info.category / info.longName  → what the fund is
  - get_funds_data().top_holdings                   → its largest holdings

So instead of mapping "IAUI → gold" by hand (which breaks the moment the holding
changes), we resolve every ETF's category + top holdings at runtime. An equity
ETF (SPY, SMH, GDX, IGV, URA…) yields real constituent tickers whose news we can
fetch; a physical-commodity fund (a gold trust) yields fund/cash holdings with no
company news, and there the category string carries the theme for the LLM to read
against the macro snapshot (dollar, real rates).
"""
import warnings

import yfinance as yf
from pydantic import BaseModel

warnings.filterwarnings("ignore")


class ETFProfile(BaseModel):
    ticker: str
    is_etf: bool
    category: str = ""        # e.g. "Equity Precious Metals", "Technology", "Large Blend"
    long_name: str = ""
    holdings: list[str] = []  # top holdings (tickers) as reported by yfinance; may be
                              # empty, foreign-listed, or fund/cash for commodity funds


def fetch_etf_profile(ticker: str) -> ETFProfile:
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception:
        return ETFProfile(ticker=ticker, is_etf=False)

    is_etf = str(info.get("quoteType", "")).upper() == "ETF"
    long_name = info.get("longName", "") or ""
    if not is_etf:
        return ETFProfile(ticker=ticker, is_etf=False, long_name=long_name)

    holdings: list[str] = []
    try:
        fd = t.get_funds_data()
        th = fd.top_holdings
        if th is not None and len(th):
            holdings = [str(x) for x in th.index[:8]]
    except Exception:
        pass

    return ETFProfile(
        ticker=ticker,
        is_etf=True,
        category=info.get("category", "") or "",
        long_name=long_name,
        holdings=holdings,
    )


def fetch_etf_profiles(tickers: list[str]) -> dict[str, ETFProfile]:
    return {tk: fetch_etf_profile(tk) for tk in tickers}


def newsable_holdings(profile: ETFProfile, cap: int = 5) -> list[str]:
    """Subset of top holdings we can meaningfully fetch US company-news for.

    Drops foreign-listed symbols (a '.' suffix like AEM.TO — Finnhub company-news
    is US-focused) and caps the count to control API calls / token budget. Money-
    market or fund holdings are left in: fetching them simply returns empty, which
    is harmless, and filtering them by name pattern would risk dropping real tickers.
    """
    out = []
    for h in profile.holdings:
        if "." in h:
            continue
        out.append(h)
        if len(out) >= cap:
            break
    return out
