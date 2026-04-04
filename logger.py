"""
Enhanced logging module.
Logs trade history to CSV and collects feature data for AI model training.
"""

import csv
import logging
import os
from datetime import datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)

TRADE_HISTORY_FIELDS = [
    "timestamp",
    "trade_id",
    "contract_id",
    "symbol",
    "direction",
    "entry_price",
    "exit_price",
    "stake",
    "pnl",
    "duration",
    "status",
]

TRAINING_DATA_FIELDS = [
    "timestamp",
    "trade_id",
    "rsi",
    "bb_distance_upper",
    "bb_distance_lower",
    "ema_trend",
    "tick_momentum",
    "volatility",
    "signal",
    "pnl",
    "outcome",  # 1 = profitable, 0 = losing
]


class TradeLogger:
    """Persists trade data and feature vectors to CSV files."""

    def __init__(
        self,
        trade_csv_path: str | None = None,
        training_csv_path: str | None = None,
    ):
        self.trade_csv = trade_csv_path or config.TRADE_HISTORY_CSV
        self.training_csv = training_csv_path or config.TRAINING_DATA_CSV
        self._ensure_csv(self.trade_csv, TRADE_HISTORY_FIELDS)
        self._ensure_csv(self.training_csv, TRAINING_DATA_FIELDS)

    def _ensure_csv(self, path: str, fields: list[str]) -> None:
        """Create the CSV file with headers if it doesn't exist."""
        if not os.path.exists(path):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
            logger.info("Created CSV: %s", path)

    def log_trade(self, record) -> None:
        """Write a completed trade to both trade history and training data."""
        ts = datetime.utcnow().isoformat()

        trade_row = {
            "timestamp": ts,
            "trade_id": record.trade_id,
            "contract_id": record.contract_id,
            "symbol": record.symbol,
            "direction": record.direction,
            "entry_price": record.entry_price,
            "exit_price": record.exit_price,
            "stake": record.stake,
            "pnl": round(record.pnl, 4),
            "duration": record.duration,
            "status": record.status,
        }
        self._append_row(self.trade_csv, trade_row, TRADE_HISTORY_FIELDS)

        features = record.features if isinstance(record.features, dict) else {}
        training_row = {
            "timestamp": ts,
            "trade_id": record.trade_id,
            "rsi": features.get("rsi", 0),
            "bb_distance_upper": features.get("bb_distance_upper", 0),
            "bb_distance_lower": features.get("bb_distance_lower", 0),
            "ema_trend": features.get("ema_trend", 0),
            "tick_momentum": features.get("tick_momentum", 0),
            "volatility": features.get("volatility", 0),
            "signal": features.get("signal", ""),
            "pnl": round(record.pnl, 4),
            "outcome": 1 if record.pnl >= 0 else 0,
        }
        self._append_row(self.training_csv, training_row, TRAINING_DATA_FIELDS)

        logger.debug("Logged trade %s to CSV", record.trade_id)

    def _append_row(self, path: str, row: dict, fields: list[str]) -> None:
        try:
            with open(path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writerow(row)
        except Exception as e:
            logger.error("Failed to write to %s: %s", path, e)

    def get_all_trades(self) -> list[dict]:
        """Read all trades from the trade history CSV."""
        trades = []
        try:
            with open(self.trade_csv, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    trades.append(row)
        except FileNotFoundError:
            pass
        return trades

    def get_training_data(self) -> list[dict]:
        """Read all training data rows."""
        rows = []
        try:
            with open(self.training_csv, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
        except FileNotFoundError:
            pass
        return rows
