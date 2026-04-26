from __future__ import annotations

from datetime import UTC, datetime, timedelta
from statistics import mean

import requests

from squeeze_bot.config import Settings
from squeeze_bot.models import MarketSnapshot, Position, RiskState


class AlpacaMarketClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
        }
        self.data_base = "https://data.alpaca.markets"
        self.trade_base = "https://paper-api.alpaca.markets" if settings.alpaca_paper else "https://api.alpaca.markets"

    def configured(self) -> bool:
        return bool(self.settings.alpaca_api_key and self.settings.alpaca_secret_key)

    def snapshot(self, symbol: str) -> MarketSnapshot | None:
        if not self.configured():
            return None
        try:
            bars = self._bars(symbol, "1Min", limit=80)
            daily = self._bars(symbol, "1Day", limit=31)
            quote = self._latest_quote(symbol)
        except requests.RequestException:
            return None
        if not bars:
            return None

        closes = [float(bar["c"]) for bar in bars]
        highs = [float(bar["h"]) for bar in bars]
        volumes = [float(bar["v"]) for bar in bars]
        last = bars[-1]
        price = float(last["c"])
        vwap = self._vwap(bars[-20:])
        average_volume = mean([float(bar["v"]) for bar in daily[:-1]]) if len(daily) > 2 else mean(volumes)
        previous_close = float(daily[-2]["c"]) if len(daily) > 1 else closes[0]
        recent_volume = sum(volumes[-5:])
        baseline_volume = mean(volumes[:-5]) * 5 if len(volumes) > 10 else max(mean(volumes), 1)
        recent_volume_ratio = (recent_volume / baseline_volume) if baseline_volume else 0.0
        projected_daily_volume = sum(volumes) * (390 / max(min(len(volumes), 390), 1))
        price_velocity = ((closes[-1] - closes[-6]) / closes[-6] * 100) if len(closes) > 6 and closes[-6] else 0.0
        volume_growth = ((recent_volume - baseline_volume) / baseline_volume * 100) if baseline_volume else 0.0
        volatility_expansion = self._volatility_expansion(closes)

        return MarketSnapshot(
            symbol=symbol,
            price=price,
            previous_close=previous_close,
            volume=sum(volumes),
            average_volume=average_volume,
            rvol=(projected_daily_volume / average_volume) if average_volume else 0.0,
            recent_volume_ratio=recent_volume_ratio,
            vwap=vwap,
            above_vwap_candles=sum(1 for bar in bars[-2:] if float(bar["c"]) > vwap),
            premarket_high=max(highs[:-1]) if len(highs) > 1 else 0.0,
            resistance=max(highs[-30:-1]) if len(highs) > 31 else max(highs[:-1], default=0.0),
            bid=float(quote.get("bp", 0) or 0),
            ask=float(quote.get("ap", 0) or 0),
            intraday_change_pct=((price - previous_close) / previous_close * 100) if previous_close else 0.0,
            price_velocity_pct=price_velocity,
            volume_growth_pct=volume_growth,
            volatility_expansion_pct=volatility_expansion,
        )

    def account_risk_state(self) -> RiskState:
        if not self.configured():
            return RiskState(equity=10_000, buying_power=10_000, daily_pnl_pct=0, open_positions=0, trades_today=0, losses_today=0)
        try:
            account = requests.get(f"{self.trade_base}/v2/account", headers=self.headers, timeout=10).json()
            positions = requests.get(f"{self.trade_base}/v2/positions", headers=self.headers, timeout=10).json()
        except requests.RequestException:
            return RiskState(equity=10_000, buying_power=10_000, daily_pnl_pct=0, open_positions=0, trades_today=0, losses_today=0)
        equity = float(account.get("equity", 10_000))
        last_equity = float(account.get("last_equity", equity))
        daily_pnl_pct = ((equity - last_equity) / last_equity * 100) if last_equity else 0.0
        return RiskState(
            equity=equity,
            buying_power=float(account.get("buying_power", 0) or 0),
            daily_pnl_pct=daily_pnl_pct,
            open_positions=len(positions) if isinstance(positions, list) else 0,
            trades_today=0,
            losses_today=0,
        )

    def positions(self) -> dict[str, Position]:
        if not self.configured():
            return {}
        try:
            response = requests.get(f"{self.trade_base}/v2/positions", headers=self.headers, timeout=10)
            response.raise_for_status()
        except requests.RequestException:
            return {}
        rows = response.json()
        if not isinstance(rows, list):
            return {}
        positions: dict[str, Position] = {}
        for row in rows:
            symbol = str(row.get("symbol", "")).upper()
            if not symbol:
                continue
            qty = float(row.get("qty", 0) or 0)
            positions[symbol] = Position(
                symbol=symbol,
                quantity=qty,
                average_entry_price=float(row.get("avg_entry_price", 0) or 0),
                market_value=float(row.get("market_value", 0) or 0),
                unrealized_gain_pct=float(row.get("unrealized_plpc", 0) or 0) * 100,
            )
        return positions

    def _bars(self, symbol: str, timeframe: str, limit: int) -> list[dict]:
        end = datetime.now(UTC)
        start = end - (timedelta(days=45) if timeframe == "1Day" else timedelta(days=2))
        params = {
            "symbols": symbol,
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": limit,
            "adjustment": "raw",
            "feed": "iex",
        }
        response = requests.get(f"{self.data_base}/v2/stocks/bars", headers=self.headers, params=params, timeout=15)
        response.raise_for_status()
        return response.json().get("bars", {}).get(symbol, [])

    def _latest_quote(self, symbol: str) -> dict:
        response = requests.get(f"{self.data_base}/v2/stocks/{symbol}/quotes/latest", headers=self.headers, params={"feed": "iex"}, timeout=10)
        response.raise_for_status()
        return response.json().get("quote", {})

    @staticmethod
    def _vwap(bars: list[dict]) -> float:
        numerator = sum(((float(bar["h"]) + float(bar["l"]) + float(bar["c"])) / 3) * float(bar["v"]) for bar in bars)
        denominator = sum(float(bar["v"]) for bar in bars)
        return numerator / denominator if denominator else 0.0

    @staticmethod
    def _volatility_expansion(closes: list[float]) -> float:
        if len(closes) < 30:
            return 0.0
        recent = max(closes[-10:]) - min(closes[-10:])
        baseline = max(closes[-30:-10]) - min(closes[-30:-10])
        return ((recent - baseline) / baseline * 100) if baseline else 0.0
