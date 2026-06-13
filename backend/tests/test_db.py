"""Unit tests for SQLite database helper functions."""

from __future__ import annotations

import os
import sqlite3
import pytest

from app import db

TEST_DB_PATH = os.path.join(os.path.dirname(__file__), "test_finally.db")


@pytest.fixture(autouse=True)
def setup_teardown_test_db():
    """Setup a temporary test database configuration and clean up after tests."""
    # Override database path
    old_db_path = db.DB_PATH
    db.DB_PATH = TEST_DB_PATH

    # Ensure clean slate
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    # Initialize schema
    db.init_db()

    yield

    # Clean up file
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    db.DB_PATH = old_db_path


def test_init_db_and_seeding():
    """Verify tables are created and default data is seeded on init."""
    conn = sqlite3.connect(TEST_DB_PATH)
    cursor = conn.cursor()

    # Verify tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    assert "users_profile" in tables
    assert "watchlist" in tables
    assert "positions" in tables
    assert "trades" in tables
    assert "portfolio_snapshots" in tables
    assert "chat_messages" in tables

    # Verify default seeded cash
    cursor.execute("SELECT cash_balance FROM users_profile WHERE id='default'")
    assert cursor.fetchone()[0] == 10000.0

    # Verify seeded watchlist tickers (10 default tickers)
    cursor.execute("SELECT ticker FROM watchlist WHERE user_id='default'")
    tickers = [row[0] for row in cursor.fetchall()]
    assert len(tickers) == 10
    assert "AAPL" in tickers
    assert "TSLA" in tickers
    conn.close()


def test_cash_balance_crud():
    """Test retrieving and updating user cash balance."""
    assert db.get_cash_balance() == 10000.0
    db.update_cash_balance(5432.10)
    assert db.get_cash_balance() == 5432.10


def test_watchlist_crud():
    """Test adding, listing, and removing items in the watchlist."""
    watchlist = db.get_watchlist()
    assert "AAPL" in watchlist
    assert "GOOGL" in watchlist

    # Add new ticker
    assert db.add_watchlist_ticker("MSFT") is False  # Already exists due to seeding
    assert db.add_watchlist_ticker("NVDA") is False  # Already exists due to seeding
    assert db.add_watchlist_ticker("BTC") is True
    assert "BTC" in db.get_watchlist()

    # Duplicate add
    assert db.add_watchlist_ticker("BTC") is False

    # Remove ticker
    assert db.remove_watchlist_ticker("BTC") is True
    assert "BTC" not in db.get_watchlist()
    assert db.remove_watchlist_ticker("NONEXISTENT") is False


def test_positions_crud():
    """Test positions upsert, list, and delete (when quantity is zero)."""
    assert len(db.get_positions()) == 0

    # Insert position
    db.update_position("AAPL", 10.0, 150.0)
    positions = db.get_positions()
    assert len(positions) == 1
    assert positions[0]["ticker"] == "AAPL"
    assert positions[0]["quantity"] == 10.0
    assert positions[0]["avg_cost"] == 150.0

    # Update position (average cost adjustments, etc.)
    db.update_position("AAPL", 25.0, 160.0)
    positions = db.get_positions()
    assert len(positions) == 1
    assert positions[0]["quantity"] == 25.0
    assert positions[0]["avg_cost"] == 160.0

    # Delete position by setting quantity to 0
    db.update_position("AAPL", 0.0, 160.0)
    assert len(db.get_positions()) == 0


def test_trades_log():
    """Test append-only trade logs."""
    assert len(db.get_trades()) == 0

    db.add_trade("AAPL", "buy", 5.0, 180.0)
    db.add_trade("GOOGL", "sell", 10.0, 175.5)

    trades = db.get_trades()
    assert len(trades) == 2
    assert trades[0]["ticker"] == "GOOGL"
    assert trades[0]["side"] == "sell"
    assert trades[0]["quantity"] == 10.0
    assert trades[0]["price"] == 175.5

    assert trades[1]["ticker"] == "AAPL"
    assert trades[1]["side"] == "buy"
    assert trades[1]["quantity"] == 5.0
    assert trades[1]["price"] == 180.0


def test_snapshots():
    """Test snapshot logging and listing."""
    assert len(db.get_portfolio_snapshots()) == 0

    db.add_portfolio_snapshot(10050.0)
    db.add_portfolio_snapshot(10200.5)

    snaps = db.get_portfolio_snapshots()
    assert len(snaps) == 2
    assert snaps[0]["total_value"] == 10050.0
    assert snaps[1]["total_value"] == 10200.5


def test_chat_messages_history():
    """Test logging messages and retrieving conversation history."""
    assert len(db.get_chat_history()) == 0

    db.add_chat_message("user", "Hello there")
    db.add_chat_message("assistant", "Hi! I am FinAlly.", {"trades": [{"ticker": "AAPL", "side": "buy"}]})

    history = db.get_chat_history(limit=5)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Hello there"
    assert history[0]["actions"] is None

    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "Hi! I am FinAlly."
    assert history[1]["actions"]["trades"][0]["ticker"] == "AAPL"
