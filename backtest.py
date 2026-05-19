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
    spy_price = get_current_price("SPY") or 0
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
        "spy_entry_price": spy_price,
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


def get_7day_return(ticker: str, start_price: float) -> Optional[float]:
    """Get the return of ticker 7 days after the entry. Uses history to find 7-day-ago price."""
    try:
        stock = yf.Ticker(ticker)
        history = stock.history(period="2wk")
        if history.empty:
            return None
        now_price = float(history.iloc[-1]["Close"])
        if start_price and start_price > 0:
            return round((now_price - start_price) / start_price * 100, 2)
    except Exception:
        pass
    return None


def compute_performance() -> dict:
    picks = load_picks()
    if not picks:
        return {"picks": [], "summary": {"total_picks": 0, "wins": 0, "losses": 0, "win_rate": 0, "avg_return": 0}}

    benchmark_price = get_current_price(BENCHMARK)
    now = datetime.now(timezone.utc).timestamp()

    results = []
    wins = 0
    losses = 0
    total_return = 0.0
    matured_results = []  # picks >= 7 days old
    rolling_returns = []  # last 30 days for rolling accuracy

    for pick in picks:
        current_price = get_current_price(pick["top_pick"])
        entry_price = pick["top_pick_price"]
        spy_entry = pick.get("spy_entry_price", 0)
        days_ago = max(1, (now - pick["timestamp"]) / 86400)

        pct_change = None
        spy_change = None
        if current_price and entry_price:
            pct_change = round((current_price - entry_price) / entry_price * 100, 2)
        if benchmark_price and spy_entry and spy_entry > 0:
            spy_change = round((benchmark_price - spy_entry) / spy_entry * 100, 2)

        inverse_return = round(-pct_change, 2) if pct_change is not None else None
        ai_vs_spy = round((pct_change or 0) - (spy_change or 0), 2) if pct_change is not None and spy_change is not None else None

        if pct_change is not None:
            total_return += pct_change
            if pct_change > 0:
                wins += 1
            else:
                losses += 1
            if days_ago <= 30:
                rolling_returns.append(pct_change)

        # Check if 7-day matured
        if days_ago >= 7:
            matured_7day_return = get_7day_return(pick["top_pick"], entry_price)
            matured_spy_7day = None
            if spy_entry and spy_entry > 0 and benchmark_price:
                matured_spy_7day = round((benchmark_price - spy_entry) / spy_entry * 100, 2)
            matured_inverse = round(-matured_7day_return, 2) if matured_7day_return is not None else None
            matured_results.append({
                "date": pick["date"],
                "top_pick": pick["top_pick"],
                "pick_7day_return": matured_7day_return,
                "spy_7day_return": matured_spy_7day,
                "inverse_7day_return": matured_inverse,
                "confidence": pick["confidence"],
                "days_ago": round(days_ago),
            })

        current_runner_price = get_current_price(pick["runner_up"])
        current_wildcard_price = get_current_price(pick["wildcard"])

        results.append({
            "id": pick["id"],
            "date": pick["date"],
            "days_ago": round(days_ago),
            "top_pick": pick["top_pick"],
            "entry_price": entry_price,
            "current_price": current_price,
            "pct_change": pct_change,
            "spy_entry": spy_entry,
            "spy_current": benchmark_price,
            "spy_pnl": spy_change,
            "ai_vs_spy": ai_vs_spy,
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

    rolling_avg = round(sum(rolling_returns) / len(rolling_returns), 2) if rolling_returns else 0
    rolling_win_rate = round(len([r for r in rolling_returns if r > 0]) / len(rolling_returns) * 100, 1) if rolling_returns else 0

    matured_wins = len([m for m in matured_results if m.get("pick_7day_return") and m["pick_7day_return"] > 0])
    matured_7day_avg = round(sum(m.get("pick_7day_return", 0) or 0 for m in matured_results) / len(matured_results), 2) if matured_results else 0
    matured_inverse_avg = round(sum(m.get("inverse_7day_return", 0) or 0 for m in matured_results) / len(matured_results), 2) if matured_results else 0
    matured_spy_avg = round(sum(m.get("spy_7day_return", 0) or 0 for m in matured_results) / len(matured_results), 2) if matured_results else 0

    runner_up_returns = [r["runner_up_pnl"] for r in results if r["runner_up_pnl"] is not None]
    wildcard_returns = [r["wildcard_pnl"] for r in results if r["wildcard_pnl"] is not None]
    inverse_returns = [r["inverse_wsb_return"] for r in results if r["inverse_wsb_return"] is not None]

    return {
        "picks": results,
        "benchmark": benchmark_price,
        "matured_picks": matured_results,
        "summary": {
            "total_picks": len(picks),
            "tracked": count,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "avg_return": avg_return,
            "avg_runner_up_return": round(sum(runner_up_returns) / len(runner_up_returns), 2) if runner_up_returns else 0,
            "avg_wildcard_return": round(sum(wildcard_returns) / len(wildcard_returns), 2) if wildcard_returns else 0,
            "avg_inverse_wsb_return": round(sum(inverse_returns) / len(inverse_returns), 2) if inverse_returns else 0,
            "inverse_wsb_win_rate": round(len([r for r in results if r.get("inverse_wsb_return") and r["inverse_wsb_return"] > 0]) / len(inverse_returns) * 100, 1) if inverse_returns else 0,
            "current_benchmark_price": benchmark_price,
            "rolling_30d_avg_return": rolling_avg,
            "rolling_30d_win_rate": rolling_win_rate,
            "matured_count": len(matured_results),
            "matured_7day_avg": matured_7day_avg,
            "matured_7day_wins": matured_wins,
            "matured_7day_win_rate": round(matured_wins / len(matured_results) * 100, 1) if matured_results else 0,
            "matured_inverse_avg": matured_inverse_avg,
            "matured_spy_avg": matured_spy_avg,
        },
    }
