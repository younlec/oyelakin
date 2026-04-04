"""
Risk management module.
Enforces position-sizing, drawdown limits, loss streaks, and cooldown periods.
"""

import logging
import time
from dataclasses import dataclass, field

import config

logger = logging.getLogger(__name__)


@dataclass
class RiskState:
    """Tracks running risk metrics for a single trading session."""
    starting_balance: float = 0.0
    current_balance: float = 0.0
    peak_balance: float = 0.0
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    open_trades: int = 0
    last_trade_time: float = 0.0
    total_trades: int = 0
    total_wins: int = 0
    total_losses: int = 0
    halted: bool = False
    halt_reason: str = ""


class RiskManager:
    """Enforces risk rules before each trade and updates state after each outcome."""

    def __init__(
        self,
        starting_balance: float = 0.0,
        max_daily_loss: float | None = None,
        max_consecutive_losses: int | None = None,
        max_open_trades: int | None = None,
        cooldown_seconds: int | None = None,
        max_drawdown_percent: float | None = None,
        risk_per_trade_percent: float | None = None,
    ):
        self.max_daily_loss = max_daily_loss or config.MAX_DAILY_LOSS
        self.max_consecutive_losses = max_consecutive_losses or config.MAX_CONSECUTIVE_LOSSES
        self.max_open_trades = max_open_trades or config.MAX_OPEN_TRADES
        self.cooldown_seconds = cooldown_seconds or config.COOLDOWN_SECONDS
        self.max_drawdown_percent = max_drawdown_percent or config.MAX_DRAWDOWN_PERCENT
        self.risk_per_trade = risk_per_trade_percent or config.RISK_PER_TRADE_PERCENT

        self.state = RiskState(
            starting_balance=starting_balance,
            current_balance=starting_balance,
            peak_balance=starting_balance,
        )

    def can_trade(self) -> tuple[bool, str]:
        """Check all risk rules. Returns (allowed, reason)."""
        if self.state.halted:
            return False, f"Trading halted: {self.state.halt_reason}"

        if abs(self.state.daily_pnl) >= self.max_daily_loss and self.state.daily_pnl < 0:
            self._halt(f"Daily loss limit reached: {self.state.daily_pnl:.2f}")
            return False, self.state.halt_reason

        if self.state.consecutive_losses >= self.max_consecutive_losses:
            self._halt(
                f"Max consecutive losses reached: {self.state.consecutive_losses}"
            )
            return False, self.state.halt_reason

        drawdown = self._current_drawdown_percent()
        if drawdown >= self.max_drawdown_percent:
            self._halt(f"Max drawdown reached: {drawdown:.2f}%")
            return False, self.state.halt_reason

        if self.state.open_trades >= self.max_open_trades:
            return False, f"Max open trades reached: {self.state.open_trades}"

        elapsed = time.time() - self.state.last_trade_time
        if elapsed < self.cooldown_seconds:
            remaining = self.cooldown_seconds - elapsed
            return False, f"Cooldown active: {remaining:.0f}s remaining"

        return True, "OK"

    def calculate_position_size(self, balance: float | None = None) -> float:
        """Compute stake amount based on risk-per-trade percentage."""
        bal = balance or self.state.current_balance
        if bal <= 0:
            return 0.0
        size = bal * (self.risk_per_trade / 100.0)
        return round(max(size, config.STAKE_AMOUNT), 2)

    def record_trade_open(self) -> None:
        self.state.open_trades += 1
        self.state.last_trade_time = time.time()
        self.state.total_trades += 1

    def record_trade_close(self, pnl: float) -> None:
        """Update risk state after a trade closes."""
        self.state.open_trades = max(0, self.state.open_trades - 1)
        self.state.daily_pnl += pnl
        self.state.current_balance += pnl

        if pnl >= 0:
            self.state.total_wins += 1
            self.state.consecutive_losses = 0
        else:
            self.state.total_losses += 1
            self.state.consecutive_losses += 1

        if self.state.current_balance > self.state.peak_balance:
            self.state.peak_balance = self.state.current_balance

        logger.info(
            "Trade closed PnL=%.2f | Daily PnL=%.2f | Balance=%.2f | DD=%.2f%%",
            pnl,
            self.state.daily_pnl,
            self.state.current_balance,
            self._current_drawdown_percent(),
        )

    def _current_drawdown_percent(self) -> float:
        if self.state.peak_balance <= 0:
            return 0.0
        dd = (self.state.peak_balance - self.state.current_balance) / self.state.peak_balance * 100
        return max(dd, 0.0)

    def _halt(self, reason: str) -> None:
        self.state.halted = True
        self.state.halt_reason = reason
        logger.warning("RISK HALT: %s", reason)

    def reset_daily(self) -> None:
        """Call at the start of each trading day."""
        self.state.daily_pnl = 0.0
        self.state.consecutive_losses = 0
        self.state.halted = False
        self.state.halt_reason = ""
        logger.info("Daily risk counters reset")

    def get_stats(self) -> dict:
        total = self.state.total_trades
        return {
            "total_trades": total,
            "wins": self.state.total_wins,
            "losses": self.state.total_losses,
            "win_rate": (self.state.total_wins / total * 100) if total > 0 else 0.0,
            "daily_pnl": round(self.state.daily_pnl, 2),
            "balance": round(self.state.current_balance, 2),
            "peak_balance": round(self.state.peak_balance, 2),
            "drawdown_percent": round(self._current_drawdown_percent(), 2),
            "consecutive_losses": self.state.consecutive_losses,
            "open_trades": self.state.open_trades,
            "halted": self.state.halted,
            "halt_reason": self.state.halt_reason,
        }
