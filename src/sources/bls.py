"""US BLS Public Data API — the origin of CPI, PPI and the jobs report.

FRED re-publishes these series, but its copy lands well after the 8:30 ET
release: measured lags were CPI +38 min, payrolls +54 min, PPI +110 min (FRED
`last_updated`, Oct 2026), and one CPI day still showed the old month at 11:50
ET. The first pre-market tick runs at ~08:33 ET, so FRED alone almost never has
today's print in time. BLS's own API carries it at release time, so BLS series
are read here first and FRED is the fallback.

Keyless v1 allows 25 queries/day and 25 series per query; a free BLS_API_KEY
switches to v2 (500/day, 50 series), which matters on shared cloud runner IPs.
Best-effort like every macro source: any failure returns {} and the caller
falls back to FRED.
"""

import os
import time
from datetime import date

import httpx

from src.timeutil import now_utc, to_et

_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
_V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
_TIMEOUT = 20
_YEARS_BACK = 2          # ≥13 monthly points even in January, for y/y
_TTL_SECONDS = 600       # one collect run asks twice; spend one query, not two

_cache: dict[tuple[str, ...], tuple[float, dict[str, list[tuple[date, float]]]]] = {}


def fetch_series(series_ids: list[str]) -> dict[str, list[tuple[date, float]]]:
    """Monthly observations per BLS series id, newest first, as (reference month,
    value). Series BLS didn't return are absent. Failure → {}."""
    ids = tuple(sorted(set(series_ids)))
    if not ids:
        return {}
    hit = _cache.get(ids)
    if hit and time.time() - hit[0] < _TTL_SECONDS:
        return hit[1]

    year = to_et(now_utc()).year
    body: dict = {"seriesid": list(ids), "startyear": str(year - _YEARS_BACK), "endyear": str(year)}
    key = os.environ.get("BLS_API_KEY", "").strip()
    if key:
        body["registrationkey"] = key
    try:
        r = httpx.post(_V2 if key else _V1, json=body,
                       headers={"User-Agent": "premarket-radar"}, timeout=_TIMEOUT)
        r.raise_for_status()
        j = r.json()
        if j.get("status") != "REQUEST_SUCCEEDED":
            # Over the daily quota BLS still answers 200, with this status + a message.
            print(f"[bls] {j.get('status')}: {' '.join(j.get('message') or [])} — falling back to FRED")
            return {}
    except Exception as e:
        print(f"[bls] fetch failed: {e} — falling back to FRED")
        return {}

    out: dict[str, list[tuple[date, float]]] = {}
    for s in j.get("Results", {}).get("series", []):
        obs = []
        for d in s.get("data", []):
            period = d.get("period", "")
            if not (period.startswith("M") and period[1:].isdigit() and 1 <= int(period[1:]) <= 12):
                continue                      # M13 = annual average, not a month
            try:
                obs.append((date(int(d["year"]), int(period[1:]), 1), float(d["value"])))
            except (ValueError, KeyError):
                pass                          # "-" = not available
        if obs:
            out[s["seriesID"]] = sorted(obs, reverse=True)
    _cache[ids] = (time.time(), out)
    return out
