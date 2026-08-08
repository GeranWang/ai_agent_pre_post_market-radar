from typing import Literal
from pydantic import BaseModel, Field


class PerAssetSummary(BaseModel):
    ticker: str
    role: str = ""                        # from holdings.yaml — pipeline-injected before render
    state: Literal["Nominal", "Watch", "Alert"] = "Nominal"  # LLM-assessed; default for old JSON
    price: float = 0.0                    # pre-market price — pipeline-injected
    change_pct: float = 0.0              # pre-market change % — pipeline-injected
    meta: dict[str, str] = Field(default_factory=dict)  # VOL / FILINGS / NEWS — pipeline-injected
    has_material_news: bool
    sentiment: Literal["bullish", "bearish", "neutral", "mixed"]
    key_events: list[str]                 # 1–4 concrete facts; empty if has_material_news=False
    portfolio_relevance: str              # why this matters for this specific holding + role
    second_order_tickers: list[str]       # other holdings affected by this ticker's news
    skip_reason: str                      # populated only when has_material_news=False
    # Label grounding — judged from the input headlines (source + published_at).
    freshness: Literal["NEW", "RECENT", "STALE", "NONE"] = "NONE"          # newest material item
    source_quality: Literal["Official", "Tier-1", "Secondary", "Low-confidence", "None"] = "None"
