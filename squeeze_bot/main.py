from __future__ import annotations

import argparse
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime

from squeeze_bot.config import settings
from squeeze_bot.data.discovery import MarketDiscoveryClient
from squeeze_bot.data.enrichment import EnrichmentClient
from squeeze_bot.data.market import AlpacaMarketClient
from squeeze_bot.engines.claude import ClaudeAnalyzer
from squeeze_bot.engines.execution import AlpacaExecutor
from squeeze_bot.engines.policy import TradingPolicy
from squeeze_bot.engines.regime import RegimeFilter
from squeeze_bot.engines.scoring import build_scores
from squeeze_bot.models import PositionMeta
from squeeze_bot.storage import Storage


def log(message: str) -> None:
    print(message, flush=True)


class Bot:
    def __init__(self) -> None:
        self.storage = Storage(settings)
        self.storage.create_all()
        self.market = AlpacaMarketClient(settings)
        self.discovery = MarketDiscoveryClient(settings, self.market)
        self.enrichment = EnrichmentClient(settings)
        self.claude = ClaudeAnalyzer(settings)
        self.regime = RegimeFilter()
        self.policy = TradingPolicy(settings)
        self.executor = AlpacaExecutor(settings, self.storage)
        self.previous_acceleration: dict[str, float] = {}
        self.claude_cache: dict[str, tuple[float, object]] = {}
        self.last_discovery_at = 0.0

    def scan_once(self) -> None:
        self.executor.reconcile_pending_orders()
        self.storage.set_state("heartbeat", {"at": time.time(), "watchlist": list(settings.watchlist)})
        self._run_discovery_if_due()
        regime_passed, regime_reason = self.regime.passes()
        risk_state = self.market.account_risk_state()
        trades_today, losses_today = self.storage.trade_counts_today()
        risk_state.trades_today = trades_today
        risk_state.losses_today = losses_today
        positions = self.market.positions()
        opportunities = self.storage.active_opportunities(settings.opportunity_ttl_minutes, settings.opportunity_scan_limit)
        opportunity_symbols = [op.symbol for op in opportunities]
        opportunity_sources = {op.symbol: op.source for op in opportunities}
        symbols = list(dict.fromkeys([*settings.watchlist, *opportunity_symbols, *positions.keys()]))
        scored_entries: dict[str, tuple] = {}
        scored_positions: dict[str, tuple] = {}
        for symbol in symbols:
            snapshot = self.market.snapshot(symbol)
            if snapshot is None:
                detail = f": {self.market.last_error}" if self.market.last_error else ""
                log(f"{symbol}: skipped, no market snapshot available{detail}")
                continue
            self.storage.update_candidate_returns(symbol, snapshot.price)

            structural = self.enrichment.structural_data(symbol)
            catalyst = self.enrichment.catalyst_data(symbol)
            social = self.enrichment.social_data(symbol)
            preliminary = build_scores(snapshot, structural, catalyst, social, previous_acceleration=self.previous_acceleration.get(symbol))
            in_position = symbol in positions
            analysis = self._analyze_with_claude_budget(symbol, snapshot, structural, catalyst, social, preliminary, in_position)
            scores = build_scores(
                snapshot,
                structural,
                catalyst,
                social,
                claude_catalyst_quality=analysis.catalyst_quality,
                previous_acceleration=self.previous_acceleration.get(symbol),
            )
            self.previous_acceleration[symbol] = scores.acceleration
            if symbol in positions:
                position = positions[symbol]
                meta = self.storage.update_position_meta_for_scan(symbol, snapshot.price, scores.acceleration_rising)
                if meta is None:
                    meta = PositionMeta(
                        symbol=symbol,
                        entry_time=datetime.now(UTC),
                        entry_price=position.average_entry_price or snapshot.price,
                        peak_price=max(snapshot.price, position.average_entry_price or snapshot.price),
                        stop_price=(position.average_entry_price or snapshot.price) * (1 - settings.hard_stop_pct / 100),
                    )
                    self.storage.upsert_position_meta(meta)
                decision = self.policy.decide_exit(snapshot, scores, analysis, position.unrealized_gain_pct, meta)
                decision.quantity = position.quantity
                scored_positions[symbol] = (scores, position, snapshot)
                if decision.action.value == "TIGHTEN_STOP" and decision.tighten_trail_pct:
                    self.storage.update_trailing_stop(symbol, decision.tighten_trail_pct)
            else:
                decision = self.policy.decide_entry(snapshot, scores, analysis, risk_state, regime_passed, regime_reason)
                if symbol in opportunity_symbols:
                    scored_entries[symbol] = (scores, analysis, decision, snapshot, regime_passed, regime_reason)
            payload = {
                "snapshot": asdict(snapshot),
                "structural": asdict(structural),
                "catalyst": asdict(catalyst),
                "social": asdict(social),
                "scores": asdict(scores),
                "claude": asdict(analysis),
                "risk_state": asdict(risk_state),
                "position": asdict(positions[symbol]) if symbol in positions else None,
                "position_meta": asdict(meta) if symbol in positions and meta is not None else None,
                "regime": {"passed": regime_passed, "reason": regime_reason},
                "decision": asdict(decision),
            }
            self.storage.log_scan(symbol, snapshot.price, scores, decision, payload)
            if symbol in opportunity_symbols:
                self.storage.record_candidate_observation(symbol, opportunity_sources.get(symbol, "opportunity"), snapshot.price, scores, decision, payload)
            executed = self.executor.execute(decision, snapshot.price)
            if executed and decision.action.value == "BUY":
                risk_state.open_positions += 1
                risk_state.trades_today += 1
            elif executed and decision.action.value == "SELL":
                risk_state.open_positions = max(0, risk_state.open_positions - 1)
            log(f"{symbol}: {decision.action} | score={scores.composite:.1f} accel={scores.acceleration:.1f} | {decision.reason}")

        self._maybe_swap(scored_positions, scored_entries, risk_state)

    def _analyze_with_claude_budget(self, symbol, snapshot, structural, catalyst, social, preliminary, in_position: bool):
        cached = self.claude_cache.get(symbol)
        cache_minutes = settings.claude_position_cache_minutes if in_position else settings.claude_cache_minutes
        if cached and time.time() - cached[0] < max(1, cache_minutes) * 60:
            return cached[1]

        should_call = (
            settings.enable_claude_analysis
            and bool(settings.anthropic_api_key)
            and (
                in_position
                or preliminary.composite >= settings.claude_min_composite_score
                or preliminary.acceleration >= settings.claude_min_acceleration_score
                or (snapshot.rvol >= settings.claude_min_rvol and catalyst.news_count_24h > 0)
            )
        )
        if not should_call:
            return self.claude.fallback(snapshot, catalyst, preliminary, "Claude skipped by cost gate; local heuristic analysis used.")

        position_status = "held" if in_position else "none"
        analysis = self.claude.analyze(snapshot, structural, catalyst, social, preliminary, position_status=position_status)
        self.claude_cache[symbol] = (time.time(), analysis)
        return analysis

    def _run_discovery_if_due(self) -> None:
        self.storage.prune_opportunities(settings.opportunity_ttl_minutes)
        now = time.time()
        if not settings.enable_market_discovery:
            return
        if now - self.last_discovery_at < settings.discovery_interval_seconds:
            return
        self.last_discovery_at = now
        positions = set(self.market.positions().keys())
        discovered = self.discovery.discover(exclude=set(settings.watchlist) | positions)
        for opportunity in discovered:
            self.storage.upsert_opportunity(opportunity)
        if discovered:
            log(f"Discovery added: {', '.join(op.symbol for op in discovered)}")

    def _maybe_swap(self, scored_positions: dict, scored_entries: dict, risk_state) -> None:
        if not settings.enable_swaps or not scored_positions or not scored_entries:
            return
        if risk_state.open_positions < settings.max_open_positions:
            return
        candidates = [
            (symbol, scores, analysis, decision, snapshot, regime_passed, regime_reason)
            for symbol, (scores, analysis, decision, snapshot, regime_passed, regime_reason) in scored_entries.items()
            if scores.composite >= settings.swap_min_score
        ]
        if not candidates:
            return
        candidates.sort(key=lambda item: item[1].composite, reverse=True)
        candidate_symbol, candidate_scores, candidate_analysis, _, candidate_snapshot, regime_passed, regime_reason = candidates[0]
        weakest = None
        for symbol, (scores, position, snapshot) in scored_positions.items():
            if weakest is None or scores.composite < weakest[1].composite:
                weakest = (symbol, scores, position, snapshot)
        if weakest is None:
            return
        held_symbol, held_scores, held_position, held_snapshot = weakest
        swap_exit = self.policy.decide_swap_exit(
            held_symbol,
            held_scores,
            held_position.unrealized_gain_pct,
            candidate_symbol,
            candidate_scores,
        )
        if swap_exit.action.value != "SELL":
            return
        swap_exit.quantity = held_position.quantity
        post_exit_risk = replace(risk_state, open_positions=max(0, risk_state.open_positions - 1))
        candidate_decision = self.policy.decide_entry(
            candidate_snapshot,
            candidate_scores,
            candidate_analysis,
            post_exit_risk,
            regime_passed,
            regime_reason,
        )
        if candidate_decision.action.value != "BUY":
            return
        self.storage.log_scan(held_symbol, held_snapshot.price, held_scores, swap_exit, {"swap_candidate": candidate_symbol, "decision": asdict(swap_exit)})
        exited = self.executor.execute(swap_exit, held_snapshot.price)
        if not exited:
            return
        candidate_decision.reason = f"swap entry after selling {held_symbol}"
        self.storage.log_scan(candidate_symbol, candidate_snapshot.price, candidate_scores, candidate_decision, {"swap_exit": held_symbol, "decision": asdict(candidate_decision)})
        self.executor.execute(candidate_decision, candidate_snapshot.price)


def run_worker() -> None:
    bot = Bot()
    alpaca_status = "configured" if bot.market.configured() else "missing Alpaca API key/secret"
    log(
        "Worker started. "
        f"Watchlist={','.join(settings.watchlist)} "
        f"interval={settings.scan_interval_seconds}s "
        f"dry_run={settings.dry_run} "
        f"alpaca={alpaca_status} "
        f"utc={datetime.now(UTC).isoformat()}"
    )
    while True:
        started = time.time()
        try:
            bot.scan_once()
        except Exception as exc:
            print(f"Worker cycle failed: {exc}")
        elapsed = time.time() - started
        time.sleep(max(1, settings.scan_interval_seconds - elapsed))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["scan-once", "worker"])
    args = parser.parse_args()
    if args.command == "scan-once":
        Bot().scan_once()
    else:
        run_worker()


if __name__ == "__main__":
    main()
