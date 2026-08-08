"""Single source of time for the pipeline.

Internal computation is anchored to **timezone-aware UTC** (`now_utc()`), so file
naming and "which day / which report" decisions never depend on the machine's local
zone or a naive `datetime.now()`. **ET is used only for trading-session / report-window
semantics** — the market runs on America/New_York — via `to_et()`.

`resolve_report()` implements the fixed-rule dispatch (test version, no auto-send):
  06:00–16:00 ET → pre-market report, for today
  16:01–23:59 ET → post-close report, for today
  00:00–05:59 ET → post-close report, for YESTERDAY (that close already happened)
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

# Report types
PREMARKET = "premarket"
POSTCLOSE = "postclose"

# Pre-market window is [06:00, 16:01) ET; everything else is post-close.
_PREMARKET_START = time(6, 0)
_PREMARKET_END = time(16, 1)   # 16:00:xx still pre-market; 16:01 flips to post-close


def now_utc() -> datetime:
    """The one 'now' — timezone-aware UTC. Everything derives from this."""
    return datetime.now(UTC)


def to_et(dt: datetime) -> datetime:
    """Convert an aware datetime to ET. Naive input is assumed UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(ET)


def resolve_report(now: datetime | None = None) -> tuple[str, date]:
    """Pick (report_type, report_date) from the current ET clock — see module docstring.

    report_date is an ET trading day; the dispatcher passes it down so no source
    module recomputes 'today' on its own.
    """
    et = to_et(now or now_utc())
    t = et.timetz().replace(tzinfo=None)
    if _PREMARKET_START <= t < _PREMARKET_END:
        return PREMARKET, et.date()
    if t >= _PREMARKET_END:                 # 16:01–23:59
        return POSTCLOSE, et.date()
    return POSTCLOSE, et.date() - timedelta(days=1)   # 00:00–05:59 → yesterday's close
