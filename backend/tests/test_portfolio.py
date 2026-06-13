"""Unit tests for portfolio management and trade execution business logic."""

from __future__ import annotations

import os
import pytest

from app import db
from app.market.cache import PriceCache
from app.portfolio import execute_trade, record_portfolio_snapshot_now

TEST_DB_PATH = os.path.join(os.path.dirname(__file__), "test_finally_portfolio.db")


@pytest.fixture(autouse=True)
def setup_teardown_test_db():
    """Setup a temporary test database configuration and clean up after tests."""
    old_db_path = db.DB_PATH
    db.DB_PATH = TEST_DB_PATH

    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    db.init_db()

    yield

    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    db.DB_PATH = old_db_path


@pytest.fixture
def price_cache():
    """Create a clean PriceCache instance and populate mock stock prices."""
    cache = PriceCache()
    cache.update("AAPL", 200.00)
    cache.update("GOOGL", 150.00)
    return cache


def test_record_portfolio_snapshot(price_cache):
    """Test calculating total portfolio value and recording snapshots."""
    # Seed a position
    db.update_position("AAPL", 10.0, 190.0)  # Value: 10 * 200 = 2000. Cash: 10000. Total: 12000
    
    total_val = record_portfolio_snapshot_now(price_cache)
    assert total_val == 12000.0

    snaps = db.get_portfolio_snapshots()
    assert len(snaps) == 1
    assert snaps[0]["total_value"] == 12000.0


def test_execute_buy_order_success(price_cache):
    """Test executing a valid BUY market order."""
    result = execute_trade("AAPL", 10.0, "buy", price_cache)
    
    assert result["success"] is True
    assert result["price"] == 200.00
    assert result["error"] is None

    # Verify cash decreased: 10000 - (10 * 200) = 8000
    assert db.get_cash_balance() == 8000.0

    # Verify position exists
    positions = db.get_positions()
    assert len(positions) == 1
    assert positions[0]["ticker"] == "AAPL"
    assert positions[0]["quantity"] == 10.0
    assert positions[0]["avg_cost"] == 200.0

    # Verify trade log has 1 entry
    trades = db.get_trades()
    assert len(trades) == 1
    assert trades[0]["ticker"] == "AAPL"
    assert trades[0]["side"] == "buy"
    assert trades[0]["quantity"] == 10.0
    assert trades[0]["price"] == 200.0


def test_execute_buy_insufficient_cash(price_cache):
    """Test BUY order failing due to insufficient cash balance."""
    # Try buying 100 shares of AAPL at $200 = $20,000 (we have $10,000)
    result = execute_trade("AAPL", 100.0, "buy", price_cache)

    assert result["success"] is False
    assert "Insufficient cash" in result["error"]
    assert result["price"] == 200.00

    # Verify cash did not change
    assert db.get_cash_balance() == 10000.0
    assert len(db.get_positions()) == 0
    assert len(db.get_trades()) == 0


def test_execute_buy_adjusts_average_cost(price_cache):
    """Test that multiple BUY tranches correctly recalculate weighted average cost."""
    # First purchase: 10 shares at $200.00
    execute_trade("AAPL", 10.0, "buy", price_cache)

    # Move market price to $250.00 and purchase 10 more shares
    price_cache.update("AAPL", 250.00)
    result = execute_trade("AAPL", 10.0, "buy", price_cache)

    assert result["success"] is True
    
    # Expected cash: 10000 - 2000 - 2500 = 5500
    assert db.get_cash_balance() == 5500.0

    # Expected average cost: (10 * 200 + 10 * 250) / 20 = 225.0
    positions = db.get_positions()
    assert len(positions) == 1
    assert positions[0]["quantity"] == 20.0
    assert positions[0]["avg_cost"] == 225.0


def test_execute_sell_order_success(price_cache):
    """Test executing a valid SELL order."""
    # Establish seed position: 10 shares of GOOGL at $150
    db.update_position("GOOGL", 10.0, 150.0)

    # Sell 4 shares
    result = execute_trade("GOOGL", 4.0, "sell", price_cache)

    assert result["success"] is True
    assert result["price"] == 150.00
    assert result["error"] is None

    # Expected cash: 10000 + (4 * 150) = 10600.0
    assert db.get_cash_balance() == 10600.0

    # Average cost basis should remain the same ($150)
    positions = db.get_positions()
    assert len(positions) == 1
    assert positions[0]["quantity"] == 6.0
    assert positions[0]["avg_cost"] == 150.0

    # Verify trade log
    trades = db.get_trades()
    assert len(trades) == 1
    assert trades[0]["side"] == "sell"
    assert trades[0]["quantity"] == 4.0
    assert trades[0]["price"] == 150.0


def test_execute_sell_insufficient_shares(price_cache):
    """Test SELL order failing because user doesn't own enough shares."""
    # Try selling AAPL when we don't own any
    result = execute_trade("AAPL", 5.0, "sell", price_cache)
    assert result["success"] is False
    assert "Insufficient shares" in result["error"]

    # Seed 5 shares of GOOGL, try selling 10 shares
    db.update_position("GOOGL", 5.0, 150.0)
    result = execute_trade("GOOGL", 10.0, "sell", price_cache)
    assert result["success"] is False
    assert "Insufficient shares" in result["error"]

    # Verify cash did not change
    assert db.get_cash_balance() == 10000.0


def test_execute_sell_closes_position(price_cache):
    """Test that selling all owned shares completely deletes the position row."""
    db.update_position("AAPL", 5.0, 200.0)

    # Sell all 5 shares
    result = execute_trade("AAPL", 5.0, "sell", price_cache)
    assert result["success"] is True

    # Position row should be deleted
    assert len(db.get_positions()) == 0
    assert db.get_cash_balance() == 11000.0
