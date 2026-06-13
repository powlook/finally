"""Portfolio business logic module for FinAlly workstation.

Handles trade execution validation, position adjustments, and portfolio value snapshots.
"""

from __future__ import annotations

import logging
from typing import Any

from app import db
from app.market.cache import PriceCache
from app.market.seed_prices import SEED_PRICES

logger = logging.getLogger(__name__)


def record_portfolio_snapshot_now(price_cache: PriceCache, user_id: str = "default") -> float:
    """Calculate the total portfolio value and write a snapshot to the database.

    Returns the calculated total portfolio value.
    """
    cash = db.get_cash_balance(user_id)
    positions = db.get_positions(user_id)
    total_val = cash

    for pos in positions:
        ticker = pos["ticker"]
        price = price_cache.get_price(ticker)
        if price is None:
            # Fallback to average cost if market price is not in cache yet
            price = pos["avg_cost"]
        total_val += pos["quantity"] * price

    db.add_portfolio_snapshot(total_val, user_id)
    return total_val


def execute_trade(
    ticker: str,
    quantity: float,
    side: str,
    price_cache: PriceCache,
    user_id: str = "default",
) -> dict[str, Any]:
    """Validate and execute a market order (buy/sell).

    Maintains cash balance, adjusts position holdings, logs the trade, and triggers
    an immediate portfolio value snapshot.
    """
    ticker_upper = ticker.strip().upper()
    side_lower = side.strip().lower()

    if quantity <= 0:
        return {"success": False, "error": "Quantity must be greater than zero", "price": 0.0}

    # Fetch live price from the cache
    price = price_cache.get_price(ticker_upper)
    if price is None:
        # Fallback to seed price if it's one of our default stocks
        price = SEED_PRICES.get(ticker_upper)
        if price is None:
            return {
                "success": False,
                "error": f"No market price available for {ticker_upper}",
                "price": 0.0,
            }

    cash = db.get_cash_balance(user_id)

    if side_lower == "buy":
        cost = quantity * price
        if cash < cost:
            return {
                "success": False,
                "error": f"Insufficient cash. Required: ${cost:,.2f}, Available: ${cash:,.2f}",
                "price": price,
            }

        # Check existing positions
        positions = db.get_positions(user_id)
        existing = next((p for p in positions if p["ticker"] == ticker_upper), None)

        if existing:
            new_qty = existing["quantity"] + quantity
            # New average cost is weighted average of previous cost and current cost
            total_cost = (existing["quantity"] * existing["avg_cost"]) + cost
            new_avg_cost = total_cost / new_qty
        else:
            new_qty = quantity
            new_avg_cost = price

        db.update_cash_balance(cash - cost, user_id)
        db.update_position(ticker_upper, new_qty, new_avg_cost, user_id)
        db.add_trade(ticker_upper, "buy", quantity, price, user_id)

        # Trigger immediate snapshot
        record_portfolio_snapshot_now(price_cache, user_id)
        logger.info(f"Executed BUY of {quantity} shares of {ticker_upper} at ${price:.2f}")
        return {"success": True, "error": None, "price": price}

    elif side_lower == "sell":
        # Check existing positions
        positions = db.get_positions(user_id)
        existing = next((p for p in positions if p["ticker"] == ticker_upper), None)

        if not existing or existing["quantity"] < quantity:
            avail = existing["quantity"] if existing else 0.0
            return {
                "success": False,
                "error": f"Insufficient shares of {ticker_upper}. Required: {quantity}, Available: {avail}",
                "price": price,
            }

        new_qty = existing["quantity"] - quantity
        proceeds = quantity * price

        db.update_cash_balance(cash + proceeds, user_id)
        # Average cost does not change on sell orders
        db.update_position(ticker_upper, new_qty, existing["avg_cost"], user_id)
        db.add_trade(ticker_upper, "sell", quantity, price, user_id)

        # Trigger immediate snapshot
        record_portfolio_snapshot_now(price_cache, user_id)
        logger.info(f"Executed SELL of {quantity} shares of {ticker_upper} at ${price:.2f}")
        return {"success": True, "error": None, "price": price}

    else:
        return {"success": False, "error": f"Invalid trade side: {side_lower}", "price": 0.0}
