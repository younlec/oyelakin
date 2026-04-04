"""
SQLite database layer for multi-user support.
Manages user accounts, API keys, and per-user configuration.
"""

import hashlib
import json
import logging
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime

import config

logger = logging.getLogger(__name__)


def _get_db_path() -> str:
    return config.DATABASE_PATH


def init_db() -> None:
    """Create tables if they don't exist."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                api_key_hash TEXT NOT NULL,
                api_key_prefix TEXT NOT NULL,
                deriv_token_encrypted TEXT DEFAULT '',
                settings TEXT DEFAULT '{}',
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trade_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                trade_id TEXT NOT NULL,
                symbol TEXT,
                direction TEXT,
                entry_price REAL,
                exit_price REAL,
                stake REAL,
                pnl REAL,
                status TEXT,
                features TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE INDEX IF NOT EXISTS idx_trade_log_user ON trade_log(user_id);
            CREATE INDEX IF NOT EXISTS idx_trade_log_created ON trade_log(created_at);
        """)
    logger.info("Database initialized at %s", _get_db_path())


@contextmanager
def _connect():
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def create_user(username: str, settings: dict | None = None) -> dict:
    """Create a user and return their API key (shown only once)."""
    api_key = secrets.token_urlsafe(32)
    key_hash = _hash_key(api_key)
    key_prefix = api_key[:8]
    now = datetime.utcnow().isoformat()
    settings_json = json.dumps(settings or {})

    with _connect() as conn:
        conn.execute(
            """INSERT INTO users (username, api_key_hash, api_key_prefix, settings, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (username, key_hash, key_prefix, settings_json, now, now),
        )
        user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    logger.info("User created: %s (id=%d)", username, user_id)
    return {"user_id": user_id, "username": username, "api_key": api_key}


def authenticate(api_key: str) -> dict | None:
    """Validate an API key and return user info, or None."""
    key_hash = _hash_key(api_key)
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, username, settings, is_active FROM users WHERE api_key_hash = ?",
            (key_hash,),
        ).fetchone()
    if row is None or not row["is_active"]:
        return None
    return {
        "user_id": row["id"],
        "username": row["username"],
        "settings": json.loads(row["settings"]),
    }


def get_user(user_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, username, settings, is_active, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "user_id": row["id"],
        "username": row["username"],
        "settings": json.loads(row["settings"]),
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }


def update_user_settings(user_id: int, settings: dict) -> None:
    now = datetime.utcnow().isoformat()
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET settings = ?, updated_at = ? WHERE id = ?",
            (json.dumps(settings), now, user_id),
        )


def store_deriv_token(user_id: int, token: str) -> None:
    """Store a Deriv API token (in production, encrypt this)."""
    now = datetime.utcnow().isoformat()
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET deriv_token_encrypted = ?, updated_at = ? WHERE id = ?",
            (token, now, user_id),
        )


def get_deriv_token(user_id: int) -> str:
    with _connect() as conn:
        row = conn.execute(
            "SELECT deriv_token_encrypted FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return row["deriv_token_encrypted"] if row else ""


def log_trade_to_db(user_id: int, trade: dict) -> None:
    now = datetime.utcnow().isoformat()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO trade_log
               (user_id, trade_id, symbol, direction, entry_price, exit_price, stake, pnl, status, features, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                trade.get("trade_id", ""),
                trade.get("symbol", ""),
                trade.get("direction", ""),
                trade.get("entry_price", 0),
                trade.get("exit_price", 0),
                trade.get("stake", 0),
                trade.get("pnl", 0),
                trade.get("status", ""),
                json.dumps(trade.get("features", {})),
                now,
            ),
        )


def get_user_trades(user_id: int, limit: int = 100) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM trade_log WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_users() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, username, api_key_prefix, is_active, created_at FROM users"
        ).fetchall()
    return [dict(r) for r in rows]
