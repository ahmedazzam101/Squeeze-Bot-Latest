from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BacktestMetrics:
    trades: int
    wins: int
    losses: int
    total_return_pct: float
    max_drawdown_pct: float

    @property
    def win_rate_pct(self) -> float:
        return (self.wins / self.trades * 100) if self.trades else 0.0
