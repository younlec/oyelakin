# Deriv Trading System

A production-grade automated trading system for the Deriv platform with backtesting, AI signal filtering, and a real-time web dashboard.

## Architecture

```
/project
  ├── main.py               # Bot entry point (trading + dashboard)
  ├── connection.py          # Deriv WebSocket connection handler
  ├── strategy.py            # RSI + Bollinger Bands + EMA strategy
  ├── execution.py           # Trade execution engine
  ├── risk.py                # Risk management (drawdown, loss limits)
  ├── logger.py              # Trade logging + feature data collection
  ├── ai_filter.py           # ML-based signal filter (RandomForest)
  ├── backtest.py            # Tick-by-tick backtesting engine
  ├── api.py                 # FastAPI backend (REST + WebSocket)
  ├── database.py            # SQLite user management
  ├── config.py              # Central configuration (.env-based)
  ├── generate_sample_data.py # Synthetic data generator
  ├── requirements.txt       # Python dependencies
  ├── .env.example           # Environment variable template
  └── frontend/
      ├── index.html         # Dashboard UI
      ├── style.css          # Dark-theme styles
      └── app.js             # Real-time chart + table updates
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your Deriv API credentials
```

### 3. Run the Dashboard (no trading)

```bash
python main.py --dashboard-only
# → http://localhost:8000
```

### 4. Run the Trading Bot with Dashboard

```bash
python main.py --with-dashboard
```

### 5. Run the Trading Bot Only

```bash
python main.py
```

## Backtesting

Run a backtest on historical tick data:

```bash
# Generate sample data
python generate_sample_data.py --ticks 10000 --output data.csv

# Run backtest
python backtest.py --file data.csv --balance 10000

# Save training data for AI model
python backtest.py --file data.csv --save-training

# Backtest with AI filter enabled
python backtest.py --file data.csv --use-ai-filter
```

The backtest engine uses the **exact same** `TradingStrategy` and `RiskManager` logic as the live bot, with configurable spread and slippage simulation.

### Output

- Performance summary printed to terminal
- Trade results saved to `backtest_results.csv`
- Training data appended to `training_data.csv` (with `--save-training`)

## AI Signal Filter

Train a RandomForest classifier from backtest trade data to filter out low-quality signals:

```bash
# Train from backtest results
python ai_filter.py --train

# Train from custom data
python ai_filter.py --train --file custom_training.csv

# Use logistic regression instead
python ai_filter.py --train --model-type logistic_regression
```

### Features used for prediction:
- RSI value
- Distance from Bollinger Bands (upper and lower)
- EMA trend direction (short - long EMA)
- Tick momentum (last 5 ticks)
- Volatility (std of recent returns)

The model is saved as `model.pkl` and automatically loaded during live trading when `USE_AI_FILTER=true`.

## Web Dashboard

The dashboard provides real-time visibility into trading activity:

- **Live balance, P&L, win rate** — auto-updating via WebSocket
- **Equity curve chart** — tracks balance over time
- **Win/loss distribution** — doughnut chart
- **Trade history table** — scrollable with color-coded P&L
- **Risk status panel** — drawdown, consecutive losses, halt status
- **Backtest runner** — upload CSV and run backtests from the browser

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/stats` | GET | Current trading statistics |
| `/trades` | GET | Trade history |
| `/backtest` | POST | Run backtest (upload CSV) |
| `/users` | POST | Create new user |
| `/users` | GET | List all users |
| `/ws` | WS | Real-time updates |

Protect endpoints with `DASHBOARD_API_KEY` in `.env`.

## Multi-User Support (SaaS)

The system supports multiple users with independent configurations:

```python
# Each user gets:
# - Unique API key for dashboard access
# - Per-user Deriv API token
# - Custom trading settings (symbol, stake, risk params)
# - Isolated trade history in SQLite
```

Create users via the API:

```bash
curl -X POST http://localhost:8000/users \
  -H "Content-Type: application/json" \
  -d '{"username": "trader1", "settings": {"symbol": "R_50"}}'
```

## Configuration

All settings are configurable via environment variables (see `.env.example`):

| Category | Variables |
|----------|-----------|
| **Deriv API** | `DERIV_APP_ID`, `DERIV_API_TOKEN`, `DERIV_ACCOUNT_TYPE` |
| **Trading** | `SYMBOL`, `STAKE_AMOUNT`, `DURATION` |
| **Strategy** | `RSI_PERIOD`, `BB_PERIOD`, `EMA_SHORT_PERIOD`, `EMA_LONG_PERIOD` |
| **Risk** | `MAX_DAILY_LOSS`, `MAX_CONSECUTIVE_LOSSES`, `MAX_DRAWDOWN_PERCENT` |
| **AI** | `USE_AI_FILTER`, `AI_CONFIDENCE_THRESHOLD` |
| **Dashboard** | `API_PORT`, `DASHBOARD_API_KEY` |

## Security

- API tokens stored in `.env` (never committed to git)
- Dashboard protected with API key header (`X-Api-Key`)
- User API keys hashed with SHA-256 in the database
- Frontend never exposes sensitive tokens
- Deriv tokens stored per-user (encrypt in production)
