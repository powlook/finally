"""Database helper module for FinAlly workstation.

Provides SQLite schema initialization, data seeding, and database access functions.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
import json
from typing import Any

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "../../db/finally.db"))


def get_db_connection() -> sqlite3.Connection:
    """Establish a thread-safe connection to the SQLite database.

    Creates any missing parent directories for the database file.
    """
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize the SQLite database schema and seed default data.

    Checks if tables already exist; if not, creates them and seeds:
      1. Default user profile with $10,000 cash balance.
      2. Watchlist containing 10 default tickers.
    """
    conn = get_db_connection()
    try:
        with conn:
            # Create tables
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users_profile (
                    id TEXT PRIMARY KEY,
                    cash_balance REAL NOT NULL DEFAULT 10000.0,
                    created_at TEXT NOT NULL
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    ticker TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    UNIQUE(user_id, ticker)
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    ticker TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    avg_cost REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, ticker)
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    ticker TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    executed_at TEXT NOT NULL
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    total_value REAL NOT NULL,
                    recorded_at TEXT NOT NULL
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    actions TEXT,
                    created_at TEXT NOT NULL
                );
            """)

            # Seed default user profile
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users_profile WHERE id = 'default'")
            if cursor.fetchone()[0] == 0:
                conn.execute(
                    "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
                    ("default", 10000.0, datetime.now(timezone.utc).isoformat()),
                )

            # Seed default watchlist
            cursor.execute("SELECT COUNT(*) FROM watchlist WHERE user_id = 'default'")
            if cursor.fetchone()[0] == 0:
                default_tickers = [
                    "AAPL",
                    "GOOGL",
                    "MSFT",
                    "AMZN",
                    "TSLA",
                    "NVDA",
                    "META",
                    "JPM",
                    "V",
                    "NFLX",
                ]
                now = datetime.now(timezone.utc).isoformat()
                for ticker in default_tickers:
                    conn.execute(
                        "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
                        (str(uuid.uuid4()), "default", ticker, now),
                    )
    finally:
        conn.close()


# --- Cash Profile Functions ---

def get_cash_balance(user_id: str = "default") -> float:
    """Retrieve the cash balance for the user."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT cash_balance FROM users_profile WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            return float(row["cash_balance"])
        return 10000.0
    finally:
        conn.close()


def update_cash_balance(cash_balance: float, user_id: str = "default") -> None:
    """Update the cash balance for the user."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute(
                "UPDATE users_profile SET cash_balance = ? WHERE id = ?",
                (cash_balance, user_id),
            )
    finally:
        conn.close()


# --- Watchlist Functions ---

def get_watchlist(user_id: str = "default") -> list[str]:
    """Retrieve the list of watchlist ticker symbols for the user."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY added_at ASC", (user_id,))
        return [row["ticker"] for row in cursor.fetchall()]
    finally:
        conn.close()


def add_watchlist_ticker(ticker: str, user_id: str = "default") -> bool:
    """Add a ticker to the watchlist. Returns True if added, False if already exists."""
    ticker_upper = ticker.strip().upper()
    if not ticker_upper:
        return False
    conn = get_db_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), user_id, ticker_upper, datetime.now(timezone.utc).isoformat()),
            )
            return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def remove_watchlist_ticker(ticker: str, user_id: str = "default") -> bool:
    """Remove a ticker from the watchlist. Returns True if deleted, False otherwise."""
    ticker_upper = ticker.strip().upper()
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.execute(
                "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
                (user_id, ticker_upper),
            )
            return cursor.rowcount > 0
    finally:
        conn.close()


# --- Positions Functions ---

def get_positions(user_id: str = "default") -> list[dict[str, Any]]:
    """Retrieve the list of positions for the user."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ticker, quantity, avg_cost, updated_at FROM positions WHERE user_id = ?",
            (user_id,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def update_position(ticker: str, quantity: float, avg_cost: float, user_id: str = "default") -> None:
    """Update or insert a position. If quantity is 0 or less, the position is deleted."""
    ticker_upper = ticker.strip().upper()
    conn = get_db_connection()
    try:
        with conn:
            if quantity <= 0:
                conn.execute(
                    "DELETE FROM positions WHERE user_id = ? AND ticker = ?",
                    (user_id, ticker_upper),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, ticker) DO UPDATE SET
                        quantity = excluded.quantity,
                        avg_cost = excluded.avg_cost,
                        updated_at = excluded.updated_at
                    """,
                    (str(uuid.uuid4()), user_id, ticker_upper, quantity, avg_cost, datetime.now(timezone.utc).isoformat()),
                )
    finally:
        conn.close()


# --- Trades Functions ---

def add_trade(ticker: str, side: str, quantity: float, price: float, user_id: str = "default") -> None:
    """Log a trade in the append-only trades table."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    user_id,
                    ticker.strip().upper(),
                    side.strip().lower(),
                    quantity,
                    price,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
    finally:
        conn.close()


def get_trades(user_id: str = "default") -> list[dict[str, Any]]:
    """Retrieve the log of trades for the user, ordered by executed_at descending."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ticker, side, quantity, price, executed_at FROM trades WHERE user_id = ? ORDER BY executed_at DESC",
            (user_id,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# --- Snapshot Functions ---

def add_portfolio_snapshot(total_value: float, user_id: str = "default") -> None:
    """Log a portfolio value snapshot."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), user_id, total_value, datetime.now(timezone.utc).isoformat()),
            )
    finally:
        conn.close()


def get_portfolio_snapshots(user_id: str = "default") -> list[dict[str, Any]]:
    """Retrieve portfolio value snapshots ordered by recorded_at ascending."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT total_value, recorded_at FROM portfolio_snapshots WHERE user_id = ? ORDER BY recorded_at ASC",
            (user_id,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# --- Chat Functions ---

def get_chat_history(user_id: str = "default", limit: int = 10) -> list[dict[str, Any]]:
    """Retrieve recent chat history ordered by created_at ascending."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT role, content, actions, created_at 
            FROM chat_messages 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = cursor.fetchall()
        # Reverse to get chronological order
        result = []
        for row in reversed(rows):
            item = dict(row)
            if item["actions"]:
                try:
                    item["actions"] = json.loads(item["actions"])
                except Exception:
                    item["actions"] = None
            result.append(item)
        return result
    finally:
        conn.close()


def add_chat_message(
    role: str,
    content: str,
    actions: dict[str, Any] | None = None,
    user_id: str = "default",
) -> None:
    """Insert a chat message into the chat_messages table."""
    conn = get_db_connection()
    actions_json = json.dumps(actions) if actions is not None else None
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO chat_messages (id, user_id, role, content, actions, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), user_id, role, content, actions_json, datetime.now(timezone.utc).isoformat()),
            )
    finally:
        conn.close()
