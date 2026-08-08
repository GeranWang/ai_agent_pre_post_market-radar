from pydantic import BaseModel
from src.sources.yfinance_prices import PremarketQuote, SessionResult
from src.sources.finnhub import NewsItem, EarningsEvent
from src.sources.forexfactory import EconomicEvent
from src.sources.sec_edgar import Filing
from src.sources.macro import MacroSnapshot
from src.sources.fred import MacroReading
from src.sources.etf import ETFProfile


class RawMaterial(BaseModel):
    report_type: str = "premarket"                # "premarket" | "postclose"
    date: str                                     # YYYY-MM-DD, ET trading day
    last_session: str | None = None              # YYYY-MM-DD of the latest completed
                                                  # market session (previous close). The
                                                  # primary news window; earlier sessions
                                                  # in the 5-session window are background.
    premarket_quotes: list[PremarketQuote]        # populated for premarket reports
    session_quotes: list[SessionResult] = []      # populated for post-close reports
    company_news: dict[str, list[NewsItem]]       # ticker → news list
    sec_filings: dict[str, list[Filing]]          # ticker → filings list
    economic_calendar: list[EconomicEvent]
    earnings_calendar: list[EarningsEvent]
    macro_snapshot: MacroSnapshot
    macro_releases: list[MacroReading] = []       # latest official BLS/BEA prints (FRED)
    etf_profiles: dict[str, ETFProfile] = {}      # ticker → ETF theme + top holdings
                                                  # (empty for non-ETF holdings)
