from __future__ import annotations

from squeeze_bot.config import Settings
from squeeze_bot.models import MarketSnapshot, RiskState


class RiskGovernor:
    def __init__(self, settings: Settings):
        self.settings = settings

    def can_enter(self, risk: RiskState, snapshot: MarketSnapshot) -> tuple[bool, str]:
        if risk.daily_pnl_pct <= -abs(self.settings.daily_loss_cap_pct):
            return False, "daily loss cap reached"
        if risk.open_positions >= self.settings.max_open_positions:
            return False, "max open positions reached"
        if risk.trades_today >= self.settings.max_trades_per_day:
            return False, "max trades per day reached"
        if risk.losses_today >= self.settings.stop_after_losses:
            return False, "loss limit reached"
        if snapshot.spread_pct > self.settings.max_spread_pct:
            return False, f"spread too wide: {snapshot.spread_pct:.2f}%"
        if risk.buying_power <= 0:
            return False, "no buying power"
        return True, "risk approved"

    def position_size(self, risk: RiskState, snapshot: MarketSnapshot, stop_pct: float | None = None) -> tuple[int, float]:
        resolved_stop_pct = (self.settings.hard_stop_pct / 100) if stop_pct is None else stop_pct
        stop_price = snapshot.price * (1 - resolved_stop_pct)
        dollars_at_risk = risk.equity * (self.settings.risk_per_trade_pct / 100)
        per_share_risk = max(snapshot.price - stop_price, 0.01)
        quantity = int(dollars_at_risk / per_share_risk)
        max_affordable = int(risk.buying_power / snapshot.price) if snapshot.price else 0
        return max(0, min(quantity, max_affordable)), stop_price
