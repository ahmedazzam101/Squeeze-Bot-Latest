from squeeze_bot.config import Settings
from squeeze_bot.engines.policy import TradingPolicy
from datetime import UTC, datetime

from squeeze_bot.models import ClaudeAnalysis, ClaudeVote, MarketSnapshot, PositionMeta, RiskState, Scores, TradeAction


def test_policy_buys_when_all_gates_pass():
    policy = TradingPolicy(Settings(require_regime_filter=False))
    snapshot = MarketSnapshot(
        symbol="TEST",
        price=10,
        rvol=5,
        vwap=9,
        above_vwap_candles=2,
        premarket_high=9.5,
        resistance=9.8,
        bid=9.98,
        ask=10.02,
    )
    scores = Scores(80, 80, 80, 80, 80, True)
    analysis = ClaudeAnalysis(ClaudeVote.BUY_CANDIDATE, 0.8, 0.8, 0.2, 0.1, "good")
    risk = RiskState(10_000, 10_000, 0, 0, 0, 0)
    decision = policy.decide_entry(snapshot, scores, analysis, risk, True, "ok")
    assert decision.action == TradeAction.BUY
    assert decision.quantity > 0


def test_policy_blocks_high_dilution_risk():
    policy = TradingPolicy(Settings(require_regime_filter=False))
    snapshot = MarketSnapshot(symbol="TEST", price=10, rvol=5, vwap=9, above_vwap_candles=2, premarket_high=9.5, resistance=9.8)
    scores = Scores(80, 80, 80, 80, 80, True)
    analysis = ClaudeAnalysis(ClaudeVote.BUY_CANDIDATE, 0.8, 0.8, 0.2, 0.9, "bad")
    risk = RiskState(10_000, 10_000, 0, 0, 0, 0)
    decision = policy.decide_entry(snapshot, scores, analysis, risk, True, "ok")
    assert decision.action != TradeAction.BUY


def test_policy_allows_high_conviction_watch_vote():
    policy = TradingPolicy(Settings(require_regime_filter=False))
    snapshot = MarketSnapshot(
        symbol="TEST",
        price=10,
        rvol=2.2,
        vwap=9,
        above_vwap_candles=1,
        premarket_high=9.5,
        resistance=9.8,
        bid=9.98,
        ask=10.02,
    )
    scores = Scores(80, 78, 80, 80, 79, True)
    analysis = ClaudeAnalysis(ClaudeVote.WATCH, 0.45, 0.8, 0.2, 0.1, "watch")
    risk = RiskState(10_000, 10_000, 0, 0, 0, 0)
    decision = policy.decide_entry(snapshot, scores, analysis, risk, False, "quiet regime")
    assert decision.action == TradeAction.BUY
    assert decision.metadata["entry_path"] == "high_conviction"


def test_policy_allows_momentum_breakout_when_structural_data_is_incomplete():
    policy = TradingPolicy(Settings(require_regime_filter=False))
    snapshot = MarketSnapshot(
        symbol="MOMO",
        price=10,
        rvol=3.4,
        vwap=9.7,
        above_vwap_candles=1,
        premarket_high=9.8,
        resistance=9.9,
        bid=9.98,
        ask=10.02,
    )
    scores = Scores(50, 68, 45, 45, 56, True)
    analysis = ClaudeAnalysis(ClaudeVote.WATCH, 0.45, 0.2, 0.2, 0.1, "fallback watch")
    risk = RiskState(10_000, 10_000, 0, 0, 0, 0)
    decision = policy.decide_entry(snapshot, scores, analysis, risk, True, "ok")
    assert decision.action == TradeAction.BUY
    assert decision.metadata["entry_path"] == "momentum_breakout"


def test_policy_allows_half_size_early_probe_near_breakout():
    policy = TradingPolicy(Settings())
    snapshot = MarketSnapshot(
        symbol="PROBE",
        price=9.85,
        rvol=4.0,
        vwap=9.7,
        above_vwap_candles=1,
        premarket_high=10.0,
        resistance=9.9,
        bid=9.83,
        ask=9.87,
    )
    scores = Scores(45, 58, 45, 40, 50, True)
    analysis = ClaudeAnalysis(ClaudeVote.WATCH, 0.45, 0.2, 0.2, 0.1, "early pressure")
    risk = RiskState(10_000, 10_000, 0, 0, 0, 0)
    decision = policy.decide_entry(snapshot, scores, analysis, risk, False, "quiet broad market")
    assert decision.action == TradeAction.BUY
    assert decision.metadata["entry_path"] == "early_squeeze_probe"
    assert decision.metadata["stock_specific_regime_bypass"] is True
    assert decision.quantity < 100


def test_policy_blocks_early_probe_when_too_far_from_breakout():
    policy = TradingPolicy(Settings(require_regime_filter=False))
    snapshot = MarketSnapshot(
        symbol="FAR",
        price=9.50,
        rvol=4.0,
        vwap=9.3,
        above_vwap_candles=1,
        premarket_high=10.0,
        resistance=9.9,
        bid=9.48,
        ask=9.52,
    )
    scores = Scores(45, 58, 45, 40, 50, True)
    analysis = ClaudeAnalysis(ClaudeVote.WATCH, 0.45, 0.2, 0.2, 0.1, "early pressure")
    risk = RiskState(10_000, 10_000, 0, 0, 0, 0)
    decision = policy.decide_entry(snapshot, scores, analysis, risk, True, "ok")
    assert decision.action != TradeAction.BUY


def test_policy_records_block_reasons():
    policy = TradingPolicy(Settings(require_regime_filter=False))
    snapshot = MarketSnapshot(symbol="TEST", price=10, rvol=1, vwap=11, above_vwap_candles=0)
    scores = Scores(40, 40, 40, 40, 40, False)
    analysis = ClaudeAnalysis(ClaudeVote.IGNORE, 0.2, 0.1, 0.2, 0.1, "ignore")
    risk = RiskState(10_000, 10_000, 0, 0, 0, 0)
    decision = policy.decide_entry(snapshot, scores, analysis, risk, True, "ok")
    assert decision.action != TradeAction.BUY
    assert decision.metadata["block_reasons"]


def test_policy_sells_on_repeated_acceleration_decay():
    policy = TradingPolicy(Settings(require_regime_filter=False))
    snapshot = MarketSnapshot(symbol="TEST", price=12, vwap=10)
    scores = Scores(80, 50, 80, 80, 75, False)
    analysis = ClaudeAnalysis(ClaudeVote.HOLD, 0.8, 0.8, 0.2, 0.1, "hold")
    meta = PositionMeta("TEST", datetime.now(UTC), 10, 13, acceleration_decay_cycles=2, stop_price=9.3)
    decision = policy.decide_exit(snapshot, scores, analysis, unrealized_gain_pct=20, meta=meta)
    assert decision.action == TradeAction.SELL


def test_policy_allows_swap_exit_for_weak_position_and_stronger_candidate():
    policy = TradingPolicy(Settings())
    decision = policy.decide_swap_exit(
        "WEAK",
        Scores(50, 45, 50, 50, 55, False),
        current_unrealized_gain_pct=-1,
        candidate_symbol="STRONG",
        candidate_scores=Scores(85, 85, 80, 80, 82, True),
    )
    assert decision.action == TradeAction.SELL
