"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  ArrowUpRight,
  ArrowDownRight,
  TrendingUp,
  TrendingDown,
  Trash2,
  Send,
  Plus,
  RefreshCw,
  Layers,
  ShieldAlert,
  CheckCircle,
  BarChart3,
  Percent,
} from "lucide-react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Treemap,
} from "recharts";

// Interfaces mirroring the backend
interface PriceUpdate {
  ticker: string;
  price: number | null;
  previous_price: number | null;
  timestamp: string | null;
  change: number;
  change_percent: number;
  direction: "up" | "down" | "flat";
}

interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  value: number;
  unrealized_pnl: number;
  change_percent: number;
  updated_at: string;
}

interface Portfolio {
  cash_balance: number;
  positions: Position[];
  total_value: number;
  positions_value: number;
  total_unrealized_pnl: number;
  total_pnl: number;
}

interface PortfolioSnapshot {
  total_value: number;
  recorded_at: string;
}

interface ChatActionTrade {
  ticker: string;
  side: string;
  quantity: number;
  price?: number;
  success: boolean;
  error?: string;
}

interface ChatActionWatchlist {
  ticker: string;
  action: string;
  success: boolean;
  error?: string;
}

interface ChatResponse {
  message: string;
  trades?: ChatActionTrade[] | null;
  watchlist_changes?: ChatActionWatchlist[] | null;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  actions?: {
    trades?: ChatActionTrade[];
    watchlist_changes?: ChatActionWatchlist[];
  } | null;
  created_at: string;
}

