from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:
    pass


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value in (None, "") else float(value)


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value in (None, "") else int(value)


@dataclass(frozen=True)
class Settings:
    dry_run: bool = _bool("DRY_RUN", True)
    enable_alpaca_execution: bool = _bool("ENABLE_ALPACA_EXECUTION", False)
    alpaca_paper: bool = _bool("ALPACA_PAPER", True)
    alpaca_api_key: str = os.getenv("ALPACA_API_KEY", "")
    alpaca_secret_key: str = os.getenv("ALPACA_SECRET_KEY", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    fmp_api_key: str = os.getenv("FMP_API_KEY", "")
    finnhub_api_key: str = os.getenv("FINNHUB_API_KEY", "")
    reddit_client_id: str = os.getenv("REDDIT_CLIENT_ID", "")
    reddit_client_secret: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    reddit_user_agent: str = os.getenv("REDDIT_USER_AGENT", "short-squeeze-bot/0.1")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///squeeze_bot.db")
    watchlist: tuple[str, ...] = tuple(
        symbol.strip().upper()
        for symbol in os.getenv("WATCHLIST", "GME,AMC,CVNA,BYND").split(",")
        if symbol.strip()
    )
    scan_interval_seconds: int = _int("SCAN_INTERVAL_SECONDS", 60)
    enable_market_discovery: bool = _bool("ENABLE_MARKET_DISCOVERY", True)
    discovery_interval_seconds: int = _int("DISCOVERY_INTERVAL_SECONDS", 300)
    discovery_max_symbols: int = _int("DISCOVERY_MAX_SYMBOLS", 20)
    opportunity_ttl_minutes: int = _int("OPPORTUNITY_TTL_MINUTES", 45)
    opportunity_scan_limit: int = _int("OPPORTUNITY_SCAN_LIMIT", 10)
    discovery_min_price: float = _float("DISCOVERY_MIN_PRICE", 1.0)
    discovery_min_move_pct: float = _float("DISCOVERY_MIN_MOVE_PCT", 4.0)
    discovery_min_rvol: float = _float("DISCOVERY_MIN_RVOL", 1.5)
    enable_swaps: bool = _bool("ENABLE_SWAPS", True)
    swap_min_score: float = _float("SWAP_MIN_SCORE", 76.0)
    swap_score_advantage: float = _float("SWAP_SCORE_ADVANTAGE", 12.0)
    swap_max_current_score: float = _float("SWAP_MAX_CURRENT_SCORE", 62.0)
    swap_max_current_pnl_pct: float = _float("SWAP_MAX_CURRENT_PNL_PCT", 2.0)
    risk_per_trade_pct: float = _float("RISK_PER_TRADE_PCT", 1.0)
    daily_loss_cap_pct: float = _float("DAILY_LOSS_CAP_PCT", 3.0)
    max_open_positions: int = _int("MAX_OPEN_POSITIONS", 2)
    max_trades_per_day: int = _int("MAX_TRADES_PER_DAY", 2)
    stop_after_losses: int = _int("STOP_AFTER_LOSSES", 2)
    min_composite_score: float = _float("MIN_COMPOSITE_SCORE", 70.0)
    min_rvol: float = _float("MIN_RVOL", 2.5)
    min_above_vwap_candles: int = _int("MIN_ABOVE_VWAP_CANDLES", 2)
    high_conviction_score: float = _float("HIGH_CONVICTION_SCORE", 78.0)
    high_conviction_acceleration: float = _float("HIGH_CONVICTION_ACCELERATION", 75.0)
    high_conviction_rvol: float = _float("HIGH_CONVICTION_RVOL", 2.0)
    high_conviction_above_vwap_candles: int = _int("HIGH_CONVICTION_ABOVE_VWAP_CANDLES", 1)
    allow_claude_watch_on_strong_quant: bool = _bool("ALLOW_CLAUDE_WATCH_ON_STRONG_QUANT", True)
    allow_high_conviction_regime_bypass: bool = _bool("ALLOW_HIGH_CONVICTION_REGIME_BYPASS", True)
    max_spread_pct: float = _float("MAX_SPREAD_PCT", 0.75)
    require_regime_filter: bool = _bool("REQUIRE_REGIME_FILTER", True)
    stale_order_ttl_minutes: int = _int("STALE_ORDER_TTL_MINUTES", 10)
    hard_stop_pct: float = _float("HARD_STOP_PCT", 7.0)
    trail_activate_pct: float = _float("TRAIL_ACTIVATE_PCT", 12.0)
    trail_pct: float = _float("TRAIL_PCT", 10.0)
    tight_trail_pct: float = _float("TIGHT_TRAIL_PCT", 7.0)

    @property
    def sqlite_path(self) -> Path | None:
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            return Path(self.database_url.removeprefix(prefix))
        return None


settings = Settings()
