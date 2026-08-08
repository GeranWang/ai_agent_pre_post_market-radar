import os
import time
from datetime import datetime, timedelta

import httpx
from pydantic import BaseModel

from src.sources.source_grade import classify_source
from src.timeutil import ET, now_utc, to_et


BASE_URL = "https://finnhub.io/api/v1"
_TIMEOUT = 20
_RETRIES = 2  # extra attempts after the first, on transient network errors only


def _get_key() -> str:
    key = os.environ.get("FINNHUB_API_KEY", "")
    if not key:
        raise RuntimeError("FINNHUB_API_KEY not set in environment")
    return key


def _get(path: str, params: dict) -> dict | list:
    params["token"] = _get_key()
    last_exc: Exception | None = None
    for attempt in range(_RETRIES + 1):
        try:
            r = httpx.get(f"{BASE_URL}{path}", params=params, timeout=_TIMEOUT)
            r.raise_for_status()  # 4xx/5xx → HTTPStatusError, NOT retried here
            return r.json()
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_exc = e
            if attempt < _RETRIES:
                time.sleep(1.5 * (attempt + 1))  # 1.5s, 3.0s backoff
    raise last_exc  # type: ignore[misc]


class NewsItem(BaseModel):
    ticker: str
    headline: str
    summary: str
    source: str                       # = original_publisher (kept for back-compat)
    url: str
    published_at: str
    via: str = ""  # constituent ticker this item was sourced through, for ETF
                   # holdings (e.g. SMH news pulled via NVDA). "" = direct news.
    # Deterministic source grading (preprocessing, not LLM — see source_grade.py).
    api_provider: str = "Finnhub"     # the aggregator API we pulled it through
    original_publisher: str = ""      # the hosting platform Finnhub reports (Yahoo…)
    source_type: str = "unknown"      # primary_official | tier_1_media | secondary_media | social | unknown
    is_primary_source: bool = False
    source_confidence: str = "low"    # high | low


class EarningsEvent(BaseModel):
    ticker: str
    company: str
    date: str
    hour: str | None  # "bmo" before market open, "amc" after market close
    eps_estimate: float | None
    revenue_estimate: float | None


def fetch_company_news(ticker: str, days_back: int = 1) -> list[NewsItem]:
    et = ET
    today = to_et(now_utc()).date()
    from_date = (today - timedelta(days=days_back)).isoformat()
    to_date = today.isoformat()

    try:
        data = _get("/company-news", {"symbol": ticker, "from": from_date, "to": to_date})
    except (httpx.TimeoutException, httpx.TransportError) as e:
        print(f"[finnhub] company-news {ticker}: {e} — skipping this ticker")
        return []
    if not isinstance(data, list):
        return []

    items = []
    for item in data[:15]:  # cap at 15 per ticker to control token usage
        publisher = item.get("source", "")
        grade = classify_source(publisher, api_provider="Finnhub", url=item.get("url", ""))
        items.append(NewsItem(
            ticker=ticker,
            headline=item.get("headline", ""),
            summary=item.get("summary", ""),
            source=publisher,
            url=item.get("url", ""),
            published_at=datetime.fromtimestamp(item.get("datetime", 0), tz=et).isoformat(),
            api_provider="Finnhub",
            original_publisher=publisher,
            **grade,
        ))
    return items


def fetch_earnings_calendar(date: str | None = None) -> list[EarningsEvent]:
    if date is None:
        date = to_et(now_utc()).date().isoformat()

    try:
        data = _get("/calendar/earnings", {"from": date, "to": date})
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            print("[finnhub] earnings calendar: 403 (paid plan required) — skipping")
            return []
        raise
    earnings_raw = data.get("earningsCalendar", []) if isinstance(data, dict) else []

    events = []
    for e in earnings_raw:
        events.append(EarningsEvent(
            ticker=e.get("symbol", ""),
            company=e.get("company", ""),
            date=e.get("date", ""),
            hour=e.get("hour"),
            eps_estimate=e.get("epsEstimate"),
            revenue_estimate=e.get("revenueEstimate"),
        ))
    return events
