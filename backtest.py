"""
Backtesting Engine — simulates tick-by-tick strategy execution on historical data.

Reuses the exact same TradingStrategy and RiskManager logic as the live bot.

CLI usage:
  python backtest.py --file data.csv
  python backtest.py --file data.csv --spread 0.0002 --slippage 0.0001
  python backtest.py --file data.csv --use-ai-filter
"""

import argparse
import csv
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

import config
from strategy import TradingStrategy, Signal, StrategyFeatures
from risk import RiskManager
from ai_filter import AIFilter

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    trade_id: str = ""
    direction: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    stake: float = 0.0
    pnl: float = 0.0
    tick_index: int = 0
    features: dict = field(default_factory=dict)
    status: str = ""


@dataclass
class BacktestResult:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    net_pnl: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_percent: float = 0.0
    sharpe_ratio: float = 0.0
    total_ticks: int = 0
    starting_balance: float = 0.0
    ending_balance: float = 0.0
    trades: list = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "",
            "=" * 50,
            "       BACKTEST PERFORMANCE SUMMARY",
            "=" * 50,
            f"  Total Ticks Processed : {self.total_ticks}",
            f"  Starting Balance      : {self.starting_balance:.2f}",
            f"  Ending Balance        : {self.ending_balance:.2f}",
            f"  Net P&L               : {self.net_pnl:.2f}",
            f"  Total Trades          : {self.total_trades}",
            f"  Wins                  : {self.wins}",
            f"  Losses                : {self.losses}",
            f"  Win Rate              : {self.win_rate:.1f}%",
            f"  Max Drawdown          : {self.max_drawdown:.2f}",
            f"  Max Drawdown %        : {self.max_drawdown_percent:.2f}%",
            f"  Sharpe Ratio          : {self.sharpe_ratio:.4f}",
            "=" * 50,
        ]
        return "\n".join(lines)


class BacktestEngine:
    """
    Simulates tick-by-tick execution using the same strategy and risk logic
    as the live trading bot.
    """

    def __init__(
        self,
        spread: float | None = None,
        slippage: float | None = None,
        starting_balance: float = 10000.0,
        stake_amount: float | None = None,
        use_ai_filter: bool = False,
        ai_model_path: str | None = None,
        cooldown_ticks: int = 5,
    ):
        self.spread = spread if spread is not None else config.BACKTEST_SPREAD
        self.slippage = slippage if slippage is not None else config.BACKTEST_SLIPPAGE
        self.starting_balance = starting_balance
        self.stake = stake_amount or config.STAKE_AMOUNT
        self.cooldown_ticks = cooldown_ticks

        self.strategy = TradingStrategy()
        self.risk = RiskManager(starting_balance=starting_balance)

        # Disable time-based cooldown for backtesting — use tick-based instead
        self.risk.cooldown_seconds = 0

        self.ai_filter: AIFilter | None = None
        if use_ai_filter:
            self.ai_filter = AIFilter(model_path=ai_model_path)
            if not self.ai_filter.load():
                logger.warning("AI filter requested but model not found; proceeding without it")
                self.ai_filter = None

        self._trade_counter = 0
        self._last_trade_tick = -self.cooldown_ticks
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[float] = []

    def run(self, prices: list[float] | np.ndarray) -> BacktestResult:
        """Execute the backtest on a price series."""
        prices = np.array(prices, dtype=np.float64)
        n = len(prices)

        logger.info("Starting backtest on %d ticks (balance=%.2f)", n, self.starting_balance)

        balance = self.starting_balance
        peak_balance = balance
        max_dd = 0.0
        pnl_series = []

        for i in range(n):
            price = float(prices[i])
            features = self.strategy.evaluate(price)
            self.equity_curve.append(balance)

            if features.signal == Signal.HOLD:
                continue

            if (i - self._last_trade_tick) < self.cooldown_ticks:
                continue

            allowed, _ = self.risk.can_trade()
            if not allowed:
                continue

            if self.ai_filter is not None:
                pred = self.ai_filter.predict(features)
                if pred == 0:
                    continue

            entry_price = price + self._apply_slippage(features.signal)
            simulated_stake = min(self.stake, balance * 0.5)

            if simulated_stake <= 0:
                continue

            exit_idx = min(i + config.DURATION, n - 1)
            exit_price = float(prices[exit_idx]) + self._apply_spread(features.signal)

            if features.signal == Signal.BUY:
                pnl = (exit_price - entry_price) / entry_price * simulated_stake
            else:
                pnl = (entry_price - exit_price) / entry_price * simulated_stake

            self._trade_counter += 1
            trade = BacktestTrade(
                trade_id=f"BT{self._trade_counter:06d}",
                direction=features.signal.value,
                entry_price=entry_price,
                exit_price=exit_price,
                stake=simulated_stake,
                pnl=round(pnl, 4),
                tick_index=i,
                features=features.to_dict(),
                status="win" if pnl >= 0 else "loss",
            )
            self.trades.append(trade)
            pnl_series.append(pnl)

            balance += pnl
            self.risk.record_trade_open()
            self.risk.record_trade_close(pnl)

            if balance > peak_balance:
                peak_balance = balance
            dd = peak_balance - balance
            if dd > max_dd:
                max_dd = dd

            self._last_trade_tick = i

        wins = sum(1 for t in self.trades if t.pnl >= 0)
        losses = len(self.trades) - wins
        total = len(self.trades)
        net_pnl = sum(t.pnl for t in self.trades)

        sharpe = self._compute_sharpe(pnl_series)
        dd_pct = (max_dd / peak_balance * 100) if peak_balance > 0 else 0.0

        result = BacktestResult(
            total_trades=total,
            wins=wins,
            losses=losses,
            win_rate=(wins / total * 100) if total > 0 else 0.0,
            net_pnl=round(net_pnl, 4),
            max_drawdown=round(max_dd, 4),
            max_drawdown_percent=round(dd_pct, 2),
            sharpe_ratio=round(sharpe, 4),
            total_ticks=n,
            starting_balance=self.starting_balance,
            ending_balance=round(balance, 4),
            trades=[self._trade_to_dict(t) for t in self.trades],
        )

        return result

    def _apply_slippage(self, signal: Signal) -> float:
        if signal == Signal.BUY:
            return self.slippage
        return -self.slippage

    def _apply_spread(self, signal: Signal) -> float:
        if signal == Signal.BUY:
            return -self.spread
        return self.spread

    @staticmethod
    def _compute_sharpe(pnl_series: list[float], risk_free_rate: float = 0.0) -> float:
        if len(pnl_series) < 2:
            return 0.0
        arr = np.array(pnl_series)
        mean_return = np.mean(arr)
        std_return = np.std(arr, ddof=1)
        if std_return == 0:
            return 0.0
        return float((mean_return - risk_free_rate) / std_return)

    @staticmethod
    def _trade_to_dict(trade: BacktestTrade) -> dict:
        return {
            "trade_id": trade.trade_id,
            "direction": trade.direction,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "stake": trade.stake,
            "pnl": trade.pnl,
            "tick_index": trade.tick_index,
            "status": trade.status,
            "features": trade.features,
        }


