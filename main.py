"""
Main entry point for the Deriv Trading Bot.

Orchestrates:
  - Connection to Deriv API
  - Strategy initialization
  - Risk management
  - AI signal filtering (optional)
  - Trade execution
  - Real-time dashboard updates via WebSocket
  - Data logging for model training

Usage:
  python main.py                        # Run the trading bot only
  python main.py --with-dashboard       # Run bot + FastAPI dashboard
  python main.py --dashboard-only       # Run only the dashboard
"""

import argparse
import asyncio
import logging
import signal
import sys
import threading

import uvicorn

import config
from ai_filter import AIFilter
from api import app as fastapi_app, push_dashboard_update, set_risk_manager
from connection import DerivConnection
from execution import ExecutionEngine
from logger import TradeLogger
from risk import RiskManager
from strategy import TradingStrategy

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class TradingBot:
    """Top-level controller that wires all subsystems together."""

    def __init__(self, user_config: dict | None = None):
        self.cfg = user_config or {}
        self.connection: DerivConnection | None = None
        self.strategy: TradingStrategy | None = None
        self.risk: RiskManager | None = None
        self.execution: ExecutionEngine | None = None
        self.ai_filter: AIFilter | None = None
        self.trade_logger: TradeLogger | None = None
        self._shutdown_event = asyncio.Event()
        self._connection_failed = False

    async def start(self) -> None:
        """Initialize all subsystems and start trading."""
        logger.info("Initializing Deriv Trading Bot...")

        self.connection = DerivConnection(
            api_token=self.cfg.get("api_token", config.DERIV_API_TOKEN),
            app_id=self.cfg.get("app_id", config.DERIV_APP_ID),
        )

        self.strategy = TradingStrategy()

        self.trade_logger = TradeLogger()

        try:
            await self.connection.connect()
        except Exception as e:
            logger.error(
                "Failed to connect to Deriv API: %s. "
                "Check DERIV_APP_ID (must be a numeric app ID from api.deriv.com) "
                "and DERIV_API_TOKEN in your .env file.",
                e,
            )
            logger.info("Dashboard remains available at http://%s:%d — trading is offline", config.API_HOST, config.API_PORT)
            logger.info("Press Ctrl+C to stop")
            self._connection_failed = True
            await self._shutdown_event.wait()
            return

        balance = await self.connection.get_balance()
        self.risk = RiskManager(starting_balance=balance)
        set_risk_manager(self.risk)

        use_ai = self.cfg.get("use_ai_filter", config.USE_AI_FILTER)
        if use_ai:
            self.ai_filter = AIFilter()
            if self.ai_filter.load():
                logger.info("AI signal filter enabled")
            else:
                logger.info("AI model not found — trading without AI filter")
                self.ai_filter = None

        self.execution = ExecutionEngine(
            connection=self.connection,
            strategy=self.strategy,
            risk_manager=self.risk,
            ai_filter=self.ai_filter,
            trade_logger=self.trade_logger,
            dashboard_callback=push_dashboard_update,
        )

        symbol = self.cfg.get("symbol", config.SYMBOL)
        await self.execution.start(symbol)

        logger.info("Trading bot is live on %s", symbol)
        await self._shutdown_event.wait()

    async def stop(self) -> None:
        """Gracefully shut down all subsystems."""
        logger.info("Shutting down trading bot...")
        if self.execution:
            await self.execution.stop()
        if self.connection:
            await self.connection.disconnect()
        self._shutdown_event.set()
        logger.info("Trading bot stopped")

    def request_shutdown(self) -> None:
        self._shutdown_event.set()


def run_dashboard(host: str = None, port: int = None) -> None:
    """Start the FastAPI dashboard server in a separate thread."""
    host = host or config.API_HOST
    port = port or config.API_PORT

    def _run():
        uvicorn.run(
            fastapi_app,
            host=host,
            port=port,
            log_level="info",
            access_log=False,
        )

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    logger.info("Dashboard running at http://%s:%d", host, port)
    return thread


async def run_bot_with_dashboard(args) -> None:
    """Run the trading bot alongside the FastAPI dashboard."""
    dashboard_thread = run_dashboard(
        host=args.host if hasattr(args, "host") else None,
        port=args.port if hasattr(args, "port") else None,
    )

    bot = TradingBot()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, bot.request_shutdown)

    try:
        await bot.start()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error("Bot encountered an error: %s", e)
        logger.info("Dashboard is still running — press Ctrl+C to stop")
        try:
            await bot._shutdown_event.wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
    finally:
        await bot.stop()


def main():
    parser = argparse.ArgumentParser(description="Deriv Trading System")
    parser.add_argument("--with-dashboard", action="store_true",
                        help="Run bot with the web dashboard")
    parser.add_argument("--dashboard-only", action="store_true",
                        help="Run only the web dashboard (no trading)")
    parser.add_argument("--host", type=str, default=config.API_HOST,
                        help="Dashboard host")
    parser.add_argument("--port", type=int, default=config.API_PORT,
                        help="Dashboard port")
    args = parser.parse_args()

    if args.dashboard_only:
        logger.info("Starting dashboard-only mode")
        uvicorn.run(
            fastapi_app,
            host=args.host,
            port=args.port,
            log_level="info",
        )
    elif args.with_dashboard:
        asyncio.run(run_bot_with_dashboard(args))
    else:
        bot = TradingBot()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, bot.request_shutdown)
        try:
            loop.run_until_complete(bot.start())
        except KeyboardInterrupt:
            pass
        finally:
            loop.run_until_complete(bot.stop())
            loop.close()


if __name__ == "__main__":
    main()
