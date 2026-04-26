from __future__ import annotations

from datetime import UTC, datetime

import requests

from squeeze_bot.config import Settings
from squeeze_bot.data.market import AlpacaMarketClient
from squeeze_bot.models import Opportunity


class MarketDiscoveryClient:
    def __init__(self, settings: Settings, market: AlpacaMarketClient):
        self.settings = settings
        self.market = market
        self.headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
        }
        self.data_base = "https://data.alpaca.markets"

    def discover(self, exclude: set[str] | None = None) -> list[Opportunity]:
        if not self.settings.enable_market_discovery or not self.market.configured():
            return []
        exclude = exclude or set()
        source_symbols = self._top_movers()
        opportunities: list[Opportunity] = []
        for symbol in source_symbols:
            if symbol in exclude:
                continue
            snapshot = self.market.snapshot(symbol)
            if snapshot is None:
                continue
            if snapshot.price < self.settings.discovery_min_price:
                continue
            volume_signal = max(snapshot.rvol, snapshot.recent_volume_ratio)
            if snapshot.intraday_change_pct < self.settings.discovery_min_move_pct and volume_signal < self.settings.discovery_min_rvol:
                continue
            if volume_signal < self.settings.discovery_min_rvol:
                continue
            score = self._opportunity_score(snapshot.intraday_change_pct, snapshot.rvol)
            opportunities.append(
                Opportunity(
                    symbol=symbol,
                    source="alpaca_movers",
                    score=score,
                    move_pct=snapshot.intraday_change_pct,
                    rvol=volume_signal,
                    price=snapshot.price,
                    reason=f"move={snapshot.intraday_change_pct:.1f}% volume_signal={volume_signal:.1f}",
                    discovered_at=datetime.now(UTC),
                )
            )
            if len(opportunities) >= self.settings.discovery_max_symbols:
                break
        return opportunities

    def _top_movers(self) -> list[str]:
        symbols: list[str] = []
        endpoints = [
            f"{self.data_base}/v1beta1/screener/stocks/movers",
            f"{self.data_base}/v1beta1/screener/stocks/most-actives",
        ]
        for endpoint in endpoints:
            try:
                response = requests.get(endpoint, headers=self.headers, params={"top": 50}, timeout=12)
                if not response.ok:
                    continue
                payload = response.json()
            except requests.RequestException:
                continue
            symbols.extend(self._symbols_from_payload(payload))
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
                symbol = row.get("symbol") or row.get("ticker")
                if symbol:
                    symbols.append(str(symbol).upper())
        return symbols

    @staticmethod
    def _opportunity_score(move_pct: float, rvol: float) -> float:
        move_component = min(max(move_pct, 0), 20) / 20 * 60
        rvol_component = min(max(rvol, 0), 8) / 8 * 40
        return min(100.0, move_component + rvol_component)
