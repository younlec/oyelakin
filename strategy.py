"""
Trading strategy module.
Implements technical indicators (RSI, Bollinger Bands, EMA) and generates
buy/sell signals. Used by both the live bot and the backtesting engine.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class StrategyFeatures:
    """Feature vector extracted from market data; shared with AI filter."""
    rsi: float = 0.0
    bb_distance_upper: float = 0.0
    bb_distance_lower: float = 0.0
    ema_trend: float = 0.0  # positive = bullish, negative = bearish
    tick_momentum: float = 0.0
    volatility: float = 0.0
    signal: Signal = Signal.HOLD

    def to_dict(self) -> dict:
        return {
            "rsi": self.rsi,
            "bb_distance_upper": self.bb_distance_upper,
            "bb_distance_lower": self.bb_distance_lower,
            "ema_trend": self.ema_trend,
            "tick_momentum": self.tick_momentum,
            "volatility": self.volatility,
            "signal": self.signal.value,
        }

    def feature_array(self) -> list[float]:
        """Numeric features for ML model input."""
        return [
            self.rsi,
            self.bb_distance_upper,
            self.bb_distance_lower,
            self.ema_trend,
            self.tick_momentum,
            self.volatility,
        ]


class TradingStrategy:
    """
    Core strategy engine using RSI + Bollinger Bands + EMA crossover.
    Maintains an internal price buffer and computes indicators on each tick.
    """

    def __init__(
        self,
        rsi_period: int | None = None,
        rsi_overbought: float | None = None,
        rsi_oversold: float | None = None,
        bb_period: int | None = None,
        bb_std_dev: float | None = None,
        ema_short: int | None = None,
        ema_long: int | None = None,
        momentum_window: int | None = None,
        volatility_window: int | None = None,
    ):
        self.rsi_period = rsi_period or config.RSI_PERIOD
        self.rsi_overbought = rsi_overbought or config.RSI_OVERBOUGHT
        self.rsi_oversold = rsi_oversold or config.RSI_OVERSOLD
        self.bb_period = bb_period or config.BB_PERIOD
        self.bb_std_dev = bb_std_dev or config.BB_STD_DEV
        self.ema_short = ema_short or config.EMA_SHORT_PERIOD
        self.ema_long = ema_long or config.EMA_LONG_PERIOD
        self.momentum_window = momentum_window or config.TICK_MOMENTUM_WINDOW
        self.volatility_window = volatility_window or config.VOLATILITY_WINDOW

        self._min_data = max(self.bb_period, self.ema_long, self.rsi_period) + 5
        self.prices: list[float] = []

    def add_tick(self, price: float) -> None:
        """Append a new price tick to the buffer."""
        self.prices.append(price)

    def add_ticks(self, prices: list[float]) -> None:
        """Append multiple price ticks."""
        self.prices.extend(prices)

    @property
    def ready(self) -> bool:
        return len(self.prices) >= self._min_data

    def compute_rsi(self, prices: np.ndarray, period: int | None = None) -> float:
        period = period or self.rsi_period
        if len(prices) < period + 1:
            return 50.0
        deltas = np.diff(prices[-(period + 1):])
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def compute_bollinger_bands(
        self, prices: np.ndarray
    ) -> tuple[float, float, float]:
        """Returns (upper, middle, lower) Bollinger Band values."""
        window = prices[-self.bb_period:]
        middle = np.mean(window)
        std = np.std(window)
        upper = middle + self.bb_std_dev * std
        lower = middle - self.bb_std_dev * std
        return upper, middle, lower

    def compute_ema(self, prices: np.ndarray, period: int) -> float:
        if len(prices) < period:
            return float(prices[-1])
        series = pd.Series(prices)
        return float(series.ewm(span=period, adjust=False).mean().iloc[-1])

    def compute_tick_momentum(self, prices: np.ndarray) -> float:
        window = prices[-self.momentum_window:]
        if len(window) < 2:
            return 0.0
        return float(window[-1] - window[0])

    def compute_volatility(self, prices: np.ndarray) -> float:
        window = prices[-self.volatility_window:]
        if len(window) < 2:
            return 0.0
        returns = np.diff(window) / window[:-1]
        return float(np.std(returns))

    def evaluate(self, price: float | None = None) -> StrategyFeatures:
        """
        Evaluate the strategy on current data.
        Optionally appends *price* before evaluation.
        Returns a StrategyFeatures with computed indicators and signal.
        """
        if price is not None:
            self.add_tick(price)

        if not self.ready:
            return StrategyFeatures(signal=Signal.HOLD)

        arr = np.array(self.prices, dtype=np.float64)

        rsi = self.compute_rsi(arr)
        upper, middle, lower = self.compute_bollinger_bands(arr)
        ema_short_val = self.compute_ema(arr, self.ema_short)
        ema_long_val = self.compute_ema(arr, self.ema_long)
        momentum = self.compute_tick_momentum(arr)
        volatility = self.compute_volatility(arr)

        current_price = arr[-1]
        bb_dist_upper = (upper - current_price) / middle if middle != 0 else 0.0
        bb_dist_lower = (current_price - lower) / middle if middle != 0 else 0.0
        ema_trend = ema_short_val - ema_long_val

        signal = self._generate_signal(
            rsi, current_price, upper, lower, ema_trend, momentum
        )

        features = StrategyFeatures(
            rsi=rsi,
            bb_distance_upper=bb_dist_upper,
            bb_distance_lower=bb_dist_lower,
            ema_trend=ema_trend,
            tick_momentum=momentum,
            volatility=volatility,
            signal=signal,
        )
        return features

    def _generate_signal(
        self,
        rsi: float,
        price: float,
        bb_upper: float,
        bb_lower: float,
        ema_trend: float,
        momentum: float,
    ) -> Signal:
        """
        Multi-factor signal generation:
        - BUY when RSI oversold + price near lower BB + bullish EMA crossover
        - SELL when RSI overbought + price near upper BB + bearish EMA crossover
        """
        buy_score = 0
        sell_score = 0

        if rsi < self.rsi_oversold:
            buy_score += 2
        elif rsi < 45:
            buy_score += 1

        if rsi > self.rsi_overbought:
            sell_score += 2
        elif rsi > 55:
            sell_score += 1

        if price <= bb_lower:
            buy_score += 2
        elif price < (bb_lower + (bb_upper - bb_lower) * 0.3):
            buy_score += 1

        if price >= bb_upper:
            sell_score += 2
        elif price > (bb_lower + (bb_upper - bb_lower) * 0.7):
            sell_score += 1

        if ema_trend > 0:
            buy_score += 1
        elif ema_trend < 0:
            sell_score += 1

        if momentum > 0:
            buy_score += 1
        elif momentum < 0:
            sell_score += 1

        if buy_score >= 4 and buy_score > sell_score:
            return Signal.BUY
        elif sell_score >= 4 and sell_score > buy_score:
            return Signal.SELL
        return Signal.HOLD

    def reset(self) -> None:
        """Clear the price buffer."""
        self.prices.clear()
