"""
Central configuration management for the Deriv Trading System.
Loads settings from environment variables and provides defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# Deriv API Configuration
DERIV_APP_ID = os.getenv("DERIV_APP_ID", "")
DERIV_API_TOKEN = os.getenv("DERIV_API_TOKEN", "")
DERIV_WS_URL = os.getenv("DERIV_WS_URL", "wss://ws.derivws.com/websockets/v3")
DERIV_ACCOUNT_TYPE = os.getenv("DERIV_ACCOUNT_TYPE", "demo")  # "demo" or "real"

# Trading Configuration
SYMBOL = os.getenv("SYMBOL", "R_100")
STAKE_AMOUNT = float(os.getenv("STAKE_AMOUNT", "1.0"))
CONTRACT_TYPE = os.getenv("CONTRACT_TYPE", "DIGITDIFF")
DURATION = int(os.getenv("DURATION", "5"))
DURATION_UNIT = os.getenv("DURATION_UNIT", "t")

# Strategy Parameters
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
RSI_OVERBOUGHT = float(os.getenv("RSI_OVERBOUGHT", "70"))
RSI_OVERSOLD = float(os.getenv("RSI_OVERSOLD", "30"))
BB_PERIOD = int(os.getenv("BB_PERIOD", "20"))
BB_STD_DEV = float(os.getenv("BB_STD_DEV", "2.0"))
EMA_SHORT_PERIOD = int(os.getenv("EMA_SHORT_PERIOD", "9"))
EMA_LONG_PERIOD = int(os.getenv("EMA_LONG_PERIOD", "21"))
TICK_MOMENTUM_WINDOW = int(os.getenv("TICK_MOMENTUM_WINDOW", "5"))
VOLATILITY_WINDOW = int(os.getenv("VOLATILITY_WINDOW", "20"))

# Risk Management
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "50.0"))
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "5"))
MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "3"))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "30"))
MAX_DRAWDOWN_PERCENT = float(os.getenv("MAX_DRAWDOWN_PERCENT", "10.0"))
RISK_PER_TRADE_PERCENT = float(os.getenv("RISK_PER_TRADE_PERCENT", "2.0"))

# Backtest Configuration
BACKTEST_SPREAD = float(os.getenv("BACKTEST_SPREAD", "0.0001"))
BACKTEST_SLIPPAGE = float(os.getenv("BACKTEST_SLIPPAGE", "0.0001"))

# AI Filter
AI_MODEL_PATH = str(BASE_DIR / os.getenv("AI_MODEL_PATH", "model.pkl"))
AI_CONFIDENCE_THRESHOLD = float(os.getenv("AI_CONFIDENCE_THRESHOLD", "0.55"))
USE_AI_FILTER = os.getenv("USE_AI_FILTER", "true").lower() == "true"

# Logging
TRADE_HISTORY_CSV = str(BASE_DIR / os.getenv("TRADE_HISTORY_CSV", "trade_history.csv"))
TRAINING_DATA_CSV = str(BASE_DIR / os.getenv("TRAINING_DATA_CSV", "training_data.csv"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Dashboard / API
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "change-me-in-production")
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'users.db'}")
DATABASE_PATH = str(BASE_DIR / "users.db")


def get_user_config(user_id: str, user_settings: dict | None = None) -> dict:
    """Build a per-user configuration dict, overlaying user-specific settings."""
    base = {
        "symbol": SYMBOL,
        "stake_amount": STAKE_AMOUNT,
        "contract_type": CONTRACT_TYPE,
        "duration": DURATION,
        "duration_unit": DURATION_UNIT,
        "max_daily_loss": MAX_DAILY_LOSS,
        "max_consecutive_losses": MAX_CONSECUTIVE_LOSSES,
        "max_open_trades": MAX_OPEN_TRADES,
        "cooldown_seconds": COOLDOWN_SECONDS,
        "max_drawdown_percent": MAX_DRAWDOWN_PERCENT,
        "risk_per_trade_percent": RISK_PER_TRADE_PERCENT,
        "use_ai_filter": USE_AI_FILTER,
    }
    if user_settings:
        base.update(user_settings)
    return base
