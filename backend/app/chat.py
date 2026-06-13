"""Chat logic module for FinAlly workstation.

Handles the /api/chat endpoint, LLM integration, prompt formatting,
and automatic action execution (trades, watchlist changes).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from litellm import completion
from pydantic import BaseModel, Field

from app import db
from app.market.cache import PriceCache
from app.market.interface import MarketDataSource
from app.portfolio import execute_trade

logger = logging.getLogger(__name__)

# Define Pydantic models for request/response schemas

class ChatPayload(BaseModel):
    message: str


class TradeAction(BaseModel):
    ticker: str = Field(description="Ticker symbol of the stock, e.g., AAPL")
    side: str = Field(description="Trade side: 'buy' or 'sell'")
    quantity: float = Field(description="Number of shares to trade (supports fractions)")


class WatchlistChangeAction(BaseModel):
    ticker: str = Field(description="Ticker symbol of the stock")
    action: str = Field(description="Watchlist action: 'add' or 'remove'")


class ChatResponse(BaseModel):
    message: str = Field(description="The conversational text response to the user")
    trades: list[TradeAction] | None = Field(default=None, description="Array of trades to execute")
    watchlist_changes: list[WatchlistChangeAction] | None = Field(default=None, description="Array of watchlist changes to apply")


def create_chat_router(price_cache: PriceCache, market_source: MarketDataSource) -> APIRouter:
    """Create the chat router with references to the price cache and market data source.

    Allows the chat handler to execute trades using the cache and add/remove
    tickers dynamically from market polling/simulation.
    """
    router = APIRouter(prefix="/api/chat", tags=["chat"])

    @router.post("", response_model=ChatResponse)
    async def chat(payload: ChatPayload) -> ChatResponse:
        user_id = "default"
        user_message = payload.message.strip()

        if not user_message:
            raise HTTPException(status_code=400, detail="Message cannot be empty")

        # 1. Fetch current portfolio and watchlist states
        cash = db.get_cash_balance(user_id)
        positions = db.get_positions(user_id)
        watchlist = db.get_watchlist(user_id)

        # 2. Check for Mock Mode
        is_mock = os.environ.get("LLM_MOCK", "false").lower() == "true"

        if is_mock:
            response_obj = _execute_mock_llm(user_message, watchlist)
        else:
            # 3. Generate prompt & call LLM
            history = db.get_chat_history(user_id, limit=10)
            response_obj = await _call_real_llm(user_message, history, cash, positions, watchlist, price_cache)

        # 4. Auto-execute trades
        executed_trades_logs = []
        if response_obj.trades:
            for trade in response_obj.trades:
                trade_result = execute_trade(
                    ticker=trade.ticker,
                    quantity=trade.quantity,
                    side=trade.side,
                    price_cache=price_cache,
                    user_id=user_id,
                )
                if trade_result["success"]:
                    executed_trades_logs.append({
                        "ticker": trade.ticker.upper(),
                        "side": trade.side.lower(),
                        "quantity": trade.quantity,
                        "price": trade_result["price"],
                        "success": True,
                    })
                else:
                    executed_trades_logs.append({
                        "ticker": trade.ticker.upper(),
                        "side": trade.side.lower(),
                        "quantity": trade.quantity,
                        "success": False,
                        "error": trade_result["error"],
                    })

        # 5. Auto-execute watchlist changes
        executed_watchlist_changes = []
        if response_obj.watchlist_changes:
            for change in response_obj.watchlist_changes:
                ticker_upper = change.ticker.strip().upper()
                action_lower = change.action.strip().lower()

                if action_lower == "add":
                    added = db.add_watchlist_ticker(ticker_upper, user_id)
                    if added:
                        await market_source.add_ticker(ticker_upper)
                        executed_watchlist_changes.append({"ticker": ticker_upper, "action": "add", "success": True})
                    else:
                        executed_watchlist_changes.append({"ticker": ticker_upper, "action": "add", "success": False, "error": "Already in watchlist"})
                elif action_lower == "remove":
                    removed = db.remove_watchlist_ticker(ticker_upper, user_id)
                    if removed:
                        await market_source.remove_ticker(ticker_upper)
                        executed_watchlist_changes.append({"ticker": ticker_upper, "action": "remove", "success": True})
                    else:
                        executed_watchlist_changes.append({"ticker": ticker_upper, "action": "remove", "success": False, "error": "Not in watchlist"})

        # 6. Save chat messages to database
        actions_saved = {}
        if executed_trades_logs:
            actions_saved["trades"] = executed_trades_logs
        if executed_watchlist_changes:
            actions_saved["watchlist_changes"] = executed_watchlist_changes

        db.add_chat_message("user", user_message, None, user_id)
        
        # Append trade execution logs to the visible assistant response message if any failed/succeeded, for transparency
        final_message = response_obj.message
        if executed_trades_logs:
            summary_parts = []
            for t in executed_trades_logs:
                if t["success"]:
                    summary_parts.append(f"Successfully {t['side']} {t['quantity']} shares of {t['ticker']} at ${t['price']:.2f}.")
                else:
                    summary_parts.append(f"Failed to {t['side']} {t['quantity']} shares of {t['ticker']}: {t['error']}.")
            final_message += "\n\n**Trade Executions:**\n" + "\n".join(f"- {p}" for p in summary_parts)

        if executed_watchlist_changes:
            summary_parts = []
            for c in executed_watchlist_changes:
                if c["success"]:
                    summary_parts.append(f"Updated watchlist: {c['action'].upper()} {c['ticker']}.")
                else:
                    summary_parts.append(f"Failed to update watchlist for {c['ticker']}: {c['error']}.")
            final_message += "\n\n**Watchlist Changes:**\n" + "\n".join(f"- {p}" for p in summary_parts)

        db.add_chat_message("assistant", final_message, actions_saved or None, user_id)

        # 7. Return complete response
        return ChatResponse(
            message=final_message,
            trades=response_obj.trades,
            watchlist_changes=response_obj.watchlist_changes,
        )

    return router


def _execute_mock_llm(message: str, watchlist: list[str]) -> ChatResponse:
    """Process user message using basic regex matching to simulate LLM execution for tests."""
    msg_lower = message.lower()
    trades: list[TradeAction] = []
    watchlist_changes: list[WatchlistChangeAction] = []

    # 1. Matches: "buy 10 aapl" or "buy 10.5 shares of msft"
    buy_match = re.search(r"\bbuy\s+([0-9.]+)\s*(?:shares\s+of\s+)?([a-zA-Z]+)\b", msg_lower)
    if buy_match:
        qty = float(buy_match.group(1))
        ticker = buy_match.group(2).upper()
        trades.append(TradeAction(ticker=ticker, side="buy", quantity=qty))

    # 2. Matches: "sell 5 tsla" or "sell 3 shares of nvda"
    sell_match = re.search(r"\bsell\s+([0-9.]+)\s*(?:shares\s+of\s+)?([a-zA-Z]+)\b", msg_lower)
    if sell_match:
        qty = float(sell_match.group(1))
        ticker = sell_match.group(2).upper()
        trades.append(TradeAction(ticker=ticker, side="sell", quantity=qty))

    # 3. Matches: "add pypl to watchlist" or "add pypl"
    add_match = re.search(r"\badd\s+([a-zA-Z]+)\s*(?:to\s+(?:the\s+)?watchlist)?\b", msg_lower)
    if add_match:
        ticker = add_match.group(1).upper()
        if ticker not in ["SHARES", "THE", "WATCHLIST", "BUY", "SELL", "ADD", "REMOVE"]:
            watchlist_changes.append(WatchlistChangeAction(ticker=ticker, action="add"))

    # 4. Matches: "remove pypl from watchlist" or "delete pypl"
    remove_match = re.search(r"\b(?:remove|delete)\s+([a-zA-Z]+)\s*(?:from\s+(?:the\s+)?watchlist)?\b", msg_lower)
    if remove_match:
        ticker = remove_match.group(1).upper()
        if ticker not in ["SHARES", "THE", "WATCHLIST", "BUY", "SELL", "ADD", "REMOVE"]:
            watchlist_changes.append(WatchlistChangeAction(ticker=ticker, action="remove"))

    # Construct mock conversational reply
    replies = []
    if trades:
        for t in trades:
            replies.append(f"Executing trade to {t.side} {t.quantity} shares of {t.ticker}.")
    if watchlist_changes:
        for c in watchlist_changes:
            replies.append(f"Updating watchlist: {c.action} {c.ticker}.")

    if not replies:
        message_reply = (
            "Hi there! I am FinAlly, your AI portfolio assistant. "
            "I can execute trades and manage your watchlist. "
            "Try asking me to 'buy 10 AAPL' or 'add AMD to watchlist' to test my simulated actions!"
        )
    else:
        message_reply = " ".join(replies)

    return ChatResponse(
        message=message_reply,
        trades=trades or None,
        watchlist_changes=watchlist_changes or None,
    )


async def _call_real_llm(
    user_message: str,
    history: list[dict[str, Any]],
    cash: float,
    positions: list[dict[str, Any]],
    watchlist: list[str],
    price_cache: PriceCache,
) -> ChatResponse:
    """Call the LLM using LiteLLM via OpenRouter and Cerebras inference with structured outputs."""
    # Format the portfolio description
    portfolio_lines = []
    for pos in positions:
        ticker = pos["ticker"]
        qty = pos["quantity"]
        avg_cost = pos["avg_cost"]
        curr_price = price_cache.get_price(ticker)
        if curr_price is None:
            curr_price = avg_cost
        value = qty * curr_price
        pnl = value - (qty * avg_cost)
        pnl_pct = (pnl / (qty * avg_cost) * 100) if avg_cost else 0.0
        portfolio_lines.append(
            f"- {ticker}: {qty} shares @ avg cost ${avg_cost:.2f} "
            f"(current price: ${curr_price:.2f}, current value: ${value:.2f}, P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%))"
        )
    portfolio_desc = "\n".join(portfolio_lines) if portfolio_lines else "No open positions."

    # Format watchlist description
    watchlist_lines = []
    for t in watchlist:
        price = price_cache.get_price(t)
        price_str = f"${price:.2f}" if price is not None else "no price available"
        watchlist_lines.append(f"- {t}: {price_str}")
    watchlist_desc = "\n".join(watchlist_lines)

    system_prompt = (
        "You are FinAlly, an AI trading workstation assistant.\n"
        "You help the user manage their simulated trading portfolio. "
        "You can execute trades (buy/sell market orders) and manage the watchlist "
        "(add/remove tickers) on behalf of the user by providing structured output actions.\n\n"
        "Always respond with a valid structured JSON format matching the ChatResponse schema.\n\n"
        f"--- USER PORTFOLIO STATE ---\n"
        f"Available Cash: ${cash:,.2f}\n"
        f"Current Open Positions:\n{portfolio_desc}\n\n"
        f"--- WATCHLIST & CURRENT PRICES ---\n"
        f"{watchlist_desc}\n\n"
        "--- INSTRUCTIONS ---\n"
        "- If the user wants to buy a stock, check if they have enough cash. If yes, add a trade action with side 'buy'.\n"
        "- If they want to sell, check if they own enough shares. If yes, add a trade action with side 'sell'.\n"
        "- If they ask to watch a ticker or add it, add a watchlist change action with action 'add'.\n"
        "- If they ask to unwatch or remove, add a watchlist change action with action 'remove'.\n"
        "- Always keep the conversational 'message' concise and explain what actions you are performing."
    )

    # Build messages sequence
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    MODEL = "openrouter/openai/gpt-oss-120b"
    EXTRA_BODY = {"provider": {"order": ["cerebras"]}}

    try:
        # LiteLLM structured outputs completion call
        response = completion(
            model=MODEL,
            messages=messages,
            response_format=ChatResponse,
            reasoning_effort="low",
            extra_body=EXTRA_BODY,
        )
        content_str = response.choices[0].message.content
        return ChatResponse.model_validate_json(content_str)
    except Exception as e:
        logger.error(f"Error calling LLM: {e}", exc_info=True)
        # Fallback to a graceful user message instead of crashing
        return ChatResponse(
            message=f"I'm sorry, I encountered an error communicating with my brain: {e}. Please try again later.",
            trades=None,
            watchlist_changes=None,
        )
