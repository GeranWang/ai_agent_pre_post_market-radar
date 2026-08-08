import os

import httpx
from datetime import timedelta
from pydantic import BaseModel

from src.timeutil import now_utc, to_et


FORM_TYPES = {"8-K", "4", "10-Q", "10-K"}


def _headers() -> dict:
    """SEC's fair-access policy requires a User-Agent identifying the requester
    with a contact address; requests without one get throttled or blocked.
    Set SEC_USER_AGENT in .env to "YourApp your@email.com".

    Read per call rather than at import time, so it can't silently fall back
    just because a caller imported this module before load_dotenv() ran.
    """
    return {"User-Agent": os.environ.get(
        "SEC_USER_AGENT", "PremarketRadar contact-not-configured@example.com")}


class Filing(BaseModel):
    ticker: str
    cik: str
    form_type: str
    filed_at: str
    description: str
    url: str


def _get_cik(ticker: str) -> str | None:
    # SEC company search returns an atom feed carrying the CIK. A transport-level
    # failure (proxy 503, timeout, connection reset) degrades to "no CIK" rather
    # than crashing the run — filings are best-effort context.
    try:
        r = httpx.get(
            f"https://www.sec.gov/cgi-bin/browse-edgar?company=&CIK={ticker}&type=10-K&dateb=&owner=include&count=1&search_text=&action=getcompany&output=atom",
            headers=_headers(),
            timeout=10,
        )
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    # Parse CIK from the atom feed
    import re
    match = re.search(r"CIK=(\d+)", r.text)
    return match.group(1) if match else None


def fetch_recent_filings(ticker: str, days_back: int = 1) -> list[Filing]:
    cik = _get_cik(ticker)
    if not cik:
        return []

    cik_padded = cik.zfill(10)
    try:
        r = httpx.get(
            f"https://data.sec.gov/submissions/CIK{cik_padded}.json",
            headers=_headers(),
            timeout=15,
        )
    except httpx.HTTPError:
        return []
    if r.status_code != 200:
        return []

    data = r.json()
    recent = data.get("filings", {}).get("recent", {})

    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    descriptions = recent.get("primaryDocument", [])
    accessions = recent.get("accessionNumber", [])

    cutoff = (to_et(now_utc()).date() - timedelta(days=days_back)).isoformat()

    filings = []
    for form, date, desc, acc in zip(forms, dates, descriptions, accessions):
        if date < cutoff:
            break
        if form not in FORM_TYPES:
            continue
        acc_clean = acc.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{desc}"
        filings.append(Filing(
            ticker=ticker,
            cik=cik,
            form_type=form,
            filed_at=date,
            description=desc,
            url=url,
        ))

    return filings