export default function Home() {
  // --- States ---
  const [prices, setPrices] = useState<Record<string, PriceUpdate>>({});
  const [watchlist, setWatchlist] = useState<PriceUpdate[]>([]);
  const [selectedTicker, setSelectedTicker] = useState<string>("AAPL");
  const [sparklines, setSparklines] = useState<Record<string, number[]>>({});
  const [portfolio, setPortfolio] = useState<Portfolio>({
    cash_balance: 10000.0,
    positions: [],
    total_value: 10000.0,
    positions_value: 0.0,
    total_unrealized_pnl: 0.0,
    total_pnl: 0.0,
  });
  const [portfolioHistory, setPortfolioHistory] = useState<PortfolioSnapshot[]>([]);
  const [connectionStatus, setConnectionStatus] = useState<"connected" | "connecting" | "disconnected">("connecting");
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState<string>("");
  const [chatLoading, setChatLoading] = useState<boolean>(false);

  // Manual trade input state
  const [tradeTicker, setTradeTicker] = useState<string>("");
  const [tradeQuantity, setTradeQuantity] = useState<string>("");
  const [tradeLoading, setTradeLoading] = useState<boolean>(false);
  const [tradeError, setTradeError] = useState<string | null>(null);

  // Watchlist input state
  const [newWatchlistTicker, setNewWatchlistTicker] = useState<string>("");

  // Selected Ticker mock historical prices
  const [tickerHistory, setTickerHistory] = useState<Record<string, { time: string; price: number }[]>>({});

  const chatEndRef = useRef<HTMLDivElement>(null);

  // --- API Base URL ---
  const API_BASE = ""; // Same origin

  // --- Load Initial Data ---
  const fetchInitialData = async () => {
    try {
      // Fetch portfolio
      const portRes = await fetch(`${API_BASE}/api/portfolio`);
      if (portRes.ok) {
        const portData = await portRes.json();
        setPortfolio(portData);
      }

      // Fetch watchlist
      const watchRes = await fetch(`${API_BASE}/api/watchlist`);
      if (watchRes.ok) {
        const watchData = await watchRes.json();
        setWatchlist(watchData);
        // Initialize prices cache with loaded watchlist items
        const initialPrices: Record<string, PriceUpdate> = {};
        watchData.forEach((item: PriceUpdate) => {
          initialPrices[item.ticker] = item;
        });
        setPrices(initialPrices);
      }

      // Fetch history snapshots
      const histRes = await fetch(`${API_BASE}/api/portfolio/history`);
      if (histRes.ok) {
        const histData = await histRes.json();
        setPortfolioHistory(histData);
      }

      // Fetch chat log
      // We'll simulate mock history if empty or load
      const chatRes = await fetch(`${API_BASE}/api/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: "Hello" }) });
      // Wait, let's not call POST chat with "Hello" on every load, as it logs messages.
      // We can create a simple chat fetcher or just initialize empty/with welcome message.
      // Let's set a friendly initial welcome message
      setChatHistory([
        {
          role: "assistant",
          content: "Welcome to **FinAlly**, your AI trading workstation! I am here to help you manage your portfolio, analyze positions, and execute simulated trades. Try asking me: `buy 10 shares of TSLA` or `add MSFT to watchlist`.",
          created_at: new Date().toISOString(),
        },
      ]);
    } catch (err) {
      console.error("Error loading initial database states:", err);
    }
  };

  useEffect(() => {
    fetchInitialData();
  }, []);

  // --- Real-time Price SSE Stream ---
  useEffect(() => {
    setConnectionStatus("connecting");
    const eventSource = new EventSource(`${API_BASE}/api/stream/prices`);

    eventSource.onopen = () => {
      setConnectionStatus("connected");
      console.log("SSE Stream connected successfully.");
    };

    eventSource.onerror = (err) => {
      console.error("SSE stream error, trying to reconnect:", err);
      setConnectionStatus("disconnected");
    };

    eventSource.onmessage = (event) => {
      try {
        const newPrices: Record<string, PriceUpdate> = JSON.parse(event.data);
        
        // Update price cache
        setPrices((prev) => {
          const next = { ...prev, ...newPrices };
          
          // Accumulate sparklines
          setSparklines((prevSparks) => {
            const nextSparks = { ...prevSparks };
            Object.keys(newPrices).forEach((ticker) => {
              const item = newPrices[ticker];
              if (item.price !== null) {
                const history = nextSparks[ticker] ? [...nextSparks[ticker]] : [];
                history.push(item.price);
                if (history.length > 25) {
                  history.shift(); // Limit to 25 data points
                }
                nextSparks[ticker] = history;
              }
            });
            return nextSparks;
          });

          // Accumulate ticker history for the selected ticker chart
          setTickerHistory((prevHistory) => {
            const nextHistory = { ...prevHistory };
            Object.keys(newPrices).forEach((ticker) => {
              const item = newPrices[ticker];
              if (item.price !== null) {
                const history = nextHistory[ticker] ? [...nextHistory[ticker]] : [];
                const timeStr = new Date().toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                });
                
                // If no history exists, seed it
                if (history.length === 0) {
                  const seeded = generateMockHistory(item.price);
                  nextHistory[ticker] = [...seeded, { time: timeStr, price: item.price }];
                } else {
                  history.push({ time: timeStr, price: item.price });
                  if (history.length > 40) {
                    history.shift(); // Limit to 40 chart ticks
                  }
                  nextHistory[ticker] = history;
                }
              }
            });
            return nextHistory;
          });

          return next;
        });
      } catch (err) {
        console.error("Error parsing price SSE payload:", err);
      }
    };

    return () => {
      eventSource.close();
    };
  }, []);

  // --- Helper to trigger portfolio sync on events ---
  const syncPortfolio = async () => {
    try {
      const portRes = await fetch(`${API_BASE}/api/portfolio`);
      if (portRes.ok) {
        setPortfolio(await portRes.json());
      }
      const histRes = await fetch(`${API_BASE}/api/portfolio/history`);
      if (histRes.ok) {
        setPortfolioHistory(await histRes.json());
      }
      const watchRes = await fetch(`${API_BASE}/api/watchlist`);
      if (watchRes.ok) {
        setWatchlist(await watchRes.json());
      }
    } catch (err) {
      console.error("Error syncing portfolio states:", err);
    }
  };

  // --- Auto-Scroll Chat ---
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory, chatLoading]);

  // --- Seed Historical Prices Helper ---
  const generateMockHistory = (basePrice: number) => {
    const data = [];
    let price = basePrice;
    const now = new Date();
    for (let i = 24; i >= 1; i--) {
      const timeStr = new Date(now.getTime() - i * 60000).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
      const change = (Math.random() - 0.49) * (basePrice * 0.008);
      price += change;
      data.push({ time: timeStr, price: Math.round(price * 100) / 100 });
    }
    return data;
  };

  // --- Execute Manual Trade ---
  const handleManualTrade = async (side: "buy" | "sell") => {
    const ticker = tradeTicker.trim().toUpperCase();
    const qty = parseFloat(tradeQuantity);

    if (!ticker) {
      setTradeError("Please enter a ticker symbol.");
      return;
    }
    if (isNaN(qty) || qty <= 0) {
      setTradeError("Please enter a valid quantity greater than zero.");
      return;
    }

    setTradeLoading(true);
    setTradeError(null);

    try {
      const res = await fetch(`${API_BASE}/api/portfolio/trade`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker, quantity: qty, side }),
      });

      const data = await res.json();
      if (!res.ok) {
        setTradeError(data.detail || "Trade execution failed.");
      } else {
        // Clear forms
        setTradeTicker("");
        setTradeQuantity("");
        // Sync database states
        await syncPortfolio();
      }
    } catch (err) {
      setTradeError("Network error executing trade.");
    } finally {
      setTradeLoading(false);
    }
  };

  // --- Add Ticker to Watchlist ---
  const handleAddToWatchlist = async (e: React.FormEvent) => {
    e.preventDefault();
    const ticker = newWatchlistTicker.trim().toUpperCase();
    if (!ticker) return;

    try {
      const res = await fetch(`${API_BASE}/api/watchlist`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker }),
      });
      if (res.ok) {
        setNewWatchlistTicker("");
        await syncPortfolio();
      }
    } catch (err) {
      console.error("Error adding to watchlist:", err);
    }
  };

  // --- Remove Ticker from Watchlist ---
  const handleRemoveFromWatchlist = async (ticker: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/watchlist/${ticker}`, {
        method: "DELETE",
      });
      if (res.ok) {
        await syncPortfolio();
        // Remove from prices state clean-up
        setPrices((prev) => {
          const next = { ...prev };
          delete next[ticker];
          return next;
        });
      }
    } catch (err) {
      console.error("Error removing from watchlist:", err);
    }
  };

  // --- Send Message to AI Assistant ---
  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    const msg = chatInput.trim();
    if (!msg) return;

    // Append user message
    const userMsg: ChatMessage = {
      role: "user",
      content: msg,
      created_at: new Date().toISOString(),
    };
    setChatHistory((prev) => [...prev, userMsg]);
    setChatInput("");
    setChatLoading(true);

    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg }),
      });

      if (res.ok) {
        const data: ChatResponse = await res.json();
        const assistantMsg: ChatMessage = {
          role: "assistant",
          content: data.message,
          actions: {
            trades: data.trades as any,
            watchlist_changes: data.watchlist_changes as any,
          },
          created_at: new Date().toISOString(),
        };
        setChatHistory((prev) => [...prev, assistantMsg]);
        
        // Sync states since the assistant may have run auto-actions
        await syncPortfolio();
      } else {
        setChatHistory((prev) => [
          ...prev,
          {
            role: "assistant",
            content: "Sorry, I received an error response from the server chat processor.",
            created_at: new Date().toISOString(),
          },
        ]);
      }
    } catch (err) {
      setChatHistory((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Sorry, I'm having trouble connecting to the chat API right now.",
          created_at: new Date().toISOString(),
        },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  // --- Custom Treemap Content Renderer ---
  const renderTreemapContent = (props: any) => {
    const { x, y, width, height, index, name, value } = props;
    if (width < 32 || height < 20) return <g />;

    // Look up position
    const pos = portfolio.positions.find((p) => p.ticker === name);
    const pnlPct = pos ? pos.change_percent : 0.0;
    const isProfit = pnlPct >= 0;
    
    // Calculate color weight
    const absPnlPct = Math.min(Math.abs(pnlPct), 10.0);
    const opacity = 0.25 + (absPnlPct / 10.0) * 0.75;
    
    const fill = isProfit
      ? `rgba(34, 197, 94, ${opacity})`
      : `rgba(239, 68, 68, ${opacity})`;

    return (
      <g>
        <rect
          x={x}
          y={y}
          width={width}
          height={height}
          style={{
            fill,
            stroke: "#0d1117",
            strokeWidth: 2,
          }}
        />
        {width > 45 && height > 30 && (
          <text
            x={x + width / 2}
            y={y + height / 2 - 3}
            textAnchor="middle"
            fill="#ffffff"
            fontSize={11}
            className="font-bold tracking-wider"
          >
            {name}
          </text>
        )}
        {width > 60 && height > 45 && (
          <text
            x={x + width / 2}
            y={y + height / 2 + 10}
            textAnchor="middle"
            fill="#cbd5e1"
            fontSize={9}
          >
            {pnlPct > 0 ? "+" : ""}{pnlPct.toFixed(1)}%
          </text>
        )}
      </g>
    );
  };

  // --- Render Sparkline Canvas Mini-Chart ---
  const Sparkline = ({ values }: { values: number[] }) => {
    if (!values || values.length < 2) return <span className="text-gray-600">-</span>;
    const minVal = Math.min(...values);
    const maxVal = Math.max(...values);
    const range = maxVal - minVal || 1.0;
    const width = 80;
    const height = 20;

    const points = values
      .map((val, idx) => {
        const x = (idx / (values.length - 1)) * width;
        const y = height - ((val - minVal) / range) * height;
        return `${x},${y}`;
      })
      .join(" ");

    const isUp = values[values.length - 1] >= values[0];

    return (
      <svg width={width} height={height} className="overflow-visible">
        <polyline
          fill="none"
          stroke={isUp ? "#22c55e" : "#ef4444"}
          strokeWidth="1.5"
          points={points}
        />
      </svg>
    );
  };

  // Build Treemap inputs
  const treemapData = portfolio.positions.map((pos) => ({
    name: pos.ticker,
    value: pos.value,
  }));

  // Selected ticker live parameters
  const currentSelectedPrice = prices[selectedTicker]?.price;
  const currentSelectedChange = prices[selectedTicker]?.change_percent || 0.0;
  const activeSelectedHistory = tickerHistory[selectedTicker] || [];

  return (
    <div className="min-h-screen bg-[#0d1117] text-[#ededed] flex flex-col font-sans">
      {/* HEADER BAR */}
      <header className="border-b border-gray-800 bg-[#0d1117]/85 backdrop-blur-md px-6 py-3 flex flex-wrap items-center justify-between gap-4 sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-gradient-to-tr from-[#ecad0a] to-[#209dd7] flex items-center justify-center font-bold text-[#0d1117] shadow-lg shadow-blue-500/10">
            F
          </div>
          <div>
            <span className="text-lg font-bold tracking-wider text-white">Fin<span className="text-[#ecad0a]">Ally</span></span>
            <span className="text-[10px] text-gray-500 block uppercase tracking-widest font-mono">AI Workstation</span>
          </div>
        </div>

        {/* METRICS ROW */}
        <div className="flex flex-wrap items-center gap-6 md:gap-10">
          <div>
            <span className="text-[10px] text-gray-500 uppercase tracking-wider block font-medium">Portfolio Value</span>
            <span className="text-xl font-bold tracking-tight text-white">
              ${portfolio.total_value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          <div>
            <span className="text-[10px] text-gray-500 uppercase tracking-wider block font-medium">Available Cash</span>
            <span className="text-lg font-semibold text-gray-300">
              ${portfolio.cash_balance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          <div>
            <span className="text-[10px] text-gray-500 uppercase tracking-wider block font-medium">Unrealized P&L</span>
            <span className={`text-lg font-semibold flex items-center gap-1 ${portfolio.total_unrealized_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
              {portfolio.total_unrealized_pnl >= 0 ? "+" : ""}
              ${portfolio.total_unrealized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          <div>
            <span className="text-[10px] text-gray-500 uppercase tracking-wider block font-medium">Net P&L</span>
            <span className={`text-lg font-semibold flex items-center gap-1 ${portfolio.total_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
              {portfolio.total_pnl >= 0 ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
              {portfolio.total_pnl >= 0 ? "+" : ""}
              ${portfolio.total_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
        </div>

        {/* CONNECTION STATUS */}
        <div className="flex items-center gap-2 bg-gray-900/40 border border-gray-800 rounded-full px-3 py-1 text-xs">
          <span className={`w-2.5 h-2.5 rounded-full ${
            connectionStatus === "connected" ? "bg-green-500 animate-pulse" :
            connectionStatus === "connecting" ? "bg-yellow-500 animate-pulse" : "bg-red-500"
          }`} />
          <span className="text-gray-400 capitalize font-mono text-[10px]">
            {connectionStatus === "connected" ? "Live Stream" : connectionStatus === "connecting" ? "Reconnecting" : "Disconnected"}
          </span>
        </div>
      </header>

      {/* DASHBOARD GRID */}
      <main className="flex-1 p-4 grid grid-cols-12 gap-4 h-[calc(100vh-68px)] overflow-hidden">
        
        {/* LEFT COLUMN: WATCHLIST & QUICK TRADE */}
        <section className="col-span-12 lg:col-span-3 flex flex-col gap-4 overflow-y-auto pr-1">
          {/* Watchlist Panel */}
          <div className="bg-[#161b22]/70 border border-gray-800 rounded-xl p-4 flex flex-col gap-3 backdrop-blur-sm shadow-xl">
            <div className="flex justify-between items-center border-b border-gray-800 pb-2">
              <h2 className="font-bold text-sm uppercase tracking-wider text-gray-400 flex items-center gap-2">
                <BarChart3 size={14} className="text-[#ecad0a]" />
                Watchlist
              </h2>
              <form onSubmit={handleAddToWatchlist} className="flex items-center gap-1">
                <input
                  type="text"
                  placeholder="ADD TICKER"
                  value={newWatchlistTicker}
                  onChange={(e) => setNewWatchlistTicker(e.target.value)}
                  className="bg-gray-900 border border-gray-800 rounded px-2 py-1 text-xs w-20 font-mono tracking-wider focus:outline-none focus:border-[#ecad0a]"
                />
                <button type="submit" className="bg-[#ecad0a] hover:bg-[#c99307] text-[#0d1117] rounded p-1 transition-colors">
                  <Plus size={14} />
                </button>
              </form>
            </div>

            <div className="overflow-x-auto min-h-[280px]">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-gray-800/60 text-gray-500 uppercase tracking-widest text-[9px]">
                    <th className="py-2">TICKER</th>
                    <th className="py-2 text-right">PRICE</th>
                    <th className="py-2 text-right">CHG %</th>
                    <th className="py-2 text-center">SPARK</th>
                    <th className="py-2"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800/40">
                  {watchlist.map((item) => {
                    const priceUpdate = prices[item.ticker] || item;
                    const price = priceUpdate.price;
                    const changePct = priceUpdate.change_percent;
                    const direction = priceUpdate.direction;

                    return (
                      <tr
                        key={item.ticker}
                        onClick={() => setSelectedTicker(item.ticker)}
                        className={`hover:bg-gray-800/30 cursor-pointer transition-colors ${
                          selectedTicker === item.ticker ? "bg-gray-800/40 font-semibold" : ""
                        }`}
                      >
                        <td className="py-2.5 font-bold tracking-wider font-mono text-gray-300">
                          {item.ticker}
                        </td>
                        <td className="py-2.5 text-right font-mono">
                          {price !== null ? (
                            <span
                              key={price} // Forces React to re-mount the text, triggering the css keyframes
                              className={
                                direction === "up" ? "flash-up text-green-400 px-1 py-0.5 rounded" :
                                direction === "down" ? "flash-down text-red-400 px-1 py-0.5 rounded" : "px-1 py-0.5"
                              }
                            >
                              ${price.toFixed(2)}
                            </span>
                          ) : (
                            <span className="text-gray-600">LOADING</span>
                          )}
                        </td>
                        <td className={`py-2.5 text-right font-mono ${changePct >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {changePct >= 0 ? "+" : ""}
                          {changePct.toFixed(2)}%
                        </td>
                        <td className="py-2.5 text-center flex justify-center">
                          <Sparkline values={sparklines[item.ticker] || []} />
                        </td>
                        <td className="py-2.5 text-right">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleRemoveFromWatchlist(item.ticker);
                            }}
                            className="text-gray-600 hover:text-red-400 p-1 rounded transition-colors"
                          >
                            <Trash2 size={12} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Quick Trade Panel */}
          <div className="bg-[#161b22]/70 border border-gray-800 rounded-xl p-4 flex flex-col gap-3 backdrop-blur-sm shadow-xl">
            <h2 className="font-bold text-sm uppercase tracking-wider text-gray-400 border-b border-gray-800 pb-2 flex items-center gap-2">
              <Layers size={14} className="text-[#209dd7]" />
              Quick Order Bar
            </h2>

            <div className="flex flex-col gap-3">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-gray-500 uppercase font-bold tracking-wider block mb-1">Stock Ticker</label>
                  <input
                    type="text"
                    placeholder="E.G. AAPL"
                    value={tradeTicker}
                    onChange={(e) => setTradeTicker(e.target.value)}
                    className="bg-gray-900 border border-gray-800 rounded p-2 text-sm w-full font-mono uppercase focus:outline-none focus:border-[#209dd7]"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 uppercase font-bold tracking-wider block mb-1">Shares Count</label>
                  <input
                    type="number"
                    placeholder="QUANTITY"
                    value={tradeQuantity}
                    onChange={(e) => setTradeQuantity(e.target.value)}
                    className="bg-gray-900 border border-gray-800 rounded p-2 text-sm w-full font-mono focus:outline-none focus:border-[#209dd7]"
                  />
                </div>
              </div>

              {tradeError && (
                <div className="bg-red-900/30 border border-red-800 text-red-400 text-xs rounded p-2 flex items-start gap-2">
                  <ShieldAlert size={14} className="shrink-0 mt-0.5" />
                  <span>{tradeError}</span>
                </div>
              )}

              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => handleManualTrade("buy")}
                  disabled={tradeLoading}
                  className="bg-green-600 hover:bg-green-500 text-white font-bold py-2 rounded text-sm tracking-wide transition-colors flex items-center justify-center gap-1 disabled:opacity-50"
                >
                  BUY
                </button>
                <button
                  onClick={() => handleManualTrade("sell")}
                  disabled={tradeLoading}
                  className="bg-red-600 hover:bg-red-500 text-white font-bold py-2 rounded text-sm tracking-wide transition-colors flex items-center justify-center gap-1 disabled:opacity-50"
                >
                  SELL
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* MIDDLE COLUMN: CHARTS, HEATMAP, POSITIONS */}
        <section className="col-span-12 lg:col-span-6 flex flex-col gap-4 overflow-y-auto pr-1">
          
          {/* Main Chart Area */}
          <div className="bg-[#161b22]/70 border border-gray-800 rounded-xl p-4 flex flex-col gap-2 backdrop-blur-sm shadow-xl min-h-[300px]">
            <div className="flex justify-between items-center border-b border-gray-800 pb-2">
              <div>
                <h2 className="font-bold text-white text-base tracking-wide flex items-center gap-2">
                  {selectedTicker} 
                  <span className="text-xs font-mono text-gray-500">Live Chart</span>
                </h2>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-xl font-bold font-mono text-[#ecad0a]">
                    {typeof currentSelectedPrice === "number" ? `$${currentSelectedPrice.toFixed(2)}` : "LOADING..."}
                  </span>
                  {typeof currentSelectedPrice === "number" && (
                    <span className={`text-xs font-semibold font-mono flex items-center gap-0.5 ${currentSelectedChange >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {currentSelectedChange >= 0 ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                      {currentSelectedChange >= 0 ? "+" : ""}{currentSelectedChange.toFixed(2)}%
                    </span>
                  )}
                </div>
              </div>
            </div>

            <div className="h-[220px] w-full mt-2 font-mono text-xs">
              {activeSelectedHistory.length > 1 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={activeSelectedHistory} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <XAxis dataKey="time" stroke="#4b5563" strokeWidth={0.5} />
                    <YAxis domain={["auto", "auto"]} stroke="#4b5563" strokeWidth={0.5} />
                    <Tooltip
                      contentStyle={{ backgroundColor: "#0d1117", borderColor: "#1f2937", color: "#fff" }}
                      labelClassName="font-bold font-mono"
                    />
                    <Line
                      type="monotone"
                      dataKey="price"
                      stroke="#209dd7"
                      strokeWidth={2}
                      dot={false}
                      activeDot={{ r: 4 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-gray-500 italic">
                  Awaiting pricing history ticks...
                </div>
              )}
            </div>
          </div>

          {/* Heatmap & P&L Side-by-side */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Heatmap block */}
            <div className="bg-[#161b22]/70 border border-gray-800 rounded-xl p-4 flex flex-col gap-2 backdrop-blur-sm shadow-xl h-[220px]">
              <h3 className="font-bold text-xs uppercase tracking-wider text-gray-400 border-b border-gray-800 pb-2">
                Portfolio Weights (Heatmap)
              </h3>
              <div className="flex-1 w-full relative">
                {treemapData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <Treemap
                      data={treemapData}
                      dataKey="value"
                      aspectRatio={4 / 3}
                      stroke="#0d1117"
                      content={renderTreemapContent}
                    />
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-gray-500 italic text-xs text-center px-4">
                    No open positions to weight. Purchase stock to populate.
                  </div>
                )}
              </div>
            </div>

            {/* P&L Performance History Line chart */}
            <div className="bg-[#161b22]/70 border border-gray-800 rounded-xl p-4 flex flex-col gap-2 backdrop-blur-sm shadow-xl h-[220px]">
              <h3 className="font-bold text-xs uppercase tracking-wider text-gray-400 border-b border-gray-800 pb-2">
                Total Value Performance
              </h3>
              <div className="flex-1 w-full font-mono text-[10px]">
                {portfolioHistory.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={portfolioHistory} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <XAxis
                        dataKey="recorded_at"
                        tickFormatter={(tick) => new Date(tick).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                        stroke="#4b5563"
                      />
                      <YAxis domain={["auto", "auto"]} stroke="#4b5563" />
                      <Tooltip
                        labelFormatter={(label) => new Date(label).toLocaleString()}
                        contentStyle={{ backgroundColor: "#0d1117", borderColor: "#1f2937", color: "#fff" }}
                      />
                      <Line
                        type="monotone"
                        dataKey="total_value"
                        stroke="#ecad0a"
                        strokeWidth={1.5}
                        dot={true}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-gray-500 italic text-xs">
                    Recording initial performance data points...
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Positions Table */}
          <div className="bg-[#161b22]/70 border border-gray-800 rounded-xl p-4 flex flex-col gap-2 backdrop-blur-sm shadow-xl overflow-hidden mb-4">
            <h3 className="font-bold text-xs uppercase tracking-wider text-gray-400 border-b border-gray-800 pb-2">
              Open Positions Holdings
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-gray-800/60 text-gray-500 uppercase tracking-widest text-[9px]">
                    <th className="py-2">TICKER</th>
                    <th className="py-2 text-right">SHARES</th>
                    <th className="py-2 text-right">AVG COST</th>
                    <th className="py-2 text-right">CURR PRICE</th>
                    <th className="py-2 text-right">MARKET VALUE</th>
                    <th className="py-2 text-right">UNREALIZED P&L</th>
                    <th className="py-2 text-right">CHG %</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800/40">
                  {portfolio.positions.length > 0 ? (
                    portfolio.positions.map((pos) => {
                      const currPrice = prices[pos.ticker]?.price || pos.current_price;
                      const val = pos.quantity * currPrice;
                      const pnl = val - (pos.quantity * pos.avg_cost);
                      const pnlPct = pos.avg_cost > 0 ? (pnl / (pos.quantity * pos.avg_cost) * 100) : 0.0;

                      return (
                        <tr key={pos.ticker} className="hover:bg-gray-800/20">
                          <td className="py-2 font-bold font-mono tracking-wide text-gray-300">
                            {pos.ticker}
                          </td>
                          <td className="py-2 text-right font-mono">
                            {pos.quantity.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                          </td>
                          <td className="py-2 text-right font-mono">
                            ${pos.avg_cost.toFixed(2)}
                          </td>
                          <td className="py-2 text-right font-mono">
                            ${currPrice.toFixed(2)}
                          </td>
                          <td className="py-2 text-right font-mono">
                            ${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </td>
                          <td className={`py-2 text-right font-mono ${pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {pnl >= 0 ? "+" : ""}
                            ${pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </td>
                          <td className={`py-2 text-right font-mono ${pnlPct >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {pnlPct >= 0 ? "+" : ""}
                            {pnlPct.toFixed(2)}%
                          </td>
                        </tr>
                      );
                    })
                  ) : (
                    <tr>
                      <td colSpan={7} className="py-6 text-center text-gray-500 italic">
                        No open positions. Use order panel or AI chat to buy shares.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* RIGHT COLUMN: AI COPILOT CHAT SIDEBAR */}
        <section className="col-span-12 lg:col-span-3 border border-gray-800 bg-[#161b22]/50 rounded-xl flex flex-col h-full overflow-hidden shadow-2xl backdrop-blur-sm">
          {/* Header */}
          <div className="bg-[#161b22] px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full bg-[#ecad0a] animate-pulse" />
              <h2 className="font-bold text-sm uppercase tracking-wider text-gray-300">
                AI Copilot Terminal
              </h2>
            </div>
            <button
              onClick={() => {
                setChatHistory([
                  {
                    role: "assistant",
                    content: "Terminal conversation log cleared. Let me know how I can help manage your portfolio!",
                    created_at: new Date().toISOString(),
                  },
                ]);
              }}
              className="text-gray-500 hover:text-gray-300 transition-colors"
            >
              <RefreshCw size={13} />
            </button>
          </div>

          {/* Scroll Area */}
          <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4 text-xs font-mono">
            {chatHistory.map((msg, index) => (
              <div
                key={index}
                className={`flex flex-col gap-1.5 max-w-[85%] ${
                  msg.role === "user" ? "self-end items-end" : "self-start"
                }`}
              >
                <span className="text-[9px] text-gray-500">
                  {msg.role === "user" ? "USER" : "ASSISTANT"} • {new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </span>

                <div
                  className={`rounded-lg p-2.5 leading-relaxed break-words whitespace-pre-wrap ${
                    msg.role === "user"
                      ? "bg-[#209dd7]/20 border border-[#209dd7]/40 text-[#b5e2f9]"
                      : "bg-[#1f2937]/80 border border-gray-800 text-gray-200"
                  }`}
                >
                  {msg.content}
                </div>

                {/* Inline confirmation logs for auto actions */}
                {msg.actions && (
                  <div className="flex flex-col gap-1 border-l-2 border-[#ecad0a]/40 pl-2 mt-1">
                    {msg.actions.trades && msg.actions.trades.map((t, idx) => (
                      <div key={idx} className="flex items-center gap-1.5 text-[9px] font-mono">
                        {t.success ? (
                          <CheckCircle size={10} className="text-green-500" />
                        ) : (
                          <ShieldAlert size={10} className="text-red-500" />
                        )}
                        <span className={t.success ? "text-green-400" : "text-red-400"}>
                          {t.side.toUpperCase()} {t.quantity} {t.ticker} {t.success ? `@ $${t.price?.toFixed(2)}` : `(FAILED: ${t.error})`}
                        </span>
                      </div>
                    ))}

                    {msg.actions.watchlist_changes && msg.actions.watchlist_changes.map((w, idx) => (
                      <div key={idx} className="flex items-center gap-1.5 text-[9px] font-mono">
                        {w.success ? (
                          <CheckCircle size={10} className="text-green-500" />
                        ) : (
                          <ShieldAlert size={10} className="text-red-500" />
                        )}
                        <span className={w.success ? "text-green-400" : "text-red-400"}>
                          WATCHLIST {w.action.toUpperCase()} {w.ticker} {w.success ? "(OK)" : `(FAILED: ${w.error})`}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {chatLoading && (
              <div className="self-start flex flex-col gap-1 max-w-[85%]">
                <span className="text-[9px] text-gray-500">ASSISTANT • THINKING...</span>
                <div className="bg-[#1f2937]/80 border border-gray-800 rounded-lg p-2.5 flex items-center gap-2">
                  <div className="w-1.5 h-1.5 bg-[#ecad0a] rounded-full animate-bounce" />
                  <div className="w-1.5 h-1.5 bg-[#ecad0a] rounded-full animate-bounce [animation-delay:0.2s]" />
                  <div className="w-1.5 h-1.5 bg-[#ecad0a] rounded-full animate-bounce [animation-delay:0.4s]" />
                </div>
              </div>
            )}

            <div ref={chatEndRef} />
          </div>

          {/* Form Input */}
          <form onSubmit={handleSendMessage} className="p-3 border-t border-gray-800 bg-[#161b22]/90 flex gap-2">
            <input
              type="text"
              placeholder="ASK ASSISTANT OR EXECUTE..."
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              className="bg-gray-900 border border-gray-800 rounded px-3 py-2 text-xs flex-1 font-mono tracking-wide focus:outline-none focus:border-[#753991]"
            />
            <button
              type="submit"
              className="bg-[#753991] hover:bg-[#612d7a] text-white rounded px-3 py-2 transition-colors flex items-center justify-center shadow-md shadow-[#753991]/20"
            >
              <Send size={14} />
            </button>
          </form>
        </section>

      </main>
    </div>
  );
}
