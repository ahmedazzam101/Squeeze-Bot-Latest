from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import requests

from squeeze_bot.config import Settings
from squeeze_bot.engines.session import SessionGuard
from squeeze_bot.models import Decision, PositionMeta, TradeAction
from squeeze_bot.storage import Storage


class AlpacaExecutor:
    def __init__(self, settings: Settings, storage: Storage):
        self.settings = settings
        self.storage = storage
        self.session_guard = SessionGuard(settings)
        self.base = "https://paper-api.alpaca.markets" if settings.alpaca_paper else "https://api.alpaca.markets"
        self.headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
            "Content-Type": "application/json",
        }

    def execute(self, decision: Decision, market_price: float) -> bool:
        if decision.action not in {TradeAction.BUY, TradeAction.SELL}:
            return False
        side = "buy" if decision.action == TradeAction.BUY else "sell"
        if decision.quantity <= 0:
            self.storage.log_order(decision.symbol, side, 0, market_price, "skipped_zero_quantity", decision.__dict__)
            return False
        session = self.session_guard.current()
        if not session.is_open:
            self.storage.log_order(decision.symbol, side, decision.quantity, market_price, f"deferred_{session.session}", {"decision": decision.__dict__, "session": session.__dict__})
            return False
        if self.settings.dry_run or not self.settings.enable_alpaca_execution:
            self.storage.log_order(decision.symbol, side, decision.quantity, market_price, "dry_run", decision.__dict__)
            self._apply_local_fill(decision, side, market_price)
            return True
        payload = {
            "symbol": decision.symbol,
            "qty": str(decision.quantity),
            "side": side,
            "type": "limit" if decision.limit_price else "market",
            "time_in_force": "day",
        }
        if decision.limit_price:
            payload["limit_price"] = f"{decision.limit_price:.2f}"
        response = requests.post(f"{self.base}/v2/orders", headers=self.headers, json=payload, timeout=10)
        status = "submitted" if response.ok else f"error_{response.status_code}"
        response_payload = self._safe_json(response)
        self.storage.log_order(decision.symbol, side, decision.quantity, market_price, status, {"request": payload, "response": response_payload})
        if not response.ok:
            return False
        order_id = str(response_payload.get("id", ""))
        if order_id:
            self.storage.add_pending_order(order_id, decision.symbol, side, decision.quantity, {"request": payload, "response": response_payload, "decision": decision.__dict__})
            fill = self._poll_order(order_id)
            if fill and fill.get("status") == "filled":
                fill_price = float(fill.get("filled_avg_price") or market_price)
                self.storage.update_pending_order(order_id, "filled", fill)
                self.storage.log_order(decision.symbol, side, decision.quantity, fill_price, "filled", fill)
                self._apply_local_fill(decision, side, fill_price)
                return True
        return False

    def reconcile_pending_orders(self) -> None:
        if self.settings.dry_run or not self.settings.enable_alpaca_execution:
            return
        cutoff = datetime.now(UTC) - timedelta(minutes=self.settings.stale_order_ttl_minutes)
        for order in self.storage.open_pending_orders():
            payload = self._get_order(order.alpaca_order_id)
            if not payload:
                continue
            status = str(payload.get("status", "unknown"))
            if status == "filled":
                price = float(payload.get("filled_avg_price") or 0)
                self.storage.update_pending_order(order.alpaca_order_id, "filled", payload)
                self.storage.log_order(order.symbol, order.side, order.quantity, price, "filled_reconciled", payload)
                decision_payload = self._pending_decision_payload(order.payload_json)
                decision = Decision(
                    symbol=order.symbol,
                    action=TradeAction.BUY if order.side == "buy" else TradeAction.SELL,
                    reason=str(decision_payload.get("reason", "reconciled fill")),
                    quantity=order.quantity,
                    stop_price=float(decision_payload.get("stop_price", 0) or 0),
                    metadata=dict(decision_payload.get("metadata", {}) or {}),
                )
                self._apply_local_fill(decision, order.side, price)
            elif status in {"canceled", "expired", "rejected"}:
                self.storage.update_pending_order(order.alpaca_order_id, status, payload)
            elif order.created_at.replace(tzinfo=UTC) < cutoff:
                cancel = self._cancel_order(order.alpaca_order_id)
                self.storage.update_pending_order(order.alpaca_order_id, "stale_canceled", cancel or payload)
                self.storage.log_order(order.symbol, order.side, order.quantity, 0, "stale_canceled", cancel or payload)

    def _apply_local_fill(self, decision: Decision, side: str, fill_price: float) -> None:
        if side == "buy":
            self.storage.upsert_position_meta(
                PositionMeta(
                    symbol=decision.symbol,
                    entry_time=datetime.now(UTC),
                    entry_price=fill_price,
                    peak_price=fill_price,
                    entry_score=float(decision.metadata.get("entry_score", 0) or 0),
                    entry_acceleration=float(decision.metadata.get("entry_acceleration", 0) or 0),
                    stop_price=decision.stop_price,
                    trailing_stop_pct=float(decision.metadata.get("trailing_stop_pct", self.settings.trail_pct) or self.settings.trail_pct),
                )
            )
        elif side == "sell":
            self.storage.record_trade_outcome(decision.symbol, fill_price, decision.quantity, decision.reason)
            self.storage.delete_position_meta(decision.symbol)

    def _poll_order(self, order_id: str) -> dict | None:
        for _ in range(3):
            payload = self._get_order(order_id)
            if payload and payload.get("status") in {"filled", "rejected", "canceled", "expired"}:
                return payload
            time.sleep(0.5)
        return self._get_order(order_id)

    def _get_order(self, order_id: str) -> dict | None:
        try:
            response = requests.get(f"{self.base}/v2/orders/{order_id}", headers=self.headers, timeout=10)
            if response.ok:
                return response.json()
        except requests.RequestException:
            return None
        return None

    def _cancel_order(self, order_id: str) -> dict | None:
        try:
            response = requests.delete(f"{self.base}/v2/orders/{order_id}", headers=self.headers, timeout=10)
            return {"status_code": response.status_code, "text": response.text}
        except requests.RequestException as exc:
            return {"error": str(exc)}

    @staticmethod
    def _safe_json(response: requests.Response) -> dict:
        try:
            return response.json()
        except ValueError:
            return {"text": response.text}

    @staticmethod
    def _pending_decision_payload(payload_json: str) -> dict:
        try:
            import json

            payload = json.loads(payload_json)
            decision = payload.get("decision", {})
            return decision if isinstance(decision, dict) else {}
        except Exception:
            return {}
