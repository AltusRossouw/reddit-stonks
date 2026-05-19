import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import yfinance as yf

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("peewee").setLevel(logging.CRITICAL)
logging.getLogger("multitasking").setLevel(logging.CRITICAL)

EURO_OVERRIDES: dict[str, list[tuple[str, str]]] = {
    "MU": [("MTE.DE", "Xetra (EUR)"), ("MU.VI", "Vienna (EUR)"), ("MU.SW", "Swiss (CHF)")],
    "AMD": [("AMD.DE", "Xetra (EUR)")],
    "NVDA": [("NVD.DE", "Xetra (EUR)")],
    "MSFT": [("MSF.DE", "Xetra (EUR)")],
    "AMZN": [("AMZ.DE", "Xetra (EUR)")],
    "INTC": [("INTC.DE", "Xetra (EUR)")],
    "TSM": [("TSM.DE", "Xetra (EUR)")],
}

EURO_SUFFIXES = [
    (".DE", "Xetra"),
    (".F", "Frankfurt"),
    (".MI", "Milan"),
    (".VI", "Vienna"),
    (".PA", "Paris"),
    (".AS", "Amsterdam"),
    (".SW", "Swiss"),
    (".L", "London"),
    (".MC", "Madrid"),
]


def find_european_equivalents(us_ticker: str) -> list[dict]:
    results: list[dict] = []

    if us_ticker in EURO_OVERRIDES:
        for euro_ticker, label in EURO_OVERRIDES[us_ticker]:
            try:
                stock = yf.Ticker(euro_ticker)
                info = stock.info
                price = info.get("currentPrice") or info.get("regularMarketPrice")
                currency = info.get("currency", "?")
                if price:
                    results.append({
                        "ticker": euro_ticker,
                        "exchange": label,
                        "price": price,
                        "currency": currency,
                    })
            except Exception:
                continue
        return results

    for suffix, exchange in EURO_SUFFIXES:
        euro_ticker = f"{us_ticker}{suffix}"
        try:
            stock = yf.Ticker(euro_ticker)
            info = stock.info
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            currency = info.get("currency", "?")
            if price and currency != "USD":
                results.append({
                    "ticker": euro_ticker,
                    "exchange": exchange,
                    "price": price,
                    "currency": currency,
                })
        except Exception:
            continue
    return results


def _fetch_one(ticker: str) -> tuple:
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        history = stock.history(period="1mo")
        if history.empty or not info:
            return ticker, None

        latest = history.iloc[-1]
        week_ago = history.iloc[-5] if len(history) >= 5 else history.iloc[0]
        price = float(latest["Close"])
        week_change_pct = round((price - float(week_ago["Close"])) / float(week_ago["Close"]) * 100, 2)
        volume = int(latest.get("Volume", 0))
        avg_volume = int(history["Volume"].tail(20).mean()) if "Volume" in history else 0
        month_high = float(history["High"].max())
        month_low = float(history["Low"].min())

        return ticker, {
            "price": price,
            "currency": info.get("currency", "USD"),
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector", "N/A"),
            "industry": info.get("industry", "N/A"),
            "short_name": info.get("shortName", ticker),
            "week_change_pct": week_change_pct,
            "volume": volume,
            "avg_volume_20d": avg_volume,
            "volume_ratio": round(volume / avg_volume, 2) if avg_volume else 0,
            "month_high": month_high,
            "month_low": month_low,
            "high_from_low_pct": round((price - month_low) / month_low * 100, 2) if month_low else 0,
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "beta": info.get("beta"),
            "fifty_day_avg": info.get("fiftyDayAverage"),
            "two_hundred_day_avg": info.get("twoHundredDayAverage"),
            "recommendation": info.get("recommendationKey", "N/A"),
            "target_mean": info.get("targetMeanPrice"),
            "short_pct": info.get("shortPercentOfFloat"),
            "inst_ownership": info.get("heldPercentInstitutions"),
            "insider_ownership": info.get("heldPercentInsiders"),
        }
    except Exception:
        return ticker, None


def fetch_stock_data(tickers: list[str]) -> dict[str, dict]:
    results: dict[str, dict] = {}
    print(f"\nFetching stock data for {len(tickers)} tickers...\n")

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, data = future.result()
            if data:
                results[ticker] = data
                print(f"  ${ticker}: ${data['price']:.2f} ({data['week_change_pct']:+.2f}% wk) - {data['short_name']}")

    print(f"\nFetched data for {len(results)} tickers.")
    return results
