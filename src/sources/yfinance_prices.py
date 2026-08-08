import math
import yfinance as yf
from datetime import date, datetime
from pydantic import BaseModel

from src.timeutil import ET, now_utc, to_et


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not math.isnan(x)


class PremarketQuote(BaseModel):
    ticker: str
    current_price: float | None
    previous_close: float | None
    premarket_price: float | None
    premarket_change_pct: float | None
    volume: int | None
    fetched_at: str


class SessionResult(BaseModel):
    """End-of-day result for the post-close report: today's close, the full-session
    move, and after-hours (post-market) drift if the feed exposes it."""
    ticker: str
    close_price: float | None
    previous_close: float | None
    day_change_pct: float | None
    after_hours_price: float | None
    after_hours_change_pct: float | None   # vs today's close
    volume: int | None
    fetched_at: str


def _session_date(info: dict):
    """Calendar date (ET) that regularMarketPrice belongs to, or None."""
    rmt = info.get("regularMarketTime")
    if not rmt:
        return None
    try:
        return datetime.fromtimestamp(int(rmt), ET).date()
    except Exception:
        return None


def last_session_date(ref_ticker: str = "SPY") -> date | None:
    """ET date of the most recent completed regular session, read from a liquid
    reference ticker's regularMarketTime. Pre-market (before today's open) this
    is the previous trading day — ground truth for the content window, so we
    don't model holidays. None if the price feed is unavailable."""
    try:
        return _session_date(yf.Ticker(ref_ticker).info)
    except Exception:
        return None


def market_state(ref_ticker: str = "SPY") -> str | None:
    """Live US-equity session state from a liquid reference ticker, as Yahoo
    reports it: PREPRE / PRE / REGULAR / POST / POSTPOST / CLOSED.

    "CLOSED" is what the feed returns on weekends *and* market holidays, which
    makes this the empirical holiday signal the scheduler needs at 08:45 ET —
    before the open, when no session data exists yet to infer from. Same
    principle as last_session_date(): probe the market, don't model a calendar.
    None if the price feed is unavailable (caller should fail open).
    """
    try:
        state = yf.Ticker(ref_ticker).info.get("marketState")
        return str(state).upper() if state else None
    except Exception:
        return None


def _prev_close(t: yf.Ticker, info: dict) -> float | None:
    """Most recent *completed* regular-session close (e.g. yesterday's close).

    The hard cases:
    - yfinance's info['previousClose'] means "the close before the last session",
      so during pre-market it returns *two* days ago, not yesterday.
    - The daily history bar for the last session is often still NaN (not settled)
      while pre-market is running, so reading history alone falls back too far.

    The reliable signal is regularMarketPrice + regularMarketTime: during
    pre-market (before today's open) regularMarketPrice still holds the last
    completed session's close, and regularMarketTime tells us which day it is.
    """
    today = to_et(now_utc()).date()
    rmp = info.get("regularMarketPrice")
    sess = _session_date(info)

    # Pre-market today: regularMarketPrice is still the last completed close.
    if _is_num(rmp) and sess is not None and sess < today:
        return round(float(rmp), 2)

    # Today already traded (open / closed): prior session close = previousClose.
    for key in ("previousClose", "regularMarketPreviousClose"):
        v = info.get(key)
        if _is_num(v):
            return round(float(v), 2)

    # Fallback: last settled (non-NaN) daily bar that isn't today's.
    try:
        hist = t.history(period="7d", interval="1d")
        for ts in reversed(hist.index):
            bar_date = ts.date() if hasattr(ts, "date") else ts
            if bar_date == today:
                continue
            close = hist.loc[ts, "Close"]
            if _is_num(close):
                return round(float(close), 2)
    except Exception:
        pass
    return None


def fetch_premarket(tickers: list[str]) -> list[PremarketQuote]:
    results = []
    et_now = to_et(now_utc()).isoformat()
    today = to_et(now_utc()).date()

    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            info = t.info

            # Baseline = most recent completed regular-session close (e.g. yesterday).
            prev_close = _prev_close(t, info)

            premarket = info.get("preMarketPrice")
            premarket = premarket if _is_num(premarket) else None

            # A "live" price only counts if it's from *today's* session; otherwise
            # regularMarketPrice is just the baseline again (pre-market before open).
            rmp = info.get("regularMarketPrice")
            live = rmp if (_is_num(rmp) and _session_date(info) == today) else None

            # Reference "now" price: pre-market if trading, else today's live price.
            ref = premarket if premarket is not None else live

            if ref is not None and prev_close:
                change_pct = round((ref - prev_close) / prev_close * 100, 2)
            else:
                # No fresh price yet (e.g. run before pre-market opens) → unavailable.
                change_pct = None

            current = ref if ref is not None else prev_close

            results.append(PremarketQuote(
                ticker=ticker,
                current_price=current,
                previous_close=prev_close,
                premarket_price=premarket,
                premarket_change_pct=change_pct,
                volume=info.get("regularMarketVolume"),
                fetched_at=et_now,
            ))
        except Exception as e:
            results.append(PremarketQuote(
                ticker=ticker,
                current_price=None,
                previous_close=None,
                premarket_price=None,
                premarket_change_pct=None,
                volume=None,
                fetched_at=et_now,
            ))

    return results


def fetch_session_result(tickers: list[str]) -> list[SessionResult]:
    """Post-close: today's regular-session close + day move (+ after-hours drift).

    After the close, `regularMarketPrice` is today's settled close and
    `regularMarketChangePercent` is the full-day move; `postMarketPrice` (when
    present) is the after-hours last. If the run happens before the close settles,
    fields degrade to None (renderer shows them unavailable) rather than guessing.
    """
    results = []
    et_now = to_et(now_utc()).isoformat()
    today = to_et(now_utc()).date()

    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            info = t.info

            prev_close = _prev_close(t, info)
            rmp = info.get("regularMarketPrice")
            # A settled close only counts once today's session has traded.
            close = rmp if (_is_num(rmp) and _session_date(info) == today) else None

            if close is not None and prev_close:
                day_change = round((close - prev_close) / prev_close * 100, 2)
            else:
                day_change = None

            post = info.get("postMarketPrice")
            post = post if _is_num(post) else None
            if post is not None and close:
                ah_change = round((post - close) / close * 100, 2)
            else:
                ah_change = None

            results.append(SessionResult(
                ticker=ticker,
                close_price=close if close is not None else prev_close,
                previous_close=prev_close,
                day_change_pct=day_change,
                after_hours_price=post,
                after_hours_change_pct=ah_change,
                volume=info.get("regularMarketVolume"),
                fetched_at=et_now,
            ))
        except Exception:
            results.append(SessionResult(
                ticker=ticker, close_price=None, previous_close=None,
                day_change_pct=None, after_hours_price=None,
                after_hours_change_pct=None, volume=None, fetched_at=et_now,
            ))

    return results
