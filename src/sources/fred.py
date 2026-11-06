"""Fill the released `actual` on economic-calendar events from official data.

The ForexFactory feed gives schedule + estimate + previous but never the
released value. FMP's calendar (which carries `actual`) moved behind a paid plan
in 2025, so for the *free* path we read the actual from the series themselves
and compute the headline transform (m/m %, y/y %, level, or the monthly change)
per series, then attach it to the matching US calendar event.

Series are keyed by their FRED id. BLS-origin series (CPI, PPI, jobs report)
are read from the BLS API first, because FRED's copy lags the 8:30 ET release
by up to ~2 h (see `bls.py`); FRED covers BEA's PCE and Census's retail sales
(measured lags +13 / +8 min) and is the fallback for everything.

This only enriches a small set of high-impact US macro releases (the ones that
actually move a US-equity portfolio). Everything else keeps `actual=None`.

No FRED key → BLS series still resolve; the FRED-only ones stay `actual=None`.

NOTE: the series ids + transforms below must be verified live against known
headline prints — SA vs NSA matters (BLS reports CPI m/m seasonally adjusted but
y/y not). Treat any unverified row as provisional.
"""

import os
from datetime import date, datetime

import httpx
from pydantic import BaseModel

from src.sources import bls
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
    (("average", "hourly", "earnings", "m/m"), "CES0500000003", "mom_pct"),  # AHE, total private, SA
    (("core", "retail", "m/m"),  "RSFSXMV", "mom_pct"),  # retail sales ex-autos
    (("retail", "sales", "m/m"), "RSAFS",   "mom_pct"),  # retail sales
]


# FRED id → the BLS series it mirrors. Each pair was checked value-for-value
# against FRED (Sep 2026 prints, 2026-11-06); AHE's m/m also matches the feed's
# `previous` (+0.1%).
_BLS_MIRROR = {
    "CPIAUCSL": "CUSR0000SA0",         # CPI-U all items, SA
    "CPIAUCNS": "CUUR0000SA0",         # CPI-U all items, NSA
    "CPILFESL": "CUSR0000SA0L1E",      # core CPI, SA
    "CPILFENS": "CUUR0000SA0L1E",      # core CPI, NSA
    "PPIFIS":   "WPSFD4",              # PPI final demand, SA
    "PPIFES":   "WPSFD49104",          # PPI final demand less foods & energy, SA
    "PAYEMS":   "CES0000000001",       # total nonfarm employment, SA (thousands)
    "UNRATE":   "LNS14000000",         # unemployment rate, SA
    "CES0500000003": "CES0500000003",  # average hourly earnings, total private, SA
}


def _load(series_ids: list[str], key: str) -> dict[str, tuple[str, list[tuple[date, float]]]]:
    """FRED id → (source, observations newest first). BLS-mirrored series come
    from one batched BLS query; FRED (when keyed) fills whatever BLS didn't return
    and is the only source for the rest. A series with no data is absent."""
    wanted = list(dict.fromkeys(series_ids))
    mirrored = any(sid in _BLS_MIRROR for sid in wanted)
    from_bls = bls.fetch_series(sorted(_BLS_MIRROR.values())) if mirrored else {}  # one query serves every caller
    out: dict[str, tuple[str, list[tuple[date, float]]]] = {}
    for sid in wanted:
        obs = from_bls.get(_BLS_MIRROR.get(sid, ""))
        if obs:
            out[sid] = ("BLS", obs)
            continue
        if not key:
            continue
        try:
            obs = _observations(sid, key)
        except Exception as e:
            print(f"[fred] {sid}: {e} — skipping")
            continue
        if obs:
            out[sid] = ("FRED", obs)
    return out


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
    label: str            # human label, e.g. "CPI y/y"
    value: str            # formatted headline figure, e.g. "4.5%"
    ref_month: str        # reference month of the reading, "YYYY-MM"
    series_id: str        # FRED id of the series (the key, whichever source served it)
    source: str = "FRED"  # "BLS" | "FRED" — where the value was actually read


def latest_macro_readings() -> list[MacroReading]:
    """Latest *official* reading for each tracked US release (with its reference
    month), regardless of whether it's on today's calendar."""
    key = os.environ.get("FRED_API_KEY", "").strip()
    series = _load([sid for _, sid, _ in _READINGS], key)
    out: list[MacroReading] = []
    for label, series_id, transform in _READINGS:
        if series_id not in series:
            continue
        source, obs = series[series_id]
        value = _apply(transform, obs)
        if value is not None:
            out.append(MacroReading(
                label=label, value=value, ref_month=obs[0][0].strftime("%Y-%m"),
                series_id=series_id, source=source,
            ))
    return out


def _match(title: str) -> tuple[str, str] | None:
    t = title.lower()
    for keywords, series_id, transform in _RULES:
        if all(k in t for k in keywords):
            return series_id, transform
    return None


def enrich_with_actuals(events: list[EconomicEvent], date: str) -> list[EconomicEvent]:
    """Attach `actual` to matching US events (BLS first, then FRED)."""
    key = os.environ.get("FRED_API_KEY", "").strip()
    hits = {i: _match(ev.event) for i, ev in enumerate(events)
            if ev.country == "US" and ev.actual is None}
    hits = {i: h for i, h in hits.items() if h is not None}
    if not hits:
        return events
    series = _load([sid for sid, _ in hits.values()], key)

    try:
        target = datetime.strptime(date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        target = to_et(now_utc()).date()   # was naive datetime.now() — a latent bug

    for i, (series_id, transform) in hits.items():
        if series_id not in series:
            continue
        source, obs = series[series_id]
        # These releases all report the *prior* calendar month, so a fresh
        # print's reference month is target_month − 1. If the latest
        # observation is older, today's number isn't out yet — skip it
        # rather than mislabel last month's value as today's actual.
        if obs[0][0] >= _prior_month(target):
            events[i].actual = _apply(transform, obs)
        else:
            print(f"[{source.lower()}] {series_id} for '{events[i].event}': latest is "
                  f"{obs[0][0]:%Y-%m}, today's print not out yet — leaving actual empty")
    return events
