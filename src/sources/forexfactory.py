import time
import xml.etree.ElementTree as ETree
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel

from src.timeutil import now_utc, to_et


# Economic calendar comes from the free ForexFactory weekly feed (faireconomy
# mirror). Finnhub's /calendar/economic is a paid endpoint (403 on free tier),
# so this is the no-key alternative. Times in this feed are UTC; we convert to
# US Eastern. Note: this feed carries forecast/previous only — no actuals.
FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
_UTC = ZoneInfo("UTC")
_ET = ZoneInfo("America/New_York")

# The feed rate-limits aggressively (429). It is a weekly feed, so cache the raw
# XML on disk and reuse it for a few hours; on a failed fetch, fall back to any
# existing cache (even if stale) rather than losing the calendar entirely.
_FF_CACHE = Path(__file__).parent.parent.parent / "output/intermediate/_ff_calendar_thisweek.xml"
_FF_CACHE_TTL_SECONDS = 6 * 3600


class EconomicEvent(BaseModel):
    event: str
    country: str
    time: str
    impact: str | None
    actual: str | None
    estimate: str | None
    previous: str | None


def _fetch_ff_xml() -> bytes | None:
    if _FF_CACHE.exists() and (time.time() - _FF_CACHE.stat().st_mtime) < _FF_CACHE_TTL_SECONDS:
        return _FF_CACHE.read_bytes()
    try:
        r = httpx.get(FF_CALENDAR_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.raise_for_status()
        _FF_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _FF_CACHE.write_bytes(r.content)
        return r.content
    except Exception as e:
        if _FF_CACHE.exists():
            print(f"[forexfactory] fetch failed ({e}); using cached calendar")
            return _FF_CACHE.read_bytes()
        print(f"[forexfactory] economic calendar fetch failed: {e} — skipping")
        return None


def _parse_ff_datetime(date_raw: str, time_raw: str):
    """Parse a ForexFactory event date/time (UTC) → (et_date, et_datetime).

    Returns (date, datetime_in_ET) when a precise time is present, or
    (date, None) for all-day / tentative / unparseable times. The date in the
    first slot is the ET calendar date (after UTC→ET shift when a time exists),
    used for same-day filtering.
    """
    try:
        d = datetime.strptime(date_raw.strip(), "%m-%d-%Y").date()
    except ValueError:
        return None, None

    t = (time_raw or "").strip().lower()
    if not t or t in ("all day", "tentative", "day 1", "day 2"):
        return d, None  # no precise time — keep the feed's date as-is

    try:
        tm = datetime.strptime(t, "%I:%M%p").time()
    except ValueError:
        return d, None

    dt_et = datetime.combine(d, tm, tzinfo=_UTC).astimezone(_ET)
    return dt_et.date(), dt_et


def fetch_economic_calendar(date: str | None = None) -> list[EconomicEvent]:
    """Economic calendar for a single ET date, from the ForexFactory feed."""
    if date is None:
        target = to_et(now_utc()).date()
    else:
        target = datetime.fromisoformat(date).date()

    xml_bytes = _fetch_ff_xml()
    if not xml_bytes:
        return []
    try:
        root = ETree.fromstring(xml_bytes)  # bytes → respects XML's declared encoding
    except Exception as e:
        print(f"[forexfactory] economic calendar parse failed: {e} — skipping")
        return []

    events: list[tuple] = []
    for node in root.findall("event"):
        date_raw = (node.findtext("date") or "").strip()
        time_raw = (node.findtext("time") or "").strip()

        ev_date, ev_dt = _parse_ff_datetime(date_raw, time_raw)
        if ev_date is None or ev_date != target:
            continue

        if ev_dt is not None:
            time_disp = ev_dt.strftime("%I:%M%p").lstrip("0").lower()  # "8:30am"
        else:
            time_disp = time_raw or "All Day"

        country_raw = (node.findtext("country") or "").strip()
        country = "US" if country_raw == "USD" else country_raw
        impact_raw = (node.findtext("impact") or "").strip().lower()
        forecast = (node.findtext("forecast") or "").strip()
        previous = (node.findtext("previous") or "").strip()

        events.append((
            ev_dt,
            EconomicEvent(
                event=(node.findtext("title") or "").strip(),
                country=country,
                time=time_disp,
                impact=impact_raw or None,
                actual=None,  # this feed carries forecast/previous only, no actuals
                estimate=forecast or None,
                previous=previous or None,
            ),
        ))

    # Chronological order; timed events first (by ET time), all-day events last.
    events.sort(key=lambda x: (x[0] is None, x[0]))
    return [e for _, e in events]
