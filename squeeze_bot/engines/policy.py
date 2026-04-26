from __future__ import annotations

from squeeze_bot.config import Settings
from squeeze_bot.engines.risk import RiskGovernor
from squeeze_bot.models import ClaudeAnalysis, ClaudeVote, Decision, MarketSnapshot, PositionMeta, RiskState, Scores, TradeAction


class TradingPolicy:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.risk = RiskGovernor(settings)

    def decide_entry(self, snapshot: MarketSnapshot, scores: Scores, analysis: ClaudeAnalysis, risk_state: RiskState, regime_passed: bool, regime_reason: str) -> Decision:
        claude_allows = analysis.vote == ClaudeVote.BUY_CANDIDATE or (
            self.settings.allow_claude_watch_on_strong_quant
            and analysis.vote == ClaudeVote.WATCH
            and scores.composite >= self.settings.high_conviction_score
            and scores.acceleration >= self.settings.high_conviction_acceleration
        )
        regime_allows = regime_passed or not self.settings.require_regime_filter or (
            self.settings.allow_high_conviction_regime_bypass
            and scores.composite >= self.settings.high_conviction_score
            and scores.acceleration >= self.settings.high_conviction_acceleration
            and snapshot.rvol >= self.settings.min_rvol
        )
        risk_flags_clear = analysis.dilution_risk < 0.65 and analysis.vote != ClaudeVote.EXIT_NOW_CATALYST_RISK

        strict_path = all(
            [
                scores.composite >= self.settings.min_composite_score,
                scores.acceleration_rising,
                snapshot.breakout_confirmed,
                snapshot.rvol >= self.settings.min_rvol,
                snapshot.above_vwap_candles >= self.settings.min_above_vwap_candles,
                claude_allows,
                analysis.confidence >= 0.50,
                risk_flags_clear,
                regime_allows,
            ]
        )
        high_conviction_path = all(
            [
                scores.composite >= self.settings.high_conviction_score,
                scores.acceleration >= self.settings.high_conviction_acceleration,
                scores.acceleration_rising,
                snapshot.breakout_confirmed,
                snapshot.rvol >= self.settings.high_conviction_rvol,
                snapshot.above_vwap_candles >= self.settings.high_conviction_above_vwap_candles,
                risk_flags_clear,
                regime_allows,
            ]
        )
        if not (strict_path or high_conviction_path):
            reasons = self._entry_block_reasons(snapshot, scores, analysis, regime_allows, regime_reason, claude_allows, risk_flags_clear)
            return Decision(
                snapshot.symbol,
                TradeAction.WATCH if scores.composite >= 55 else TradeAction.IGNORE,
                "; ".join(reasons[:3]),
                metadata={"block_reasons": reasons},
            )

        allowed, risk_reason = self.risk.can_enter(risk_state, snapshot)
        if not allowed:
            return Decision(snapshot.symbol, TradeAction.WATCH, risk_reason)
        quantity, stop_price = self.risk.position_size(risk_state, snapshot)
        if quantity <= 0:
            return Decision(snapshot.symbol, TradeAction.WATCH, "position size resolved to zero")
        return Decision(
            symbol=snapshot.symbol,
            action=TradeAction.BUY,
            reason="all entry gates passed",
            quantity=quantity,
            stop_price=stop_price,
            limit_price=snapshot.ask or snapshot.price,
            metadata={
                "entry_score": scores.composite,
                "entry_acceleration": scores.acceleration,
                "trailing_stop_pct": self.settings.trail_pct,
                "entry_path": "strict" if strict_path else "high_conviction",
            },
        )

    def _entry_block_reasons(
        self,
        snapshot: MarketSnapshot,
        scores: Scores,
        analysis: ClaudeAnalysis,
        regime_allows: bool,
        regime_reason: str,
        claude_allows: bool,
        risk_flags_clear: bool,
    ) -> list[str]:
        reasons: list[str] = []
        if scores.composite < self.settings.min_composite_score:
            reasons.append(f"composite {scores.composite:.1f} below {self.settings.min_composite_score}")
        if not scores.acceleration_rising:
            reasons.append("acceleration not rising")
        if not snapshot.breakout_confirmed:
            reasons.append("breakout not confirmed")
        if snapshot.rvol < self.settings.high_conviction_rvol:
            reasons.append(f"RVOL {snapshot.rvol:.2f} below {self.settings.high_conviction_rvol}")
        if snapshot.above_vwap_candles < self.settings.high_conviction_above_vwap_candles:
            reasons.append("not above VWAP")
        if not claude_allows:
            reasons.append(f"Claude vote is {analysis.vote}")
        if analysis.confidence < 0.50 and scores.composite < self.settings.high_conviction_score:
            reasons.append(f"Claude confidence {analysis.confidence:.2f} too low")
        if not risk_flags_clear:
            reasons.append(f"risk flags not clear; dilution={analysis.dilution_risk:.2f}")
        if not regime_allows:
            reasons.append(regime_reason)
        return reasons or ["entry gates not met"]

    def decide_exit(self, snapshot: MarketSnapshot, scores: Scores, analysis: ClaudeAnalysis, unrealized_gain_pct: float, meta: PositionMeta | None = None) -> Decision:
        if analysis.vote == ClaudeVote.EXIT_NOW_CATALYST_RISK:
            return Decision(snapshot.symbol, TradeAction.SELL, "Claude flagged immediate catalyst risk")
        if meta is not None:
            hard_stop = meta.stop_price or meta.entry_price * (1 - self.settings.hard_stop_pct / 100)
            if snapshot.price <= hard_stop:
                return Decision(snapshot.symbol, TradeAction.SELL, f"hard stop hit at {snapshot.price:.2f}")
            if unrealized_gain_pct >= self.settings.trail_activate_pct:
                trail_pct = self.settings.tight_trail_pct if unrealized_gain_pct >= 20 else self.settings.trail_pct
                trail_floor = meta.peak_price * (1 - trail_pct / 100)
                if snapshot.price <= trail_floor:
                    return Decision(snapshot.symbol, TradeAction.SELL, f"trailing stop hit: peak {meta.peak_price:.2f}, floor {trail_floor:.2f}")
            if meta.acceleration_decay_cycles >= 2:
                return Decision(snapshot.symbol, TradeAction.SELL, f"acceleration decayed for {meta.acceleration_decay_cycles} cycles")
        if snapshot.price < snapshot.vwap:
            return Decision(snapshot.symbol, TradeAction.SELL, "VWAP breakdown")
        if not scores.acceleration_rising and analysis.vote == ClaudeVote.EXIT_WARNING:
            return Decision(snapshot.symbol, TradeAction.SELL, "acceleration decay confirmed with exit warning")
        if unrealized_gain_pct >= 10 and analysis.vote == ClaudeVote.HOLD_BUT_TIGHTEN_STOP:
            return Decision(snapshot.symbol, TradeAction.TIGHTEN_STOP, "tighten trailing stop", tighten_trail_pct=7.0)
        return Decision(snapshot.symbol, TradeAction.HOLD, "trend intact")

    def decide_swap_exit(
        self,
        current_symbol: str,
        current_scores: Scores,
        current_unrealized_gain_pct: float,
        candidate_symbol: str,
        candidate_scores: Scores,
    ) -> Decision:
        if not self.settings.enable_swaps:
            return Decision(current_symbol, TradeAction.HOLD, "swaps disabled")
        if candidate_scores.composite < self.settings.swap_min_score:
            return Decision(current_symbol, TradeAction.HOLD, "swap candidate score below minimum")
        if candidate_scores.composite - current_scores.composite < self.settings.swap_score_advantage:
            return Decision(current_symbol, TradeAction.HOLD, "swap advantage too small")
        weak_position = (
            current_scores.composite <= self.settings.swap_max_current_score
            or not current_scores.acceleration_rising
        )
        if not weak_position:
            return Decision(current_symbol, TradeAction.HOLD, "held position not weak enough to swap")
        if current_unrealized_gain_pct > self.settings.swap_max_current_pnl_pct:
            return Decision(current_symbol, TradeAction.HOLD, "held position profit protected")
        return Decision(
            current_symbol,
            TradeAction.SELL,
            (
                f"swap exit: {candidate_symbol} score {candidate_scores.composite:.1f} "
                f"beats held score {current_scores.composite:.1f}"
            ),
            metadata={
                "swap_candidate": candidate_symbol,
                "candidate_score": candidate_scores.composite,
                "held_score": current_scores.composite,
            },
        )
