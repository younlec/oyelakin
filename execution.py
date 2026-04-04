"""
Trade execution engine.
Bridges strategy signals, risk checks, and the Deriv API connection to
place and manage trades.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

import config
from connection import DerivConnection
from strategy import Signal, StrategyFeatures, TradingStrategy
from risk import RiskManager

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    trade_id: str = ""
    contract_id: str = ""
    symbol: str = ""
    direction: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    stake: float = 0.0
    pnl: float = 0.0
    entry_time: float = 0.0
    exit_time: float = 0.0
    duration: int = 0
    status: str = "pending"
    features: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "contract_id": self.contract_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "stake": self.stake,
            "pnl": self.pnl,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "duration": self.duration,
            "status": self.status,
            "features": self.features,
        }


class ExecutionEngine:
    """
    Coordinates the end-to-end trade lifecycle:
    tick → strategy evaluation → risk check → (optional AI filter) → execution → logging.
    """

    def __init__(
        self,
        connection: DerivConnection,
        strategy: TradingStrategy,
        risk_manager: RiskManager,
        ai_filter=None,
        trade_logger=None,
        dashboard_callback=None,
    ):
        self.conn = connection
        self.strategy = strategy
        self.risk = risk_manager
        self.ai_filter = ai_filter
        self.trade_logger = trade_logger
        self.dashboard_callback = dashboard_callback

        self.active_trades: dict[str, TradeRecord] = {}
        self.trade_history: list[TradeRecord] = []
        self._trade_counter = 0
        self._running = False

    async def start(self, symbol: str | None = None) -> None:
        """Begin listening for ticks and executing the strategy."""
        symbol = symbol or config.SYMBOL
        self._running = True

        self.conn.on_tick(self._on_tick)
        self.conn.on_trade_update(self._on_trade_update)

        history = await self.conn.get_tick_history(symbol, count=200)
        prices = history.get("history", {}).get("prices", [])
        if prices:
            self.strategy.add_ticks([float(p) for p in prices])
            logger.info("Loaded %d historical ticks for warm-up", len(prices))

        await self.conn.subscribe_ticks(symbol)
        logger.info("Execution engine started for %s", symbol)

    async def stop(self) -> None:
        self._running = False
        logger.info("Execution engine stopped")

    async def _on_tick(self, tick_data: dict) -> None:
        """Process each incoming tick."""
        if not self._running:
            return

        price = float(tick_data.get("quote", 0))
        if price <= 0:
            return

        features = self.strategy.evaluate(price)

        if features.signal == Signal.HOLD:
            return

        allowed, reason = self.risk.can_trade()
        if not allowed:
            logger.debug("Trade blocked by risk: %s", reason)
            return

        if self.ai_filter is not None and config.USE_AI_FILTER:
            prediction = self.ai_filter.predict(features)
            if prediction == 0:
                logger.info("AI filter rejected signal: %s", features.signal.value)
                return

        await self._execute_trade(features, tick_data)

    async def _execute_trade(self, features: StrategyFeatures, tick_data: dict) -> None:
        """Place a trade on the Deriv platform."""
        symbol = tick_data.get("symbol", config.SYMBOL)
        direction = features.signal.value

        contract_type = "CALL" if direction == "BUY" else "PUT"
        stake = self.risk.calculate_position_size()

        if stake <= 0:
            logger.warning("Position size is zero; skipping trade")
            return

        self._trade_counter += 1
        trade_id = f"T{self._trade_counter:06d}"

        record = TradeRecord(
            trade_id=trade_id,
            symbol=symbol,
            direction=direction,
            entry_price=float(tick_data.get("quote", 0)),
            stake=stake,
            entry_time=time.time(),
            status="pending",
            features=features.to_dict(),
        )

        try:
            response = await self.conn.buy_contract(
                amount=stake,
                contract_type=contract_type,
                symbol=symbol,
                duration=config.DURATION,
                duration_unit=config.DURATION_UNIT,
            )

            if "error" in response:
                record.status = "error"
                logger.error(
                    "Trade %s failed: %s", trade_id, response["error"]["message"]
                )
                return

            buy_info = response.get("buy", {})
            record.contract_id = str(buy_info.get("contract_id", ""))
            record.stake = float(buy_info.get("buy_price", stake))
            record.status = "open"

            self.active_trades[record.contract_id] = record
            self.risk.record_trade_open()

            logger.info(
                "TRADE OPENED: %s %s %s @ %.5f (stake=%.2f)",
                trade_id,
                direction,
                symbol,
                record.entry_price,
                record.stake,
            )

            if self.dashboard_callback:
                await self._push_dashboard_update("trade_opened", record)

        except Exception as e:
            record.status = "error"
            logger.error("Trade execution error: %s", e)

    async def _on_trade_update(self, contract_data: dict) -> None:
        """Handle contract settlement / update from Deriv."""
        contract_id = str(contract_data.get("contract_id", ""))
        if contract_id not in self.active_trades:
            return

        record = self.active_trades[contract_id]
        is_sold = contract_data.get("is_sold", 0)

        if is_sold:
            sell_price = float(contract_data.get("sell_price", 0))
            buy_price = float(contract_data.get("buy_price", record.stake))
            pnl = sell_price - buy_price

            record.exit_price = float(contract_data.get("exit_tick", 0))
            record.exit_time = time.time()
            record.pnl = pnl
            record.status = "win" if pnl >= 0 else "loss"
            record.duration = int(record.exit_time - record.entry_time)

            self.risk.record_trade_close(pnl)
            self.trade_history.append(record)
            del self.active_trades[contract_id]

            if self.trade_logger:
                self.trade_logger.log_trade(record)

            logger.info(
                "TRADE CLOSED: %s %s PnL=%.2f (balance=%.2f)",
                record.trade_id,
                record.status.upper(),
                pnl,
                self.risk.state.current_balance,
            )

            if self.dashboard_callback:
                await self._push_dashboard_update("trade_closed", record)

    async def _push_dashboard_update(self, event: str, record: TradeRecord) -> None:
        """Send real-time update to the dashboard."""
        if self.dashboard_callback is None:
            return
        payload = {
            "event": event,
            "trade": record.to_dict(),
            "stats": self.risk.get_stats(),
        }
        try:
            if asyncio.iscoroutinefunction(self.dashboard_callback):
                await self.dashboard_callback(payload)
            else:
                self.dashboard_callback(payload)
        except Exception as e:
            logger.error("Dashboard push error: %s", e)

    def get_trade_history(self) -> list[dict]:
        return [t.to_dict() for t in self.trade_history]

    def get_active_trades(self) -> list[dict]:
        return [t.to_dict() for t in self.active_trades.values()]
