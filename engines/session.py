from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import requests

from squeeze_bot.config import Settings
from squeeze_bot.models import MarketSession


class SessionGuard:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base = "https://paper-api.alpaca.markets" if settings.alpaca_paper else "https://api.alpaca.markets"
        self.headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
        }

    def current(self) -> MarketSession:
        if self.settings.alpaca_api_key and self.settings.alpaca_secret_key:
            try:
                response = requests.get(f"{self.base}/v2/clock", headers=self.headers, timeout=8)
                response.raise_for_status()
                payload = response.json()
                if payload.get("is_open"):
                    return MarketSession(True, "regular", "Alpaca clock open")
                return MarketSession(False, "closed", "Alpaca clock closed")
            except requests.RequestException:
                pass

        now = datetime.now(ZoneInfo("America/New_York"))
        if now.weekday() >= 5:
            return MarketSession(False, "weekend", "market weekend fallback")
        if time(9, 30) <= now.time() <= time(16, 0):
            return MarketSession(True, "regular", "regular-hours fallback")
        if time(4, 0) <= now.time() < time(9, 30):
            return MarketSession(False, "premarket", "premarket orders disabled")
        if time(16, 0) < now.time() <= time(20, 0):
            return MarketSession(False, "afterhours", "after-hours orders disabled")
        return MarketSession(False, "overnight", "overnight orders disabled")
