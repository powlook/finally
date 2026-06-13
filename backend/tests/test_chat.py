"""Unit tests for AI chat copilot endpoints and auto-execution flow."""

from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

from app import db
from app.market.cache import PriceCache
from app.market.simulator import SimulatorDataSource
from app.main import app

TEST_DB_PATH = os.path.join(os.path.dirname(__file__), "test_finally_chat.db")


@pytest.fixture(autouse=True)
def setup_teardown_test_db():
    """Setup a temporary test database configuration and clean up after tests."""
    old_db_path = db.DB_PATH
    db.DB_PATH = TEST_DB_PATH

    # Set mock environment variable
    old_mock_env = os.environ.get("LLM_MOCK")
    os.environ["LLM_MOCK"] = "true"

    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    db.init_db()

    yield

    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    db.DB_PATH = old_db_path
    if old_mock_env is not None:
        os.environ["LLM_MOCK"] = old_mock_env
    else:
        os.environ.pop("LLM_MOCK", None)


@pytest.fixture
def test_client():
    """Create a test client for the FastAPI app."""
    # Ensure PriceCache and Simulator are initialized for tests
    from app.main import price_cache
    price_cache.update("AAPL", 200.00)
    price_cache.update("TSLA", 150.00)
    
    with TestClient(app) as client:
        yield client


def test_chat_conversational_mock(test_client):
    """Test standard conversational chat with no parsed actions."""
    res = test_client.post("/api/chat", json={"message": "Hello there! How are you?"})
    
    assert res.status_code == 200
    data = res.json()
    assert "message" in data
    assert "assistant" in data["message"].lower() or "portfolio" in data["message"].lower()
    assert data["trades"] is None
    assert data["watchlist_changes"] is None

    # Check database logging
    history = db.get_chat_history()
    assert len(history) == 2  # user and assistant messages
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"


def test_chat_buy_action_mock(test_client):
    """Test chat mock parses a BUY request and auto-executes the trade."""
    assert db.get_cash_balance() == 10000.0
    
    res = test_client.post("/api/chat", json={"message": "Please buy 10 shares of AAPL"})
    
    assert res.status_code == 200
    data = res.json()
    assert data["trades"] is not None
    assert data["trades"][0]["ticker"] == "AAPL"
    assert data["trades"][0]["side"] == "buy"
    assert data["trades"][0]["quantity"] == 10.0

    # Verify cash decreased: 10000 - (10 * 200) = 8000
    assert db.get_cash_balance() == 8000.0

    # Verify position exists in DB
    positions = db.get_positions()
    assert len(positions) == 1
    assert positions[0]["ticker"] == "AAPL"
    assert positions[0]["quantity"] == 10.0


def test_chat_sell_action_mock(test_client):
    """Test chat mock parses a SELL request and auto-executes the trade."""
    # Seed position
    db.update_position("TSLA", 10.0, 150.0)
    assert db.get_cash_balance() == 10000.0

    res = test_client.post("/api/chat", json={"message": "sell 4 shares of TSLA"})

    assert res.status_code == 200
    data = res.json()
    assert data["trades"] is not None
    assert data["trades"][0]["ticker"] == "TSLA"
    assert data["trades"][0]["side"] == "sell"
    assert data["trades"][0]["quantity"] == 4.0

    # Verify cash increased: 10000 + (4 * 150) = 10600
    assert db.get_cash_balance() == 10600.0

    positions = db.get_positions()
    assert len(positions) == 1
    assert positions[0]["quantity"] == 6.0


def test_chat_add_watchlist_action_mock(test_client):
    """Test chat mock parses an ADD WATCHLIST request."""
    # AMD is not in default watchlist
    assert "AMD" not in db.get_watchlist()

    res = test_client.post("/api/chat", json={"message": "add AMD to my watchlist"})

    assert res.status_code == 200
    data = res.json()
    assert data["watchlist_changes"] is not None
    assert data["watchlist_changes"][0]["ticker"] == "AMD"
    assert data["watchlist_changes"][0]["action"] == "add"

    # Verify in DB
    assert "AMD" in db.get_watchlist()


def test_chat_remove_watchlist_action_mock(test_client):
    """Test chat mock parses a REMOVE WATCHLIST request."""
    assert "AAPL" in db.get_watchlist()

    res = test_client.post("/api/chat", json={"message": "remove AAPL from watchlist"})

    assert res.status_code == 200
    data = res.json()
    assert data["watchlist_changes"] is not None
    assert data["watchlist_changes"][0]["ticker"] == "AAPL"
    assert data["watchlist_changes"][0]["action"] == "remove"

    # Verify not in DB
    assert "AAPL" not in db.get_watchlist()
