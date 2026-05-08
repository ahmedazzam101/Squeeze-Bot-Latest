from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

import requests

from squeeze_bot.config import Settings
from squeeze_bot.data.market import AlpacaMarketClient
from squeeze_bot.models import Opportunity


class MarketDiscoveryClient:
    def __init__(self, settings: Settings, market: AlpacaMarketClient):
        self.settings = settings
        self.market = market
        self.last_summary: dict[str, object] = {}
        self.headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
        }
        self.data_base = "https://data.alpaca.markets"

    def discover(self, exclude: set[str] | None = None) -> list[Opportunity]:
        self.last_summary = {}
        if not self.settings.enable_market_discovery or not self.market.configured():
            self.last_summary = {"enabled": self.settings.enable_market_discovery, "configured": self.market.configured()}
            return []
        exclude = exclude or set()
        source_symbols = self._top_movers()
        endpoint_errors = list(self.last_summary.get("endpoint_errors", [])) if isinstance(self.last_summary, dict) else []
        counts: Counter[str] = Counter(source_symbols= len(source_symbols))
        relaxed: list[Opportunity] = []
        opportunities: list[Opportunity] = []
        for symbol in source_symbols[: self.settings.discovery_source_limit]:
            if symbol in exclude:
                counts["excluded"] += 1
                continue
            if self.settings.discovery_common_stocks_only and not self._looks_like_common_stock(symbol):
                counts["non_common"] += 1
                continue
            snapshot = self.market.snapshot(symbol)
            if snapshot is None:
                counts["snapshot_missing"] += 1
                continue
            if snapshot.price < self.settings.discovery_min_price:
                counts["price"] += 1
                continue
            counts["snapshot_ok"] += 1
            volume_signal = max(snapshot.rvol, snapshot.recent_volume_ratio)
            score = self._opportunity_score(snapshot.intraday_change_pct, volume_signal)
            candidate = Opportunity(
                symbol=symbol,
                source="alpaca_movers",
                score=score,
                move_pct=snapshot.intraday_change_pct,
                rvol=volume_signal,
                price=snapshot.price,
                reason=f"move={snapshot.intraday_change_pct:.1f}% volume_signal={volume_signal:.1f}",
                discovered_at=datetime.now(UTC),
            )
            relaxed.append(candidate)
            move_pass = abs(snapshot.intraday_change_pct) >= self.settings.discovery_min_move_pct
            volume_pass = volume_signal >= self.settings.discovery_min_rvol
            if not (move_pass or volume_pass):
                counts["weak_move_and_volume"] += 1
                continue
            opportunities.append(candidate)
            if len(opportunities) >= self.settings.discovery_max_symbols:
                break
        if not opportunities and self.settings.discovery_keep_relaxed_candidates:
            relaxed = [
                item
                for item in relaxed
                if item.score >= self.settings.discovery_relaxed_score_floor
            ]
            relaxed.sort(key=lambda item: (item.score, abs(item.move_pct), item.rvol), reverse=True)
            opportunities = relaxed[: self.settings.discovery_max_symbols]
            counts["relaxed_added"] = len(opportunities)
        self.last_summary = {
            "counts": dict(counts),
            "source_sample": source_symbols[:10],
            "added": [op.symbol for op in opportunities[:10]],
            "endpoint_errors": endpoint_errors,
        }
        return opportunities

    def _top_movers(self) -> list[str]:
        symbols: list[str] = []
        errors: list[str] = []
        endpoints = [
            f"{self.data_base}/v1beta1/screener/stocks/movers",
            f"{self.data_base}/v1beta1/screener/stocks/most-actives",
        ]
        for endpoint in endpoints:
            try:
                response = requests.get(endpoint, headers=self.headers, params={"top": self.settings.discovery_source_limit}, timeout=12)
                if not response.ok:
                    errors.append(f"{endpoint.rsplit('/', 1)[-1]}:{response.status_code}")
                    continue
                payload = response.json()
            except requests.RequestException:
                errors.append(f"{endpoint.rsplit('/', 1)[-1]}:request_failed")
                continue
            symbols.extend(self._symbols_from_payload(payload))
        yahoo_symbols = self._yahoo_movers()
        if yahoo_symbols:
            symbols.extend(yahoo_symbols)
        if errors:
            self.last_summary["endpoint_errors"] = errors
        return list(dict.fromkeys(symbols))

    def _yahoo_movers(self) -> list[str]:
        symbols: list[str] = []
        screeners = ("day_gainers", "most_actives")
        headers = {"User-Agent": "Mozilla/5.0"}
        for screener in screeners:
            try:
                response = requests.get(
                    "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved",
                    headers=headers,
                    params={"scrIds": screener, "count": self.settings.discovery_source_limit},
                    timeout=12,
                )
                if not response.ok:
                    continue
                payload = response.json()
            except requests.RequestException:
                continue
            symbols.extend(self._symbols_from_yahoo_payload(payload))
        return list(dict.fromkeys(symbols))

    @staticmethod
    def _symbols_from_payload(payload: dict) -> list[str]:
        rows = []
        for key in ("gainers", "losers", "most_actives", "movers"):
            value = payload.get(key)
            if isinstance(value, list):
                rows.extend(value)
        if isinstance(payload.get("data"), list):
            rows.extend(payload["data"])
        symbols = []
        for row in rows:
            if isinstance(row, dict):
                symbol = row.get("symbol") or row.get("ticker") or row.get("S")
                if symbol:
                    symbols.append(str(symbol).upper())
        return symbols

    @staticmethod
    def _symbols_from_yahoo_payload(payload: dict) -> list[str]:
        symbols: list[str] = []
        finance = payload.get("finance", {})
        results = finance.get("result", []) if isinstance(finance, dict) else []
        for result in results:
            if not isinstance(result, dict):
                continue
            for quote in result.get("quotes", []) or []:
                if isinstance(quote, dict) and quote.get("symbol"):
                    symbols.append(str(quote["symbol"]).upper())
        return symbols

    @staticmethod
    def _looks_like_common_stock(symbol: str) -> bool:
        symbol = symbol.upper()
        if "." in symbol or "/" in symbol:
            return False
        if symbol.endswith(("WS", "WT")):
            return False
        if len(symbol) >= 5 and symbol.endswith(("W", "U", "R")):
            return False
        return True

    @staticmethod
    def _opportunity_score(move_pct: float, rvol: float) -> float:
        move_component = min(max(move_pct, 0), 20) / 20 * 60
        rvol_component = min(max(rvol, 0), 8) / 8 * 40
        return min(100.0, move_component + rvol_component)
