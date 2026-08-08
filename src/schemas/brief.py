from typing import Literal
from pydantic import BaseModel, field_validator

Confidence = Literal["Low", "Medium", "High"]


class MarketPulse(BaseModel):
    """Section 00 — the 30-second read. ≤80 words across all fields combined."""
    bias: str                             # "Mixed / Event-driven", "Risk-off", "Constructive"
    themes: list[str]                     # 1–3 short theme lines, ranked
    key_question: str                     # the one unresolved question the open will answer
    confidence: Confidence
    caveat: str = ""                      # low-confidence/data-quality note; "" → omit row

    @field_validator("themes")
    @classmethod
    def check_themes(cls, v):
        if not (1 <= len(v) <= 3):
            raise ValueError(f"themes must have 1–3 items, got {len(v)}")
        return v


class Interaction(BaseModel):
    """One cross-holding dynamic. Must name ≥2 holdings and give the mechanism —
    the whole point is interaction, not a single-ticker note."""
    kind: Literal["Shared driver", "Hedge failure", "Concentration", "Divergence"]
    holdings: list[str]                   # ≥2 tickers / exposure groups involved
    note: str                             # the mechanism / read, 中文

    @field_validator("holdings")
    @classmethod
    def at_least_two(cls, v):
        if len(v) < 2:
            raise ValueError(f"an interaction must involve ≥2 holdings, got {len(v)}")
        return v


class PortfolioRead(BaseModel):
    """Section 01 — the cross-holding synthesis. The product's main value-add:
    treat the holdings as one book, not a list of tickers."""
    posture: str                          # net exposure of the book today, one line
    interactions: list[Interaction]       # 2–3 paired cross-holding dynamics
    ripple: str = ""                      # optional 2nd-order chain crossing ≥2 holdings
    swing: str                            # the one variable that decides the book (命门)
    watch: list[str] = []                 # ≤5 portfolio-level watch statements (absorbs
                                          # the old watch_after_open); statements, not advice

    @field_validator("interactions")
    @classmethod
    def check_interactions(cls, v):
        if not (1 <= len(v) <= 4):
            raise ValueError(f"interactions must have 1–4 items, got {len(v)}")
        return v

    @field_validator("watch")
    @classmethod
    def check_watch(cls, v):
        if len(v) > 5:
            raise ValueError(f"portfolio watch must have 0–5 items, got {len(v)}")
        return v


class TelemetryReading(BaseModel):
    key: str                              # "DGS2" / "DGS10" / "DXY" / "VIX"
    value: str                            # "4.82" — string to preserve decimal display
    unit: str                             # "%" or ""
    delta: str                            # "+3bp · breakout"
    flag: bool                            # True → amber highlight; max 2 should be True
    note: str = ""                        # one-line 中文 reading for flagged rows; "" → bare number


class Label(BaseModel):
    """Compact quality tag, rendered as "Official · New · High impact"."""
    freshness: Literal["LIVE", "NEW", "RECENT", "STALE"]
    source: Literal["Official", "Tier-1", "Secondary", "Low-confidence", "Inference"]
    impact: Literal["High", "Medium", "Low", "Background"]


class TopSignal(BaseModel):
    """Section 02 — max 5, ranked. Must pass the relevance gate."""
    rank: int                             # 1-based importance rank
    signal: str                           # the signal itself, one line
    affected: list[str]                   # tickers / exposure groups
    why: str                              # why it matters, ≤1 sentence
    label: Label
    confidence: Confidence


class AssetImpact(BaseModel):
    """Section 03 — one per holding or exposure group. ≤4 content lines."""
    ticker: str                           # ticker OR exposure-group name ("Semiconductors")
    role: str                             # "Core" / "Thematic · AI" / "Hedge" etc.
    state: Literal["Nominal", "Watch", "Alert"]
    price: float | None = None            # injected from raw pre-market data; None = unavailable
    change_pct: float | None = None       # injected from raw pre-market data; None = unavailable
    news: str                             # what happened (or "No direct overnight news…")
    impact: str                           # what it means for the holder — mixed-setup framing
    watch: str                            # what to watch after open to confirm direction
    confidence: Confidence
    meta: dict[str, str] = {}             # optional {"VOL": "1.2M PM", "FILINGS": "0"}


class EventWatch(BaseModel):
    """Section 05 — max 5 events. Replaces the old Catalyst model."""
    time: str                             # "06.12 · 10:00" (ET)
    event: str                            # event description
    affected: str                         # affected ticker / group / "MACRO"
    why: str                              # why it matters, short
    priority: Literal["LOW", "MED", "HIGH"]


class FilteredItem(BaseModel):
    headline: str
    reason: str                           # one clause: why deprioritized


class SourceQuality(BaseModel):
    """Section 07 — rendered as one line of counts + report confidence."""
    official: int = 0
    tier1: int = 0
    secondary: int = 0
    inference: int = 0
    report_confidence: Confidence = "Medium"
    limitation: str = ""                  # optional one-line caveat; "" → omit


class DailyBrief(BaseModel):
    date: str                             # "2026-06-12"
    report_type: str = "premarket"        # injected by pipeline (premarket|postclose)
    mission_designator: str = "ARC-01"   # "ARC-09" — injected by pipeline; defaults to ARC-01
    signal_state: Literal["NOMINAL", "AMBER", "RED"]
    market_pulse: MarketPulse             # Section 00
    portfolio_read: PortfolioRead         # Section 01 — cross-holding synthesis
    telemetry: list[TelemetryReading]     # Section 02, 3–6 readings
    top_signals: list[TopSignal]          # Section 03, 0–5 items
    assets: list[AssetImpact]             # Section 04, collapsed cards in render
    events: list[EventWatch] = []         # Section 05, 0–5 items
    filtered: list[FilteredItem] = []     # Section 06, collapsed in render
    source_quality: SourceQuality         # Section 07

    @field_validator("telemetry")
    @classmethod
    def check_telemetry(cls, v):
        if not (3 <= len(v) <= 6):
            raise ValueError(f"telemetry must have 3–6 readings, got {len(v)}")
        return v

    @field_validator("top_signals")
    @classmethod
    def check_top_signals(cls, v):
        if len(v) > 5:
            raise ValueError(f"top_signals must have 0–5 items, got {len(v)}")
        return v

    @field_validator("events")
    @classmethod
    def check_events(cls, v):
        if len(v) > 5:
            raise ValueError(f"events must have 0–5 items, got {len(v)}")
        return v
