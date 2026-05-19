import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import yfinance as yf

PICKS_FILE = "picks.json"
BENCHMARK = "SPY"


def load_picks() -> list[dict]:
    if not os.path.exists(PICKS_FILE):
        return []
    with open(PICKS_FILE) as f:
        data = json.load(f)
    return data.get("picks", [])


def save_picks(picks: list[dict]):
    with open(PICKS_FILE, "w") as f:
        json.dump({"picks": picks}, f, indent=2, default=str)


def save_pick(top_pick: str, top_price: float, runner_up: str, runner_up_price: float,
              wildcard: str, wildcard_price: float, confidence: int,
              posts_scraped: int, tickers_found: int, analysis: str):
    picks = load_picks()
    picks.append({
        "id": str(uuid.uuid4())[:8],
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "timestamp": datetime.now(timezone.utc).timestamp(),
        "top_pick": top_pick,
        "top_pick_price": top_price,
        "runner_up": runner_up,
        "runner_up_price": runner_up_price,
        "wildcard": wildcard,
        "wildcard_price": wildcard_price,
        "confidence": confidence,
        "posts_scraped": posts_scraped,
        "tickers_found": tickers_found,
        "analysis": analysis[:500],
    })
    save_picks(picks)


def get_current_price(ticker: str) -> Optional[float]:
    try:
        stock = yf.Ticker(ticker)
        history = stock.history(period="5d")
        if history.empty:
            return None
        return float(history.iloc[-1]["Close"])
    except Exception:
        return None


def compute_performance() -> dict:
    picks = load_picks()
    if not picks:
        return {"picks": [], "summary": {"total_picks": 0, "wins": 0, "losses": 0, "win_rate": 0, "avg_return": 0}}

    benchmark_price = get_current_price(BENCHMARK)

    results = []
    wins = 0
    losses = 0
    total_return = 0.0
    benchmark_total_return = 0.0

    for pick in picks:
        current_price = get_current_price(pick["top_pick"])
        entry_price = pick["top_pick_price"]

        if current_price and entry_price:
            pct_change = round((current_price - entry_price) / entry_price * 100, 2)
        else:
            pct_change = None

        current_runner_price = get_current_price(pick["runner_up"])
        current_wildcard_price = get_current_price(pick["wildcard"])

        # Inverse WSB: fade the top pick (short), buy benchmark
        if pct_change is not None:
            inverse_return = round(-pct_change, 2)
        else:
            inverse_return = None

        if pct_change is not None:
            total_return += pct_change
            if pct_change > 0:
                wins += 1
            else:
                losses += 1

        days_ago = max(1, (datetime.now(timezone.utc).timestamp() - pick["timestamp"]) / 86400)

        results.append({
            "id": pick["id"],
            "date": pick["date"],
            "days_ago": round(days_ago),
            "top_pick": pick["top_pick"],
            "entry_price": entry_price,
            "current_price": current_price,
            "pct_change": pct_change,
            "runner_up": pick["runner_up"],
            "runner_up_entry": pick["runner_up_price"],
            "runner_up_current": current_runner_price,
            "runner_up_pnl": round((current_runner_price - pick["runner_up_price"]) / pick["runner_up_price"] * 100, 2) if current_runner_price and pick["runner_up_price"] else None,
            "wildcard": pick["wildcard"],
            "wildcard_entry": pick["wildcard_price"],
            "wildcard_current": current_wildcard_price,
            "wildcard_pnl": round((current_wildcard_price - pick["wildcard_price"]) / pick["wildcard_price"] * 100, 2) if current_wildcard_price and pick["wildcard_price"] else None,
            "confidence": pick["confidence"],
            "inverse_wsb_return": inverse_return,
            "analysis": pick.get("analysis", ""),
        })

    count = len([r for r in results if r["pct_change"] is not None])
    avg_return = round(total_return / count, 2) if count > 0 else 0
    win_rate = round(wins / count * 100, 1) if count > 0 else 0

    runner_up_returns = [r["runner_up_pnl"] for r in results if r["runner_up_pnl"] is not None]
    avg_runner_return = round(sum(runner_up_returns) / len(runner_up_returns), 2) if runner_up_returns else 0

    wildcard_returns = [r["wildcard_pnl"] for r in results if r["wildcard_pnl"] is not None]
    avg_wildcard_return = round(sum(wildcard_returns) / len(wildcard_returns), 2) if wildcard_returns else 0

    inverse_returns = [r["inverse_wsb_return"] for r in results if r["inverse_wsb_return"] is not None]
    avg_inverse_return = round(sum(inverse_returns) / len(inverse_returns), 2) if inverse_returns else 0
    inverse_win_rate = round(len([r for r in results if r.get("inverse_wsb_return") and r["inverse_wsb_return"] > 0]) / len(inverse_returns) * 100, 1) if inverse_returns else 0

    return {
        "picks": results,
        "benchmark": benchmark_price,
        "summary": {
            "total_picks": len(picks),
            "tracked": count,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "avg_return": avg_return,
            "avg_runner_up_return": avg_runner_return,
            "avg_wildcard_return": avg_wildcard_return,
            "avg_inverse_wsb_return": avg_inverse_return,
            "inverse_wsb_win_rate": inverse_win_rate,
            "current_benchmark_price": benchmark_price,
        },
    }
