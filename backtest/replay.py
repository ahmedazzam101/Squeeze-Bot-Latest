from __future__ import annotations

import csv
from pathlib import Path

from squeeze_bot.backtest.metrics import BacktestMetrics


def replay_trades(csv_path: str | Path, entry_score: float = 70, stop_loss_pct: float = 7, trailing_pct: float = 10) -> BacktestMetrics:
    """Replay a simple scored historical file.

    Expected CSV columns:
    symbol,timestamp,close,composite_score,acceleration_score,acceleration_rising

    This is intentionally small: it validates thresholds and exit behavior before
    connecting the full data stack.
    """
    rows = list(csv.DictReader(Path(csv_path).open(newline="")))
    cash = 10_000.0
    equity_peak = cash
    max_drawdown = 0.0
    position: dict | None = None
    trades = wins = losses = 0

    for row in rows:
        price = float(row["close"])
        score = float(row["composite_score"])
        acceleration = float(row["acceleration_score"])
        rising = str(row["acceleration_rising"]).lower() in {"1", "true", "yes"}

        if position is None and score >= entry_score and rising:
            position = {"entry": price, "highest": price, "shares": cash / price, "last_accel": acceleration}
            trades += 1
            continue

        if position is not None:
            position["highest"] = max(position["highest"], price)
            stop = position["entry"] * (1 - stop_loss_pct / 100)
            trail = position["highest"] * (1 - trailing_pct / 100)
            accel_decay = acceleration < position["last_accel"]
            position["last_accel"] = acceleration
            if price <= stop or price <= trail or accel_decay:
                pnl = (price - position["entry"]) / position["entry"] * 100
                cash *= 1 + pnl / 100
                wins += int(pnl > 0)
                losses += int(pnl <= 0)
                position = None
                equity_peak = max(equity_peak, cash)
                drawdown = ((equity_peak - cash) / equity_peak * 100) if equity_peak else 0
                max_drawdown = max(max_drawdown, drawdown)

    total_return = ((cash - 10_000) / 10_000) * 100
    return BacktestMetrics(trades=trades, wins=wins, losses=losses, total_return_pct=total_return, max_drawdown_pct=max_drawdown)
