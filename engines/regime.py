from __future__ import annotations

import yfinance as yf


class RegimeFilter:
    def passes(self) -> tuple[bool, str]:
        try:
            vix = yf.Ticker("^VIX").history(period="2d", interval="1d")["Close"]
            spy = yf.Ticker("SPY").history(period="2d", interval="1d")["Close"]
            vix_last = float(vix.iloc[-1])
            spy_move = abs((float(spy.iloc[-1]) - float(spy.iloc[-2])) / float(spy.iloc[-2]) * 100) if len(spy) > 1 else 0.0
            passed = vix_last >= 18 or spy_move >= 1
            return passed, f"VIX={vix_last:.2f}, SPY move={spy_move:.2f}%"
        except Exception as exc:
            return False, f"Regime unavailable: {exc}"
