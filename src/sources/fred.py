"""Fill the released `actual` on economic-calendar events using FRED.

The ForexFactory feed gives schedule + estimate + previous but never the
released value. FMP's calendar (which carries `actual`) moved behind a paid plan
in 2025, so for the *free* path we read the actual from FRED: the underlying
BLS/BEA series update on release day, so at 9:00 ET the latest observation is
the 8:30 print. We compute the headline transform (m/m %, y/y %, level, or the
monthly change) per series and attach it to the matching US calendar event.

This only enriches a small set of high-impact US macro releases (the ones that
actually move a US-equity portfolio). Everything else keeps `actual=None`.

No FRED key → events pass through unchanged (estimate/previous still present).

NOTE: the series ids + transforms below must be verified live against known
headline prints — SA vs NSA matters (BLS reports CPI m/m seasonally adjusted but
y/y not). Treat any unverified row as provisional.
"""

import os
from datetime import date, datetime

import httpx
from pydantic import BaseModel

from src.sources.forexfactory import EconomicEvent
from src.timeutil import now_utc, to_et

_FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
_TIMEOUT = 20


def _prior_month(d: date) -> date:
    """First day of the calendar month before `d`."""
    return date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)

# Each rule: (keywords that must all appear in the lowercased US event title,
#             FRED series id, transform). First matching rule wins, so more
#             specific rules (e.g. "core cpi") come before general ones.
_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("core", "cpi", "m/m"), "CPILFESL", "mom_pct"),   # core CPI, SA
    (("core", "cpi", "y/y"), "CPILFENS", "yoy_pct"),   # core CPI, NSA
    (("cpi", "m/m"),         "CPIAUCSL", "mom_pct"),   # headline CPI, SA
    (("cpi", "y/y"),         "CPIAUCNS", "yoy_pct"),   # headline CPI, NSA
    (("core", "ppi", "m/m"), "PPIFES",   "mom_pct"),   # core PPI final demand, SA
    (("ppi", "m/m"),         "PPIFIS",   "mom_pct"),   # PPI final demand, SA
    (("core", "pce", "m/m"), "PCEPILFE", "mom_pct"),   # core PCE price index, SA
    (("pce", "m/m"),         "PCEPI",    "mom_pct"),   # headline PCE price index, SA
    (("non-farm", "employment"), "PAYEMS", "mom_diff_k"),  # NFP change
    (("nonfarm", "payroll"),     "PAYEMS", "mom_diff_k"),
    (("unemployment", "rate"),   "UNRATE", "level_pct"),
    (("core", "retail", "m/m"),  "RSFSXMV", "mom_pct"),  # retail sales ex-autos
    (("retail", "sales", "m/m"), "RSAFS",   "mom_pct"),  # retail sales
]


def _observations(series_id: str, key: str) -> list[tuple[date, float]]:
    """Latest observations (newest first) as (reference-month, value), dropping
    missing ('.') points."""
    r = httpx.get(_FRED_URL, params={
        "series_id": series_id, "api_key": key, "file_type": "json",
        "sort_order": "desc", "limit": 14,
    }, timeout=_TIMEOUT)
    r.raise_for_status()
    out = []
    for o in r.json().get("observations", []):
        v = o.get("value")
        if v in (None, "", "."):
            continue
        try:
            out.append((datetime.strptime(o["date"], "%Y-%m-%d").date(), float(v)))
        except (ValueError, KeyError):
            pass
    return out


def _apply(transform: str, obs: list[tuple[date, float]]) -> str | None:
    """Turn the raw series into the headline figure, formatted like the feed."""
    v = [o[1] for o in obs]
    if transform == "mom_pct":
        if len(v) < 2 or v[1] == 0:
            return None
        return f"{(v[0] / v[1] - 1) * 100:.1f}%"
    if transform == "yoy_pct":
        if len(v) < 13 or v[12] == 0:
            return None
        return f"{(v[0] / v[12] - 1) * 100:.1f}%"
    if transform == "level_pct":
        return f"{v[0]:.1f}%" if v else None
    if transform == "mom_diff_k":  # PAYEMS is in thousands; report the change
        if len(v) < 2:
            return None
        return f"{round(v[0] - v[1]):+d}K"
    return None


# Headline US releases to always surface as the latest *official* reading, so
# the brief cites these instead of a number quoted in a news article — even on
# days when the release isn't on the calendar (it printed earlier in the week).
_READINGS: list[tuple[str, str, str]] = [
    ("CPI y/y",            "CPIAUCNS", "yoy_pct"),
    ("Core CPI y/y",       "CPILFENS", "yoy_pct"),
    ("CPI m/m",            "CPIAUCSL", "mom_pct"),
    ("Core CPI m/m",       "CPILFESL", "mom_pct"),
    ("PPI m/m",            "PPIFIS",   "mom_pct"),
    ("Core PCE m/m",       "PCEPILFE", "mom_pct"),
    ("Nonfarm payrolls Δ", "PAYEMS",   "mom_diff_k"),
    ("Unemployment rate",  "UNRATE",   "level_pct"),
    ("Retail sales m/m",   "RSAFS",    "mom_pct"),
]


class MacroReading(BaseModel):
    label: str       # human label, e.g. "CPI y/y"
    value: str       # formatted headline figure, e.g. "4.5%"
    ref_month: str   # reference month of the reading, "YYYY-MM"
    series_id: str   # FRED series the value came from


def latest_macro_readings() -> list[MacroReading]:
    """Latest *official* reading for each tracked US release (with its reference
    month), regardless of whether it's on today's calendar. No key → empty."""
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        return []

    cache: dict[str, list[tuple[date, float]]] = {}
    out: list[MacroReading] = []
    for label, series_id, transform in _READINGS:
        try:
            if series_id not in cache:
                cache[series_id] = _observations(series_id, key)
            obs = cache[series_id]
            value = _apply(transform, obs)
            if value is not None and obs:
                out.append(MacroReading(
                    label=label, value=value,
                    ref_month=obs[0][0].strftime("%Y-%m"), series_id=series_id,
                ))
        except Exception as e:
            print(f"[fred] reading {series_id} ({label}): {e} — skipping")
    return out


def _match(title: str) -> tuple[str, str] | None:
    t = title.lower()
    for keywords, series_id, transform in _RULES:
        if all(k in t for k in keywords):
            return series_id, transform
    return None


def enrich_with_actuals(events: list[EconomicEvent], date: str) -> list[EconomicEvent]:
    """Attach `actual` to matching US events from FRED. No key → unchanged."""
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        return events

    try:
        target = datetime.strptime(date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        target = to_et(now_utc()).date()   # was naive datetime.now() — a latent bug

    cache: dict[str, list[tuple[date, float]]] = {}
    for ev in events:
        if ev.country != "US" or ev.actual is not None:
            continue
        hit = _match(ev.event)
        if hit is None:
            continue
        series_id, transform = hit
        try:
            if series_id not in cache:
                cache[series_id] = _observations(series_id, key)
            obs = cache[series_id]
            # These releases all report the *prior* calendar month, so a fresh
            # print's reference month is target_month − 1. If FRED's latest
            # observation is older, today's number isn't ingested yet — skip it
            # rather than mislabel last month's value as today's actual.
            if obs and obs[0][0] >= _prior_month(target):
                ev.actual = _apply(transform, obs)
        except Exception as e:
            print(f"[fred] {series_id} for '{ev.event}': {e} — leaving actual empty")
    return events
