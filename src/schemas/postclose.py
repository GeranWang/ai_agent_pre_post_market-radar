"""Post-close (收盘总结) brief schema — the backward-looking evening report.

Shares the Lone Trail chrome and several models with the pre-market `DailyBrief`
(Telemetry / EventWatch / FilteredItem / SourceQuality / Label / Confidence) but
has its own sections: it recaps what actually happened and — when the same trading
day's pre-market brief exists — grades the morning's calls (the 复盘对账 scorecard).
"""
from typing import Literal
from pydantic import BaseModel, field_validator

from src.schemas.brief import (
    Confidence,
    TelemetryReading,
    EventWatch,
    FilteredItem,
    SourceQuality,
)


class ClosePulse(BaseModel):
    """Section 00 — how the day resolved, in a 30-second read."""
    bias: str                             # "风险偏好回升 / 科技领涨" etc.
    themes: list[str]                     # 1–3 things that defined the session
    takeaway: str                         # the one line that matters for tonight
    confidence: Confidence
    caveat: str = ""

    @field_validator("themes")
    @classmethod
    def _themes(cls, v):
        if not (1 <= len(v) <= 3):
            raise ValueError(f"themes must have 1–3 items, got {len(v)}")
        return v


class ScorecardItem(BaseModel):
    """Section 01 — one morning expectation graded against the actual outcome."""
    item: str                             # what the morning flagged (命门 / watch / signal)
    morning_view: str                     # what the morning brief expected
    actual: str                           # what actually happened today
    verdict: Literal["命中", "落空", "中性", "待续"]


class Mover(BaseModel):
    """Section 03 — a notable holding move today. change_pct injected from data."""
    ticker: str
    change_pct: float | None = None
    note: str                             # why it moved (中文)


class AssetRecap(BaseModel):
    """Section 04 — per-holding day recap. close_price/change_pct injected."""
    ticker: str
    role: str
    state: Literal["Nominal", "Watch", "Alert"]
    close_price: float | None = None
    change_pct: float | None = None
    what_happened: str                    # today's actual events for this holding
    read: str                             # what it means for the holder
    watch: str                            # what carries into tomorrow (信息非建议)
    confidence: Confidence
    meta: dict[str, str] = {}


class PostCloseBrief(BaseModel):
    date: str
    report_type: str = "postclose"
    mission_designator: str = "ARC-01"
    signal_state: Literal["NOMINAL", "AMBER", "RED"]
    close_pulse: ClosePulse               # 00
    scorecard: list[ScorecardItem] = []   # 01 — empty if no morning brief to compare
    scorecard_note: str = ""              # e.g. "无当日晨报可对比"
    telemetry: list[TelemetryReading]     # 02 — close readings
    movers: list[Mover] = []              # 03
    assets: list[AssetRecap]              # 04
    after_hours: list[str] = []           # 05 — after-hours moves (statements)
    tomorrow: list[EventWatch] = []       # 05 — tomorrow's catalysts (72h)
    filtered: list[FilteredItem] = []     # 06
    source_quality: SourceQuality         # 07

    @field_validator("telemetry")
    @classmethod
    def _tel(cls, v):
        if not (3 <= len(v) <= 6):
            raise ValueError(f"telemetry must have 3–6 readings, got {len(v)}")
        return v

    @field_validator("scorecard")
    @classmethod
    def _score(cls, v):
        if len(v) > 6:
            raise ValueError(f"scorecard must have 0–6 items, got {len(v)}")
        return v

    @field_validator("movers")
    @classmethod
    def _movers(cls, v):
        if len(v) > 5:
            raise ValueError(f"movers must have 0–5 items, got {len(v)}")
        return v
