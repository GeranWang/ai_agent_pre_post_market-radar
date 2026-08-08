import csv
import io
import math
import time
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel

import httpx

from src.timeutil import now_utc, to_et

# Treasury yields (2Y/10Y) come from the U.S. Treasury's official Daily Treasury
# Par Yield Curve CSV — no API key required. This is the same underlying series
# FRED republishes as DGS2/DGS10, so the values are consistent. We keep the FRED
# field names (dgs2/dgs10) so the rest of the pipeline is unchanged.
_TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all"
    "?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv"
)
# Yields update once per business day; cache the CSV and fall back to a stale
# copy on a failed fetch rather than losing the snapshot entirely.
_TREASURY_CACHE = Path(__file__).parent.parent.parent / "output/intermediate/_treasury_yields.csv"
_TREASURY_CACHE_TTL_SECONDS = 6 * 3600


class MacroSnapshot(BaseModel):
    # Treasury yields come from the U.S. Treasury daily yield curve (no key).
    dgs2: float | None = None
    dgs2_prev: float | None = None
    dgs10: float | None = None
    dgs10_prev: float | None = None
    # DXY and VIX come from yfinance (no API key required).
    dxy: float | None = None
    dxy_prev: float | None = None
    vix: float | None = None
    vix_prev: float | None = None
    fetched_at: str
    note: str = ""


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not math.isnan(x)


def _yf_quote(ticker: str) -> tuple[float | None, float | None]:
    """(latest, previous_close) for an index ticker via yfinance; no key needed."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        latest = info.get("regularMarketPrice")
        prev = info.get("regularMarketPreviousClose") or info.get("previousClose")
        latest = round(float(latest), 2) if _is_num(latest) else None
        prev = round(float(prev), 2) if _is_num(prev) else None
        return latest, prev
    except Exception:
        return None, None


def _fetch_treasury_csv() -> str | None:
    """Current-year Treasury yield-curve CSV text, with on-disk caching."""
    if _TREASURY_CACHE.exists() and (time.time() - _TREASURY_CACHE.stat().st_mtime) < _TREASURY_CACHE_TTL_SECONDS:
        return _TREASURY_CACHE.read_text()
    year = to_et(now_utc()).year
    try:
        r = httpx.get(
            _TREASURY_URL.format(year=year),
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
            follow_redirects=True,
        )
        r.raise_for_status()
        _TREASURY_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _TREASURY_CACHE.write_text(r.text)
        return r.text
    except Exception as e:
        if _TREASURY_CACHE.exists():
            print(f"[treasury] fetch failed ({e}); using cached yields")
            return _TREASURY_CACHE.read_text()
        print(f"[treasury] yield-curve fetch failed: {e}")
        return None


def _parse_yield(row: dict, col: str) -> float | None:
    raw = (row.get(col) or "").strip()
    try:
        return round(float(raw), 2)
    except ValueError:
        return None


def _fetch_treasury_yields() -> tuple[float | None, float | None, float | None, float | None, str | None]:
    """(dgs2, dgs2_prev, dgs10, dgs10_prev, error_note) from the Treasury CSV.

    The CSV is ordered most-recent-first, so row 0 is the latest session and
    row 1 the prior one.
    """
    text = _fetch_treasury_csv()
    if not text:
        return None, None, None, None, "treasury yield-curve unavailable"
    try:
        rows = list(csv.DictReader(io.StringIO(text)))
    except Exception as e:
        return None, None, None, None, f"treasury CSV parse error: {e}"
    if not rows:
        return None, None, None, None, "treasury CSV had no rows"

    latest = rows[0]
    prev = rows[1] if len(rows) >= 2 else {}
    dgs2 = _parse_yield(latest, "2 Yr")
    dgs10 = _parse_yield(latest, "10 Yr")
    dgs2_prev = _parse_yield(prev, "2 Yr")
    dgs10_prev = _parse_yield(prev, "10 Yr")
    note = None if (dgs2 is not None or dgs10 is not None) else "treasury yields missing from CSV"
    return dgs2, dgs2_prev, dgs10, dgs10_prev, note


def fetch_macro_snapshot() -> MacroSnapshot:
    et_now = to_et(now_utc()).isoformat()
    notes: list[str] = []

    # DXY + VIX from yfinance — always available, no API key.
    dxy, dxy_prev = _yf_quote("DX-Y.NYB")
    vix, vix_prev = _yf_quote("^VIX")
    if dxy is None and vix is None:
        notes.append("yfinance macro (DXY/VIX) unavailable")

    # Treasury yields from the U.S. Treasury daily yield curve — no API key.
    dgs2, dgs2_prev, dgs10, dgs10_prev, yield_note = _fetch_treasury_yields()
    if yield_note:
        notes.append(yield_note)

    return MacroSnapshot(
        dgs2=dgs2, dgs2_prev=dgs2_prev,
        dgs10=dgs10, dgs10_prev=dgs10_prev,
        dxy=dxy, dxy_prev=dxy_prev,
        vix=vix, vix_prev=vix_prev,
        fetched_at=et_now,
        note="; ".join(notes),
    )
