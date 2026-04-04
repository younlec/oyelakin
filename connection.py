"""
Deriv WebSocket connection handler.
Manages authentication, tick subscriptions, and message routing.
"""

import asyncio
import json
import logging
from typing import Callable

import websockets

import config

logger = logging.getLogger(__name__)


class DerivConnection:
    """Manages a persistent WebSocket connection to the Deriv API."""

    def __init__(
        self,
        api_token: str | None = None,
        app_id: str | None = None,
        ws_url: str | None = None,
    ):
        self.api_token = api_token or config.DERIV_API_TOKEN
        self.app_id = app_id or config.DERIV_APP_ID
        self.ws_url = ws_url or config.DERIV_WS_URL
        self.ws = None
        self._authenticated = False
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._tick_callbacks: list[Callable] = []
        self._trade_callbacks: list[Callable] = []
        self._running = False
        self._listen_task: asyncio.Task | None = None
        self.balance: float | None = None
        self.account_info: dict | None = None

    @property
    def full_url(self) -> str:
        return f"{self.ws_url}?app_id={self.app_id}"

    def _next_req_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def connect(self) -> None:
        """Establish WebSocket connection and authenticate."""
        logger.info("Connecting to Deriv API at %s", self.full_url)
        self.ws = await websockets.connect(self.full_url, ping_interval=30)
        logger.info("WebSocket connected")
        await self._authorize()
        self._running = True
        self._listen_task = asyncio.create_task(self._listen())

    async def disconnect(self) -> None:
        """Gracefully close the connection."""
        self._running = False
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self.ws:
            await self.ws.close()
            logger.info("WebSocket disconnected")

    async def _authorize(self) -> dict:
        """Authorize with the Deriv API token."""
        if not self.api_token:
            raise ValueError("DERIV_API_TOKEN is required for authentication")
        response = await self._send({"authorize": self.api_token})
        if "error" in response:
            raise ConnectionError(f"Authorization failed: {response['error']['message']}")
        self._authenticated = True
        self.account_info = response.get("authorize", {})
        self.balance = float(self.account_info.get("balance", 0))
        logger.info(
            "Authenticated: %s (balance: %.2f %s)",
            self.account_info.get("loginid"),
            self.balance,
            self.account_info.get("currency", "USD"),
        )
        return response

    async def _send(self, payload: dict) -> dict:
        """Send a request and wait for the response."""
        if self.ws is None:
            raise ConnectionError("Not connected")
        req_id = self._next_req_id()
        payload["req_id"] = req_id
        future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future
        await self.ws.send(json.dumps(payload))
        try:
            return await asyncio.wait_for(future, timeout=30)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise TimeoutError(f"Request {req_id} timed out")

    async def send_and_wait(self, payload: dict) -> dict:
        """Public wrapper for sending requests."""
        return await self._send(payload)

    async def _listen(self) -> None:
        """Background listener that routes incoming messages."""
        try:
            async for raw_msg in self.ws:
                try:
                    msg = json.loads(raw_msg)
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON message")
                    continue

                req_id = msg.get("req_id")
                if req_id and req_id in self._pending:
                    self._pending.pop(req_id).set_result(msg)

                if "tick" in msg:
                    await self._dispatch_tick(msg["tick"])

                if "proposal_open_contract" in msg:
                    await self._dispatch_trade(msg["proposal_open_contract"])

        except websockets.ConnectionClosed:
            logger.warning("Connection closed unexpectedly")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Listener error: %s", e)

    async def _dispatch_tick(self, tick_data: dict) -> None:
        for cb in self._tick_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(tick_data)
                else:
                    cb(tick_data)
            except Exception as e:
                logger.error("Tick callback error: %s", e)

    async def _dispatch_trade(self, trade_data: dict) -> None:
        for cb in self._trade_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(trade_data)
                else:
                    cb(trade_data)
            except Exception as e:
                logger.error("Trade callback error: %s", e)

    def on_tick(self, callback: Callable) -> None:
        """Register a callback for tick data."""
        self._tick_callbacks.append(callback)

    def on_trade_update(self, callback: Callable) -> None:
        """Register a callback for trade updates."""
        self._trade_callbacks.append(callback)

    async def subscribe_ticks(self, symbol: str | None = None) -> dict:
        """Subscribe to tick stream for a symbol."""
        symbol = symbol or config.SYMBOL
        response = await self._send({"ticks": symbol, "subscribe": 1})
        if "error" in response:
            raise RuntimeError(f"Tick subscription failed: {response['error']['message']}")
        logger.info("Subscribed to ticks for %s", symbol)
        return response

    async def get_balance(self) -> float:
        """Fetch current account balance."""
        response = await self._send({"balance": 1})
        if "error" in response:
            raise RuntimeError(f"Balance fetch failed: {response['error']['message']}")
        self.balance = float(response.get("balance", {}).get("balance", 0))
        return self.balance

    async def buy_contract(
        self,
        amount: float,
        contract_type: str,
        symbol: str,
        duration: int,
        duration_unit: str,
        barrier: str | None = None,
    ) -> dict:
        """Purchase a contract on the Deriv platform."""
        proposal = {
            "buy": 1,
            "price": amount,
            "parameters": {
                "amount": amount,
                "basis": "stake",
                "contract_type": contract_type,
                "currency": self.account_info.get("currency", "USD") if self.account_info else "USD",
                "duration": duration,
                "duration_unit": duration_unit,
                "symbol": symbol,
            },
        }
        if barrier is not None:
            proposal["parameters"]["barrier"] = barrier

        response = await self._send(proposal)
        if "error" in response:
            logger.error("Buy failed: %s", response["error"]["message"])
        else:
            buy_info = response.get("buy", {})
            logger.info(
                "Contract purchased: ID=%s, price=%.2f",
                buy_info.get("contract_id"),
                buy_info.get("buy_price", 0),
            )
        return response

    async def get_tick_history(
        self, symbol: str | None = None, count: int = 100, style: str = "ticks"
    ) -> dict:
        """Fetch historical tick data."""
        symbol = symbol or config.SYMBOL
        payload = {
            "ticks_history": symbol,
            "count": count,
            "end": "latest",
            "style": style,
        }
        response = await self._send(payload)
        if "error" in response:
            raise RuntimeError(f"History fetch failed: {response['error']['message']}")
        return response