def save_results(result: BacktestResult, output_path: str = "backtest_results.csv") -> None:
    """Write backtest trade results to CSV."""
    if not result.trades:
        logger.warning("No trades to save")
        return

    fields = ["trade_id", "direction", "entry_price", "exit_price", "stake", "pnl", "tick_index", "status"]
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for trade in result.trades:
            row = {k: trade[k] for k in fields}
            writer.writerow(row)
    logger.info("Backtest results saved to %s", output_path)


def save_training_data(result: BacktestResult, output_path: str | None = None) -> None:
    """Save feature + outcome data from backtest for AI model training."""
    from datetime import datetime

    output_path = output_path or config.TRAINING_DATA_CSV
    if not result.trades:
        return

    fields = [
        "timestamp", "trade_id", "rsi", "bb_distance_upper", "bb_distance_lower",
        "ema_trend", "tick_momentum", "volatility", "signal", "pnl", "outcome",
    ]
    file_exists = Path(output_path).exists()
    with open(output_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not file_exists:
            writer.writeheader()
        ts = datetime.utcnow().isoformat()
        for trade in result.trades:
            feat = trade.get("features", {})
            row = {
                "timestamp": ts,
                "trade_id": trade["trade_id"],
                "rsi": feat.get("rsi", 0),
                "bb_distance_upper": feat.get("bb_distance_upper", 0),
                "bb_distance_lower": feat.get("bb_distance_lower", 0),
                "ema_trend": feat.get("ema_trend", 0),
                "tick_momentum": feat.get("tick_momentum", 0),
                "volatility": feat.get("volatility", 0),
                "signal": feat.get("signal", ""),
                "pnl": trade["pnl"],
                "outcome": 1 if trade["pnl"] >= 0 else 0,
            }
            writer.writerow(row)
    logger.info("Training data appended to %s", output_path)


def load_price_data(file_path: str) -> np.ndarray:
    """
    Load price data from CSV. Supports various formats:
    - Single column of prices
    - Column named 'price', 'close', or 'quote'
    """
    df = pd.read_csv(file_path)

    for col_name in ["price", "close", "quote", "Close", "Price"]:
        if col_name in df.columns:
            return df[col_name].dropna().values.astype(np.float64)

    if df.shape[1] == 1:
        return df.iloc[:, 0].dropna().values.astype(np.float64)

    if df.shape[1] >= 4:
        return df.iloc[:, 3].dropna().values.astype(np.float64)

    raise ValueError(
        f"Cannot identify price column in {file_path}. "
        "Expected column named 'price', 'close', or 'quote'."
    )


def main():
    parser = argparse.ArgumentParser(description="Backtest the Deriv trading strategy")
    parser.add_argument("--file", type=str, required=True, help="Path to CSV with price data")
    parser.add_argument("--balance", type=float, default=10000.0, help="Starting balance")
    parser.add_argument("--stake", type=float, default=None, help="Stake per trade")
    parser.add_argument("--spread", type=float, default=None, help="Simulated spread")
    parser.add_argument("--slippage", type=float, default=None, help="Simulated slippage")
    parser.add_argument("--use-ai-filter", action="store_true", help="Use AI filter")
    parser.add_argument("--output", type=str, default="backtest_results.csv", help="Output CSV")
    parser.add_argument("--save-training", action="store_true", help="Save training data for AI")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    prices = load_price_data(args.file)
    logger.info("Loaded %d price ticks from %s", len(prices), args.file)

    engine = BacktestEngine(
        spread=args.spread,
        slippage=args.slippage,
        starting_balance=args.balance,
        stake_amount=args.stake,
        use_ai_filter=args.use_ai_filter,
    )

    result = engine.run(prices)
    print(result.summary())

    save_results(result, args.output)

    if args.save_training:
        save_training_data(result)

    return result


if __name__ == "__main__":
    main()
