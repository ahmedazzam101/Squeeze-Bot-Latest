from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class TradeAction(StrEnum):
    IGNORE = "IGNORE"
    WATCH = "WATCH"
    BUY = "BUY"
    HOLD = "HOLD"
    TIGHTEN_STOP = "TIGHTEN_STOP"
    SELL = "SELL"


class ClaudeVote(StrEnum):
    IGNORE = "IGNORE"
    WATCH = "WATCH"
    BUY_CANDIDATE = "BUY_CANDIDATE"
    HOLD = "HOLD"
    HOLD_BUT_TIGHTEN_STOP = "HOLD_BUT_TIGHTEN_STOP"
    EXIT_WARNING = "EXIT_WARNING"
    EXIT_NOW_CATALYST_RISK = "EXIT_NOW_CATALYST_RISK"


@dataclass
class MarketSnapshot:
    symbol: str
    price: float
    previous_close: float = 0.0
    volume: float = 0.0
    average_volume: float = 0.0
    rvol: float = 0.0
    recent_volume_ratio: float = 0.0
    vwap: float = 0.0
    above_vwap_candles: int = 0
    premarket_high: float = 0.0
    resistance: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    intraday_change_pct: float = 0.0
    price_velocity_pct: float = 0.0
    volume_growth_pct: float = 0.0
    volatility_expansion_pct: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def spread_pct(self) -> float:
        if self.bid <= 0 or self.ask <= 0:
            return 0.0
        midpoint = (self.bid + self.ask) / 2
        return ((self.ask - self.bid) / midpoint) * 100 if midpoint else 0.0

    @property
    def breakout_confirmed(self) -> bool:
        level = max(self.premarket_high, self.resistance)
        return bool(level > 0 and self.price > level)


@dataclass
class StructuralData:
    short_interest_pct_float: float = 0.0
    float_shares: float = 0.0
    days_to_cover: float = 0.0
    borrow_fee_pct: float = 0.0
    borrow_utilization_pct: float = 0.0
    fails_to_deliver_ratio: float = 0.0
    short_sale_volume_ratio: float = 0.0


@dataclass
class CatalystData:
    news_count_24h: int = 0
    news_count_baseline: float = 0.0
    headlines: list[str] = field(default_factory=list)

    @property
    def frequency_growth_pct(self) -> float:
        if self.news_count_baseline <= 0:
            return 100.0 if self.news_count_24h else 0.0
        return ((self.news_count_24h - self.news_count_baseline) / self.news_count_baseline) * 100


@dataclass
class SocialData:
    reddit_mentions_1h: int = 0
    reddit_mentions_baseline: float = 0.0
    reddit_sentiment_shift: float = 0.0
    google_trends_change_pct: float = 0.0

    @property
    def mention_velocity_pct(self) -> float:
        if self.reddit_mentions_baseline <= 0:
            return 100.0 if self.reddit_mentions_1h else 0.0
        return ((self.reddit_mentions_1h - self.reddit_mentions_baseline) / self.reddit_mentions_baseline) * 100


@dataclass
class Scores:
    structural_pressure: float
    acceleration: float
    catalyst_strength: float
    social_pressure: float
    composite: float
    acceleration_rising: bool


@dataclass
class ClaudeAnalysis:
    vote: ClaudeVote
    confidence: float
    catalyst_quality: float
    manipulation_risk: float
    dilution_risk: float
    summary: str
    red_flags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskState:
    equity: float
    buying_power: float
    daily_pnl_pct: float
    open_positions: int
    trades_today: int
    losses_today: int


@dataclass
class Position:
    symbol: str
    quantity: float
    average_entry_price: float
    market_value: float
    unrealized_gain_pct: float


@dataclass
class PositionMeta:
    symbol: str
    entry_time: datetime
    entry_price: float
    peak_price: float
    entry_score: float = 0.0
    entry_acceleration: float = 0.0
    acceleration_decay_cycles: int = 0
    stop_price: float = 0.0
    trailing_stop_pct: float = 0.0


@dataclass
class MarketSession:
    is_open: bool
    session: str
    reason: str


@dataclass
class Opportunity:
    symbol: str
    source: str
    score: float
    move_pct: float = 0.0
    rvol: float = 0.0
    price: float = 0.0
    reason: str = ""
    discovered_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Decision:
    symbol: str
    action: TradeAction
    reason: str
    quantity: float = 0
    stop_price: float = 0.0
    limit_price: float = 0.0
    tighten_trail_pct: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
