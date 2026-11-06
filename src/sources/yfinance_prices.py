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


class SessionMove(BaseModel):
    """One completed regular session: its close and the move vs the session before."""
    date: str                    # YYYY-MM-DD, ET session date
    close: float
    change_pct: float | None     # None for the oldest session in the series


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


def _prev_close(t: yf.Ticker, info: dict, today: date | None = None) -> float | None:
    """Most recent *completed* regular-session close before `today` (e.g.
    yesterday's close). `today` defaults to the ET wall clock; the post-close
    report passes its session date instead, because its catch-up run happens
    after midnight, when the wall-clock day is already the next one.

    The hard cases:
    - yfinance's info['previousClose'] means "the close before the last session",
      so during pre-market it returns *two* days ago, not yesterday.
    - The daily history bar for the last session is often still NaN (not settled)
      while pre-market is running, so reading history alone falls back too far.

    The reliable signal is regularMarketPrice + regularMarketTime: during
    pre-market (before today's open) regularMarketPrice still holds the last
    completed session's close, and regularMarketTime tells us which day it is.
    """
    today = today or to_et(now_utc()).date()
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

    # Fallback: last settled (non-NaN) daily bar from before `today`.
    try:
        hist = t.history(period="7d", interval="1d")
        for ts in reversed(hist.index):
            bar_date = ts.date() if hasattr(ts, "date") else ts
            if bar_date >= today:
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


def fetch_session_result(tickers: list[str], session_date: date) -> list[SessionResult]:
    """Post-close: `session_date`'s regular-session close + day move (+ after-hours drift).

    After the close, `regularMarketPrice` is that session's settled close and
    `regularMarketChangePercent` is the full-day move; `postMarketPrice` (when
    present) is the after-hours last. These hold until the next session opens,
    which is what makes the after-midnight catch-up run work — as long as we
    compare against `session_date`, not the wall-clock day. If the session hasn't
    settled (or the next one has already opened), fields degrade to None
    (renderer shows them unavailable) rather than guessing.
    """
    results = []
    et_now = to_et(now_utc()).isoformat()

    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            info = t.info

            prev_close = _prev_close(t, info, today=session_date)
            rmp = info.get("regularMarketPrice")
            # A settled close only counts if it belongs to the reported session.
            close = rmp if (_is_num(rmp) and _session_date(info) == session_date) else None

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


def fetch_recent_sessions(tickers: list[str], through: date,
                          sessions: int = 5) -> dict[str, list[SessionMove]]:
    """The last `sessions` completed daily closes up to and including `through`,
    each with its move vs the prior close.

    Ground truth for dating price-action news. A story is often published the day
    after the move it describes ("gold just had its best day since August" lands
    the next morning), and the summarizer only sees the publish date — so without
    the real daily moves it pins yesterday's rally on today. Unadjusted closes, so
    they match the quotes; a ticker whose history fails gets an empty list.
    """
    out: dict[str, list[SessionMove]] = {}
    for ticker in tickers:
        rows: list[SessionMove] = []
        try:
            hist = yf.Ticker(ticker).history(period="1mo", interval="1d", auto_adjust=False)
            prev = None
            for ts, close in hist["Close"].items():
                if ts.date() > through or not _is_num(close):
                    continue
                close = float(close)
                change = round((close - prev) / prev * 100, 2) if prev else None
                rows.append(SessionMove(date=ts.date().isoformat(), close=round(close, 2),
                                        change_pct=change))
                prev = close
        except Exception:
            rows = []
        out[ticker] = rows[-sessions:]
    return out
