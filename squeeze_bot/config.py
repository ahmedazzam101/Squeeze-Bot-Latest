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
    enable_claude_analysis: bool = _bool("ENABLE_CLAUDE_ANALYSIS", True)
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
    claude_min_composite_score: float = _float("CLAUDE_MIN_COMPOSITE_SCORE", 68.0)
    claude_min_acceleration_score: float = _float("CLAUDE_MIN_ACCELERATION_SCORE", 65.0)
    claude_min_rvol: float = _float("CLAUDE_MIN_RVOL", 2.5)
    claude_cache_minutes: int = _int("CLAUDE_CACHE_MINUTES", 20)
    claude_position_cache_minutes: int = _int("CLAUDE_POSITION_CACHE_MINUTES", 3)
    claude_daily_budget_usd: float = _float("CLAUDE_DAILY_BUDGET_USD", 0.45)
    claude_max_calls_per_day: int = _int("CLAUDE_MAX_CALLS_PER_DAY", 10)
    claude_estimated_cost_per_call_usd: float = _float("CLAUDE_ESTIMATED_COST_PER_CALL_USD", 0.02)
    claude_call_finalists: bool = _bool("CLAUDE_CALL_FINALISTS", True)
    claude_finalist_min_composite_score: float = _float("CLAUDE_FINALIST_MIN_COMPOSITE_SCORE", 35.0)
    claude_finalist_min_acceleration_score: float = _float("CLAUDE_FINALIST_MIN_ACCELERATION_SCORE", 55.0)
    claude_finalist_min_rvol: float = _float("CLAUDE_FINALIST_MIN_RVOL", 3.0)
    fmp_api_key: str = os.getenv("FMP_API_KEY", "")
    finnhub_api_key: str = os.getenv("FINNHUB_API_KEY", "")
    reddit_client_id: str = os.getenv("REDDIT_CLIENT_ID", "")
    reddit_client_secret: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    reddit_user_agent: str = os.getenv("REDDIT_USER_AGENT", "short-squeeze-bot/0.1")
    enrichment_cache_minutes: int = _int("ENRICHMENT_CACHE_MINUTES", 15)
    reddit_cache_minutes: int = _int("REDDIT_CACHE_MINUTES", 10)
    enable_google_trends: bool = _bool("ENABLE_GOOGLE_TRENDS", False)
    google_trends_refresh_minutes: int = _int("GOOGLE_TRENDS_REFRESH_MINUTES", 15)
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///squeeze_bot.db")
    watchlist: tuple[str, ...] = tuple(
        symbol.strip().upper()
        for symbol in os.getenv("WATCHLIST", "").split(",")
        if symbol.strip()
    )
    scan_interval_seconds: int = _int("SCAN_INTERVAL_SECONDS", 60)
    log_api_health: bool = _bool("LOG_API_HEALTH", True)
    log_scan_summary: bool = _bool("LOG_SCAN_SUMMARY", True)
    log_top_candidates: int = _int("LOG_TOP_CANDIDATES", 5)
    market_snapshot_cache_seconds: int = _int("MARKET_SNAPSHOT_CACHE_SECONDS", 45)
    positions_cache_seconds: int = _int("POSITIONS_CACHE_SECONDS", 20)
    enable_market_hours_throttle: bool = _bool("ENABLE_MARKET_HOURS_THROTTLE", True)
    closed_market_scan_interval_seconds: int = _int("CLOSED_MARKET_SCAN_INTERVAL_SECONDS", 900)
    premarket_scan_interval_seconds: int = _int("PREMARKET_SCAN_INTERVAL_SECONDS", 300)
    enable_closed_market_discovery: bool = _bool("ENABLE_CLOSED_MARKET_DISCOVERY", False)
    enable_market_discovery: bool = _bool("ENABLE_MARKET_DISCOVERY", True)
    discovery_interval_seconds: int = _int("DISCOVERY_INTERVAL_SECONDS", 600)
    discovery_max_symbols: int = _int("DISCOVERY_MAX_SYMBOLS", 10)
    discovery_source_limit: int = _int("DISCOVERY_SOURCE_LIMIT", 25)
    opportunity_ttl_minutes: int = _int("OPPORTUNITY_TTL_MINUTES", 45)
    opportunity_scan_limit: int = _int("OPPORTUNITY_SCAN_LIMIT", 6)
    discovery_min_price: float = _float("DISCOVERY_MIN_PRICE", 1.0)
    discovery_min_move_pct: float = _float("DISCOVERY_MIN_MOVE_PCT", 1.5)
    discovery_min_rvol: float = _float("DISCOVERY_MIN_RVOL", 1.1)
    discovery_common_stocks_only: bool = _bool("DISCOVERY_COMMON_STOCKS_ONLY", True)
    discovery_keep_relaxed_candidates: bool = _bool("DISCOVERY_KEEP_RELAXED_CANDIDATES", True)
    discovery_relaxed_score_floor: float = _float("DISCOVERY_RELAXED_SCORE_FLOOR", 10.0)
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
    enable_momentum_breakout_entry: bool = _bool("ENABLE_MOMENTUM_BREAKOUT_ENTRY", True)
    momentum_min_composite_score: float = _float("MOMENTUM_MIN_COMPOSITE_SCORE", 55.0)
    momentum_min_acceleration_score: float = _float("MOMENTUM_MIN_ACCELERATION_SCORE", 60.0)
    momentum_min_rvol: float = _float("MOMENTUM_MIN_RVOL", 3.0)
    enable_early_squeeze_probe: bool = _bool("ENABLE_EARLY_SQUEEZE_PROBE", True)
    early_probe_min_composite_score: float = _float("EARLY_PROBE_MIN_COMPOSITE_SCORE", 40.0)
    early_probe_min_acceleration_score: float = _float("EARLY_PROBE_MIN_ACCELERATION_SCORE", 55.0)
    early_probe_min_rvol: float = _float("EARLY_PROBE_MIN_RVOL", 3.0)
    early_probe_strong_acceleration_score: float = _float("EARLY_PROBE_STRONG_ACCELERATION_SCORE", 60.0)
    early_probe_strong_rvol: float = _float("EARLY_PROBE_STRONG_RVOL", 10.0)
    early_probe_breakout_distance_pct: float = _float("EARLY_PROBE_BREAKOUT_DISTANCE_PCT", 2.0)
    early_probe_risk_multiplier: float = _float("EARLY_PROBE_RISK_MULTIPLIER", 0.50)
    enable_paper_probe_entry: bool = _bool("ENABLE_PAPER_PROBE_ENTRY", True)
    paper_probe_min_composite_score: float = _float("PAPER_PROBE_MIN_COMPOSITE_SCORE", 40.0)
    paper_probe_min_acceleration_score: float = _float("PAPER_PROBE_MIN_ACCELERATION_SCORE", 10.0)
    paper_probe_min_rvol: float = _float("PAPER_PROBE_MIN_RVOL", 2.0)
    paper_probe_risk_multiplier: float = _float("PAPER_PROBE_RISK_MULTIPLIER", 0.25)
    allow_stock_specific_regime_bypass: bool = _bool("ALLOW_STOCK_SPECIFIC_REGIME_BYPASS", True)
    allow_claude_watch_on_strong_quant: bool = _bool("ALLOW_CLAUDE_WATCH_ON_STRONG_QUANT", True)
    allow_high_conviction_regime_bypass: bool = _bool("ALLOW_HIGH_CONVICTION_REGIME_BYPASS", True)
    max_spread_pct: float = _float("MAX_SPREAD_PCT", 0.75)
    require_regime_filter: bool = _bool("REQUIRE_REGIME_FILTER", True)
    fail_open_on_regime_unavailable: bool = _bool("FAIL_OPEN_ON_REGIME_UNAVAILABLE", True)
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
