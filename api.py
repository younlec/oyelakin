"""
FastAPI backend for the trading dashboard.

Endpoints:
  GET  /stats          — trading statistics
  GET  /trades         — trade history
  WS   /ws             — real-time updates
  POST /backtest       — run a backtest
  POST /users          — create a user
  GET  /health         — health check

Run:
  uvicorn api:app --reload
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Optional

import numpy as np
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    Header,
    UploadFile,
    File,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import database
from backtest import BacktestEngine, load_price_data, save_results, save_training_data
from logger import TradeLogger
from risk import RiskManager

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

database.init_db()

app = FastAPI(
    title="Deriv Trading Dashboard",
    description="Real-time trading dashboard with backtesting and AI signal filtering",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

trade_logger = TradeLogger()


class ConnectionManager:
    """Manages active WebSocket connections for real-time dashboard updates."""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        logger.info("WebSocket client connected (%d active)", len(self.active))

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)
        logger.info("WebSocket client disconnected (%d active)", len(self.active))

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_manager = ConnectionManager()

_risk_manager = RiskManager(starting_balance=10000.0)


async def push_dashboard_update(payload: dict):
    """Callback used by the execution engine to push updates."""
    await ws_manager.broadcast(payload)


def _verify_api_key(x_api_key: str = Header(default="")):
    """Simple API key verification for protected endpoints."""
    if config.DASHBOARD_API_KEY and x_api_key != config.DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/stats")
async def get_stats(_auth=Depends(_verify_api_key)):
    """Returns current trading statistics."""
    stats = _risk_manager.get_stats()
    stats["timestamp"] = datetime.utcnow().isoformat()
    return stats


# ── Trade History ─────────────────────────────────────────────────────────────

@app.get("/trades")
async def get_trades(
    limit: int = Query(default=100, ge=1, le=1000),
    _auth=Depends(_verify_api_key),
):
    """Returns trade history from CSV log."""
    trades = trade_logger.get_all_trades()
    return {"trades": trades[-limit:], "total": len(trades)}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_json({"type": "pong"})
            elif data == "stats":
                await ws.send_json({"type": "stats", "data": _risk_manager.get_stats()})
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


# ── Backtest ──────────────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    starting_balance: float = 10000.0
    stake: float = 1.0
    spread: float = 0.0001
    slippage: float = 0.0001
    use_ai_filter: bool = False


@app.post("/backtest")
async def run_backtest(
    file: UploadFile = File(...),
    starting_balance: float = 10000.0,
    stake: float = 1.0,
    spread: float = 0.0001,
    slippage: float = 0.0001,
    use_ai_filter: bool = False,
    _auth=Depends(_verify_api_key),
):
    """Run a backtest with uploaded CSV data."""
    import tempfile
    import pandas as pd

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    try:
        contents = await file.read()
        tmp.write(contents)
        tmp.close()

        prices = load_price_data(tmp.name)

        engine = BacktestEngine(
            spread=spread,
            slippage=slippage,
            starting_balance=starting_balance,
            stake_amount=stake,
            use_ai_filter=use_ai_filter,
        )
        result = engine.run(prices)

        return {
            "total_trades": result.total_trades,
            "wins": result.wins,
            "losses": result.losses,
            "win_rate": result.win_rate,
            "net_pnl": result.net_pnl,
            "max_drawdown": result.max_drawdown,
            "max_drawdown_percent": result.max_drawdown_percent,
            "sharpe_ratio": result.sharpe_ratio,
            "starting_balance": result.starting_balance,
            "ending_balance": result.ending_balance,
            "total_ticks": result.total_ticks,
            "trades": result.trades[:50],
        }
    finally:
        os.unlink(tmp.name)


# ── User Management ──────────────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    username: str
    settings: dict | None = None


@app.post("/users")
async def create_user(req: CreateUserRequest, _auth=Depends(_verify_api_key)):
    """Create a new user and return their API key."""
    try:
        user = database.create_user(req.username, req.settings)
        return user
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/users")
async def list_users(_auth=Depends(_verify_api_key)):
    return {"users": database.get_all_users()}


@app.get("/users/{user_id}/trades")
async def user_trades(user_id: int, limit: int = 100, _auth=Depends(_verify_api_key)):
    return {"trades": database.get_user_trades(user_id, limit)}


# ── Frontend Serving ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Dashboard frontend not found</h1>", status_code=404)


# ── Push helper for external use ──────────────────────────────────────────────

def get_ws_manager() -> ConnectionManager:
    return ws_manager


def get_risk_manager() -> RiskManager:
    return _risk_manager


def set_risk_manager(rm: RiskManager) -> None:
    global _risk_manager
    _risk_manager = rm
