from __future__ import annotations

import argparse
import time
from collections import Counter
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
        self.claude_budget_day = datetime.now(UTC).date()
        self.claude_calls_today = 0
        self.claude_spend_today = 0.0
        self.last_discovery_at = 0.0

    def scan_once(self) -> None:
        self.executor.reconcile_pending_orders()
        summary = {
            "symbols": 0,
            "scored": 0,
            "skipped_snapshot": 0,
            "executed_buy": 0,
            "executed_sell": 0,
        }
        action_counts: Counter[str] = Counter()
        claude_status_counts: Counter[str] = Counter()
        snapshot_error_counts: Counter[str] = Counter()
        top_candidates: list[dict] = []
        finalist_audits: list[dict] = []
        finalist_counts: Counter[str] = Counter()
        self.enrichment.reset_status()
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
        summary["symbols"] = len(symbols)
        scored_entries: dict[str, tuple] = {}
        scored_positions: dict[str, tuple] = {}
        for symbol in symbols:
            snapshot = self.market.snapshot(symbol)
            if snapshot is None:
                summary["skipped_snapshot"] += 1
                if self.market.last_error:
                    snapshot_error_counts[self._short_error(self.market.last_error)] += 1
                detail = f": {self.market.last_error}" if self.market.last_error else ""
                log(f"{symbol}: skipped, no market snapshot available{detail}")
                continue
            self.storage.update_candidate_returns(symbol, snapshot.price)

            structural = self.enrichment.structural_data(symbol)
            catalyst = self.enrichment.catalyst_data(symbol)
            social = self.enrichment.social_data(symbol)
            preliminary = build_scores(snapshot, structural, catalyst, social, previous_acceleration=self.previous_acceleration.get(symbol))
            in_position = symbol in positions
            analysis, claude_status = self._analyze_with_claude_budget(symbol, snapshot, structural, catalyst, social, preliminary, in_position)
            scores = build_scores(
                snapshot,
                structural,
                catalyst,
                social,
                claude_catalyst_quality=analysis.catalyst_quality,
                previous_acceleration=self.previous_acceleration.get(symbol),
            )
            summary["scored"] += 1
            claude_status_counts[claude_status] += 1
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
                audit = self._entry_gate_audit(snapshot, scores, decision, risk_state, regime_passed, regime_reason, claude_status)
                finalist_audits.append(audit)
                for key, value in audit.items():
                    if isinstance(value, bool) and value:
                        finalist_counts[key] += 1
            action_counts[decision.action.value] += 1
            top_candidates.append(
                {
                    "symbol": symbol,
                    "score": scores.composite,
                    "acceleration": scores.acceleration,
                    "rvol": snapshot.rvol,
                    "breakout": snapshot.breakout_confirmed,
                    "action": decision.action.value,
                    "reason": decision.reason,
                    "in_position": symbol in positions,
                }
            )
            payload = {
                "snapshot": asdict(snapshot),
                "structural": asdict(structural),
                "catalyst": asdict(catalyst),
                "social": asdict(social),
                "scores": asdict(scores),
                "claude": asdict(analysis),
                "claude_status": claude_status,
                "claude_budget": {
                    "calls_today": self.claude_calls_today,
                    "estimated_spend_today": round(self.claude_spend_today, 4),
                    "daily_budget": settings.claude_daily_budget_usd,
                },
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
                summary["executed_buy"] += 1
            elif executed and decision.action.value == "SELL":
                risk_state.open_positions = max(0, risk_state.open_positions - 1)
                summary["executed_sell"] += 1
            log(f"{symbol}: {decision.action} | score={scores.composite:.1f} accel={scores.acceleration:.1f} | claude={claude_status} | {decision.reason}")

        self._maybe_swap(scored_positions, scored_entries, risk_state)
        self._log_scan_summary(
            summary,
            action_counts,
            claude_status_counts,
            snapshot_error_counts,
            top_candidates,
            finalist_audits,
            finalist_counts,
            self.enrichment.status_summary(),
            risk_state,
            regime_passed,
            regime_reason,
            len(opportunities),
        )

    def _analyze_with_claude_budget(self, symbol, snapshot, structural, catalyst, social, preliminary, in_position: bool):
        self._reset_claude_budget_if_needed()
        cached = self.claude_cache.get(symbol)
        cache_minutes = settings.claude_position_cache_minutes if in_position else settings.claude_cache_minutes
        if cached and time.time() - cached[0] < max(1, cache_minutes) * 60:
            return cached[1], "cached"

        should_call = (
            settings.enable_claude_analysis
            and bool(settings.anthropic_api_key)
            and (
                in_position
                or preliminary.composite >= settings.claude_min_composite_score
                or self._is_claude_finalist(snapshot, preliminary)
                or (
                    preliminary.acceleration >= settings.claude_min_acceleration_score
                    and snapshot.rvol >= settings.claude_min_rvol
                )
            )
        )
        if not should_call:
            return self.claude.fallback(snapshot, catalyst, preliminary, "Claude skipped by cost gate; local heuristic analysis used."), "skipped_cost_gate"

        projected_spend = self.claude_spend_today + settings.claude_estimated_cost_per_call_usd
        if self.claude_calls_today >= settings.claude_max_calls_per_day:
            return self.claude.fallback(snapshot, catalyst, preliminary, "Claude skipped because daily call limit was reached."), "skipped_daily_call_limit"
        if projected_spend > settings.claude_daily_budget_usd:
            return self.claude.fallback(snapshot, catalyst, preliminary, "Claude skipped because daily budget was reached."), "skipped_daily_budget"

        position_status = "held" if in_position else "none"
        analysis = self.claude.analyze(snapshot, structural, catalyst, social, preliminary, position_status=position_status)
        self.claude_calls_today += 1
        self.claude_spend_today += float(analysis.raw.get("_estimated_cost_usd", settings.claude_estimated_cost_per_call_usd) or settings.claude_estimated_cost_per_call_usd)
        self.claude_cache[symbol] = (time.time(), analysis)
        return analysis, "called"

    @staticmethod
    def _is_claude_finalist(snapshot, scores) -> bool:
        if not settings.claude_call_finalists:
            return False
        near_breakout = snapshot.near_breakout(settings.early_probe_breakout_distance_pct)
        above_vwap = snapshot.above_vwap_candles >= settings.high_conviction_above_vwap_candles
        standard_finalist = (
            scores.composite >= settings.claude_finalist_min_composite_score
            and scores.acceleration >= settings.claude_finalist_min_acceleration_score
            and snapshot.rvol >= settings.claude_finalist_min_rvol
            and near_breakout
            and above_vwap
        )
        market_data_override = (
            scores.acceleration >= settings.early_probe_strong_acceleration_score
            and snapshot.rvol >= settings.early_probe_strong_rvol
            and near_breakout
            and above_vwap
        )
        return standard_finalist or market_data_override

    def _entry_gate_audit(self, snapshot, scores, decision, risk_state, regime_passed: bool, regime_reason: str, claude_status: str) -> dict:
        near_breakout = snapshot.near_breakout(settings.early_probe_breakout_distance_pct)
        market_data_setup = (
            (
                snapshot.breakout_confirmed
                and snapshot.rvol >= settings.min_rvol
                and snapshot.above_vwap_candles >= settings.min_above_vwap_candles
            )
            or (
                near_breakout
                and scores.acceleration >= settings.early_probe_min_acceleration_score
                and snapshot.rvol >= settings.early_probe_min_rvol
                and snapshot.above_vwap_candles >= settings.high_conviction_above_vwap_candles
            )
            or (
                near_breakout
                and scores.acceleration >= settings.early_probe_strong_acceleration_score
                and snapshot.rvol >= settings.early_probe_strong_rvol
                and snapshot.above_vwap_candles >= settings.high_conviction_above_vwap_candles
            )
        )
        risk_allowed, risk_reason = self.policy.risk.can_enter(risk_state, snapshot)
        return {
            "symbol": snapshot.symbol,
            "market_data_setup": market_data_setup,
            "near_breakout": near_breakout,
            "breakout_confirmed": snapshot.breakout_confirmed,
            "above_vwap": snapshot.above_vwap_candles >= settings.high_conviction_above_vwap_candles,
            "risk_allowed": risk_allowed,
            "regime_passed": regime_passed,
            "claude_finalist": self._is_claude_finalist(snapshot, scores),
            "claude_called": claude_status == "called",
            "buy_decision": decision.action.value == "BUY",
            "score": scores.composite,
            "acceleration": scores.acceleration,
            "rvol": snapshot.rvol,
            "reason": decision.reason,
            "risk_reason": risk_reason,
            "regime_reason": regime_reason,
        }

    def _reset_claude_budget_if_needed(self) -> None:
        today = datetime.now(UTC).date()
        if today != self.claude_budget_day:
            self.claude_budget_day = today
            self.claude_calls_today = 0
            self.claude_spend_today = 0.0

    def should_run_full_scan(self) -> tuple[bool, int, str]:
        if not settings.enable_market_hours_throttle:
            return True, settings.scan_interval_seconds, "market-hours throttle disabled"
        session = self.executor.session_guard.current()
        if session.is_open:
            return True, settings.scan_interval_seconds, session.reason
        if session.session == "premarket":
            return True, settings.premarket_scan_interval_seconds, session.reason
        if settings.enable_closed_market_discovery:
            return True, settings.closed_market_scan_interval_seconds, session.reason
        return False, settings.closed_market_scan_interval_seconds, session.reason

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
            log(
                "Discovery added "
                f"{len(discovered)}/{settings.discovery_max_symbols}: "
                f"{', '.join(op.symbol for op in discovered)}"
            )
        else:
            log("Discovery found no new candidates")

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

    def api_health_line(self) -> str:
        alpaca = "configured" if self.market.configured() else "missing"
        execution_mode = "paper" if settings.alpaca_paper else "live"
        execution = "enabled" if settings.enable_alpaca_execution else "disabled"
        claude = "configured" if settings.anthropic_api_key else "missing"
        fmp = "configured" if settings.fmp_api_key else "missing"
        finnhub = "configured" if settings.finnhub_api_key else "missing"
        reddit = "configured" if settings.reddit_client_id and settings.reddit_client_secret else "missing"
        google_trends = "enabled" if settings.enable_google_trends else "disabled"
        return (
            "API health: "
            f"alpaca={alpaca} execution={execution}_{execution_mode} dry_run={settings.dry_run} "
            f"claude={claude} model={settings.claude_model} "
            f"claude_budget=${settings.claude_daily_budget_usd:.2f}/day max_calls={settings.claude_max_calls_per_day} "
            f"claude_finalists={settings.claude_call_finalists} "
            f"fmp={fmp} finnhub={finnhub} reddit={reddit} google_trends={google_trends} "
            f"discovery=every_{settings.discovery_interval_seconds}s max_symbols={settings.discovery_max_symbols} "
            f"opportunity_scan_limit={settings.opportunity_scan_limit} snapshot_cache={settings.market_snapshot_cache_seconds}s"
        )

    def _log_scan_summary(
        self,
        summary: dict,
        action_counts: Counter[str],
        claude_status_counts: Counter[str],
        snapshot_error_counts: Counter[str],
        top_candidates: list[dict],
        finalist_audits: list[dict],
        finalist_counts: Counter[str],
        enrichment_summary: dict,
        risk_state,
        regime_passed: bool,
        regime_reason: str,
        active_opportunities: int,
    ) -> None:
        if not settings.log_scan_summary:
            return
        self.storage.set_state(
            "last_scan_summary",
            {
                "at": time.time(),
                "summary": summary,
                "actions": dict(action_counts),
                "claude": dict(claude_status_counts),
                "snapshot_errors": dict(snapshot_error_counts),
                "buy_gate_audit": {
                    "counts": dict(finalist_counts),
                    "finalists": self._rank_audits(finalist_audits)[: settings.log_top_candidates],
                },
                "enrichment": enrichment_summary,
                "top_candidates": sorted(top_candidates, key=lambda item: item["score"], reverse=True)[: settings.log_top_candidates],
                "regime": {"passed": regime_passed, "reason": regime_reason},
            },
        )
        log(
            "Scan summary: "
            f"symbols={summary['symbols']} scored={summary['scored']} "
            f"snapshot_skips={summary['skipped_snapshot']} "
            f"actions={self._format_counter(action_counts)} "
            f"executed_buy={summary['executed_buy']} executed_sell={summary['executed_sell']} "
            f"active_opportunities={active_opportunities} "
            f"risk=open_positions:{risk_state.open_positions}/{settings.max_open_positions},"
            f"trades_today:{risk_state.trades_today}/{settings.max_trades_per_day},"
            f"losses_today:{risk_state.losses_today}/{settings.stop_after_losses},"
            f"buying_power:{risk_state.buying_power:.2f} "
            f"regime={'pass' if regime_passed else 'block'}({regime_reason}) "
            f"claude={self._format_counter(claude_status_counts)} "
            f"claude_spend=${self.claude_spend_today:.4f}/${settings.claude_daily_budget_usd:.2f}"
        )
        enrichment_status = Counter(enrichment_summary.get("status", {}))
        enrichment_errors = Counter(enrichment_summary.get("errors", {}))
        log(f"Data sources: {self._format_counter(enrichment_status, limit=8)}")
        if enrichment_errors:
            log(f"Data source issues: {self._format_counter(enrichment_errors, limit=5)}")
        if snapshot_error_counts:
            log(f"Snapshot issues: {self._format_counter(snapshot_error_counts, limit=3)}")
        self._log_buy_gate_audit(finalist_audits, finalist_counts)
        self._log_top_candidates(top_candidates)

    def _log_buy_gate_audit(self, audits: list[dict], counts: Counter[str]) -> None:
        if not audits:
            return
        log(
            "Buy gate audit: "
            f"market_data_setup={counts.get('market_data_setup', 0)} "
            f"risk_allowed={counts.get('risk_allowed', 0)} "
            f"claude_finalists={counts.get('claude_finalist', 0)} "
            f"claude_called={counts.get('claude_called', 0)} "
            f"buy_decisions={counts.get('buy_decision', 0)}"
        )
        ranked = self._rank_audits(audits)[: settings.log_top_candidates]
        parts = []
        for item in ranked:
            parts.append(
                f"{item['symbol']} market={item['market_data_setup']} risk={item['risk_allowed']} "
                f"claude_finalist={item['claude_finalist']} claude_called={item['claude_called']} "
                f"buy={item['buy_decision']} score={item['score']:.1f} accel={item['acceleration']:.1f} "
                f"rvol={item['rvol']:.2f} reason={self._clip(item['reason'], 80)}"
            )
        log(f"Buy gate finalists: {' | '.join(parts)}")

    @staticmethod
    def _rank_audits(audits: list[dict]) -> list[dict]:
        return sorted(
            audits,
            key=lambda item: (
                bool(item.get("buy_decision")),
                bool(item.get("market_data_setup")),
                bool(item.get("claude_finalist")),
                float(item.get("acceleration", 0) or 0),
                float(item.get("rvol", 0) or 0),
                float(item.get("score", 0) or 0),
            ),
            reverse=True,
        )

    def _log_top_candidates(self, candidates: list[dict]) -> None:
        limit = max(0, settings.log_top_candidates)
        if limit == 0 or not candidates:
            return
        ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)[:limit]
        parts = []
        for item in ranked:
            parts.append(
                f"{item['symbol']} score={item['score']:.1f} accel={item['acceleration']:.1f} "
                f"rvol={item['rvol']:.2f} breakout={item['breakout']} "
                f"action={item['action']} reason={self._clip(item['reason'], 90)}"
            )
        log(f"Top candidates: {' | '.join(parts)}")
        buys = [item for item in candidates if item["action"] == "BUY"]
        if not buys:
            best = ranked[0]
            log(
                "No buy this cycle: "
                f"best={best['symbol']} score={best['score']:.1f} accel={best['acceleration']:.1f} "
                f"rvol={best['rvol']:.2f} blocked_by={self._clip(best['reason'], 140)}"
            )

    @staticmethod
    def _format_counter(counter: Counter[str], limit: int | None = None) -> str:
        if not counter:
            return "none"
        items = counter.most_common(limit)
        return ",".join(f"{key}:{value}" for key, value in items)

    @staticmethod
    def _clip(value: str, limit: int) -> str:
        clean = " ".join(str(value).split())
        if len(clean) <= limit:
            return clean
        return clean[: max(0, limit - 3)] + "..."

    @classmethod
    def _short_error(cls, value: str) -> str:
        text = str(value)
        if "Connection reset by peer" in text:
            return "alpaca_connection_reset"
        if "Read timed out" in text or "read timeout" in text.lower():
            return "alpaca_read_timeout"
        if "Max retries exceeded" in text:
            return "alpaca_max_retries"
        if "429" in text or "rate limit" in text.lower():
            return "rate_limited"
        return cls._clip(text, 80)


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
    if settings.log_api_health:
        log(bot.api_health_line())
    while True:
        started = time.time()
        try:
            should_scan, sleep_seconds, session_reason = bot.should_run_full_scan()
            if should_scan:
                bot.scan_once()
            else:
                bot.executor.reconcile_pending_orders()
                bot.storage.set_state("heartbeat", {"at": time.time(), "watchlist": list(settings.watchlist), "session": session_reason, "mode": "closed_market_throttle"})
                log(f"Market closed throttle active: {session_reason}. Next light check in {sleep_seconds}s")
        except Exception as exc:
            print(f"Worker cycle failed: {exc}")
            sleep_seconds = settings.scan_interval_seconds
        elapsed = time.time() - started
        time.sleep(max(1, sleep_seconds - elapsed))


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
