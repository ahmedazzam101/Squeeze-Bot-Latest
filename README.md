# Short Squeeze Bot

Rule-based short squeeze scanner and Alpaca paper-trading worker.

This project is intentionally built so Claude analyzes context but does not place trades directly. The trade action is produced by:

```text
market data + squeeze scores + Claude classification + risk governor
```

The risk governor can always veto a trade.

## What It Does

- Scans a configurable ticker universe.
- Discovers market-wide movers and temporarily adds them to an opportunity queue.
- Scores structural short-squeeze pressure.
- Scores acceleration across price, volume, news, and social velocity.
- Uses Claude only for catalyst/risk classification.
- Enforces hard entry, exit, and daily risk limits.
- Places Alpaca paper orders when explicitly enabled.
- Logs scans, decisions, orders, and positions to SQLite.
- Blocks stock orders outside regular market hours to avoid stale queued fills.
- Tracks pending orders, reconciles fills, and cancels stale orders.
- Persists position metadata for restart-safe stops, peaks, and acceleration decay.
- Records completed trade outcomes with entry score, entry acceleration, exit reason, and P&L.
- Can conservatively swap a weak position into a stronger opportunity when the account is already at max positions.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m squeeze_bot.main scan-once
```

By default, the bot runs in dry-run mode.

## Railway

Set the environment variables in Railway, then deploy. `Procfile` starts the worker:

```text
worker: python -m squeeze_bot.main worker
```

## Important Environment Variables

- `WATCHLIST`: comma-separated symbols, for example `GME,AMC,CVNA,BYND`
- `DRY_RUN`: keep `true` until you are ready for paper execution
- `ENABLE_ALPACA_EXECUTION`: must be `true` before Alpaca orders are submitted
- `ALPACA_PAPER`: defaults to `true`
- `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`
- `ANTHROPIC_API_KEY`
- `FMP_API_KEY`
- `FINNHUB_API_KEY`
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`

## Safety Defaults

- 1% risk per trade
- max 2 open positions
- max 2 trades/day
- stop after 2 losses
- 3% daily loss cap
- no averaging down
- no trading when the spread/liquidity gate fails
- no regular stock orders outside market hours
- stale pending orders are cancelled after `STALE_ORDER_TTL_MINUTES`

This is not financial advice. Run paper trading and backtests before considering live use.
