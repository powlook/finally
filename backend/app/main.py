"""Main FastAPI application entrypoint for FinAlly workstation.

Configures API endpoints, lifespan database/market startup, and static file serving.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import db
from app.market.cache import PriceCache
from app.market.factory import create_market_data_source
from app.market.stream import create_stream_router
from app.chat import create_chat_router
from app.portfolio import execute_trade, record_portfolio_snapshot_now

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Singletons for the runtime lifecycle
price_cache = PriceCache()
market_source = create_market_data_source(price_cache)

snapshot_task: asyncio.Task | None = None


async def _run_periodic_snapshots() -> None:
    """Background loop that records a portfolio value snapshot every 30 seconds."""
    # Record initial snapshot
    try:
        record_portfolio_snapshot_now(price_cache)
    except Exception as e:
        logger.error(f"Error recording initial snapshot: {e}")

    while True:
        try:
            await asyncio.sleep(30)
            record_portfolio_snapshot_now(price_cache)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in background portfolio snapshot task: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for database initialization, market stream startup, and background tasks."""
    global snapshot_task

    # 1. Initialize SQLite database & Seed default values
    logger.info("Initializing SQLite database schema...")
    db.init_db()

    # 2. Retrieve watchlist and start the live price feed
    watchlist_tickers = db.get_watchlist()
    logger.info(f"Starting market data source with tickers: {watchlist_tickers}")
    await market_source.start(watchlist_tickers)

    # 3. Start portfolio snapshotting task
    snapshot_task = asyncio.create_task(_run_periodic_snapshots())

    yield

    # Clean up background resources on shutdown
    logger.info("Stopping background tasks and data sources...")
    if snapshot_task:
        snapshot_task.cancel()
        try:
            await snapshot_task
        except asyncio.CancelledError:
            pass

    await market_source.stop()
    logger.info("Cleanup complete.")


app = FastAPI(title="FinAlly API", lifespan=lifespan)

# Setup CORS for development (Next.js typically runs on a different port during dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Wire up routers
stream_router = create_stream_router(price_cache)
chat_router = create_chat_router(price_cache, market_source)

app.include_router(stream_router)
app.include_router(chat_router)


# --- Request/Response Schemas ---

class TradeRequest(BaseModel):
    ticker: str = Field(..., json_schema_extra={"example": "AAPL"})
    quantity: float = Field(..., gt=0, json_schema_extra={"example": 5.0})
    side: str = Field(..., pattern="^(buy|sell)$", json_schema_extra={"example": "buy"})


class WatchlistRequest(BaseModel):
    ticker: str = Field(..., json_schema_extra={"example": "AAPL"})


# --- Portfolio Endpoints ---

@app.get("/api/portfolio")
def get_portfolio() -> dict[str, Any]:
    """Retrieve user portfolio valuations, holdings list, cash, and aggregate P&L."""
    user_id = "default"
    cash = db.get_cash_balance(user_id)
    raw_positions = db.get_positions(user_id)

    positions = []
    positions_value = 0.0
    total_cost = 0.0

    for pos in raw_positions:
        ticker = pos["ticker"]
        qty = pos["quantity"]
        avg_cost = pos["avg_cost"]
        
        # Calculate current valuation details
        curr_price = price_cache.get_price(ticker)
        if curr_price is None:
            curr_price = avg_cost  # Fallback
            
        value = qty * curr_price
        cost_basis = qty * avg_cost
        
        unrealized_pnl = value - cost_basis
        change_pct = (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0.0

        positions_value += value
        total_cost += cost_basis

        positions.append({
            "ticker": ticker,
            "quantity": qty,
            "avg_cost": avg_cost,
            "current_price": curr_price,
            "value": value,
            "unrealized_pnl": unrealized_pnl,
            "change_percent": change_pct,
            "updated_at": pos["updated_at"],
        })

    total_value = cash + positions_value
    total_pnl = total_value - 10000.0  # Seed portfolio was $10,000

    return {
        "cash_balance": cash,
        "positions": positions,
        "total_value": total_value,
        "positions_value": positions_value,
        "total_unrealized_pnl": positions_value - total_cost,
        "total_pnl": total_pnl,
    }


@app.post("/api/portfolio/trade")
def post_trade(payload: TradeRequest) -> dict[str, Any]:
    """Manually execute a market order (buy/sell)."""
    result = execute_trade(
        ticker=payload.ticker,
        quantity=payload.quantity,
        side=payload.side,
        price_cache=price_cache,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/api/portfolio/history")
def get_portfolio_history() -> list[dict[str, Any]]:
    """Retrieve historical portfolio value snapshots for tracking performance."""
    return db.get_portfolio_snapshots()


# --- Watchlist Endpoints ---

@app.get("/api/watchlist")
def get_watchlist_prices() -> list[dict[str, Any]]:
    """Retrieve watchlist tickers along with their current live prices and stats."""
    tickers = db.get_watchlist()
    result = []
    for ticker in tickers:
        update = price_cache.get(ticker)
        if update:
            result.append(update.to_dict())
        else:
            result.append({
                "ticker": ticker,
                "price": None,
                "previous_price": None,
                "timestamp": None,
                "change": 0.0,
                "change_percent": 0.0,
                "direction": "flat",
            })
    return result


@app.post("/api/watchlist")
async def post_watchlist(payload: WatchlistRequest) -> dict[str, Any]:
    """Add a ticker to the watchlist and request market data streaming."""
    ticker_upper = payload.ticker.strip().upper()
    if not ticker_upper:
        raise HTTPException(status_code=400, detail="Ticker symbol cannot be empty")

    added = db.add_watchlist_ticker(ticker_upper)
    if not added:
        return {"success": False, "message": "Ticker already in watchlist or invalid"}

    # Signal live market data source to track this ticker
    await market_source.add_ticker(ticker_upper)
    return {"success": True, "ticker": ticker_upper}


@app.delete("/api/watchlist/{ticker}")
async def delete_watchlist(ticker: str) -> dict[str, Any]:
    """Remove a ticker from the watchlist and stop streaming its price updates."""
    ticker_upper = ticker.strip().upper()
    removed = db.remove_watchlist_ticker(ticker_upper)
    if not removed:
        raise HTTPException(status_code=404, detail="Ticker not found in watchlist")

    # Stop tracking ticker in live source
    await market_source.remove_ticker(ticker_upper)
    return {"success": True, "ticker": ticker_upper}


# --- System Health Endpoint ---

@app.get("/api/health")
def healthcheck() -> dict[str, str]:
    """Standard health check endpoint."""
    return {"status": "ok"}


# --- Static Frontend Serving ---

# Search for the static export folder. Default to '../static' relative to this file
static_dir = os.environ.get("STATIC_DIR", os.path.join(os.path.dirname(__file__), "../static"))

if os.path.isdir(static_dir):
    logger.info(f"Serving static frontend files from: {static_dir}")
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
else:
    logger.warning(
        f"Static files directory not found at '{static_dir}'. "
        "Frontend will not be served directly by FastAPI. API-only mode active."
    )
