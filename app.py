#!/usr/bin/env python3
import asyncio
import json
import os
import re
import sys
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from reddit_scraper import scrape_all
from stock_data import fetch_stock_data, find_european_equivalents
from backtest import save_pick, compute_performance

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
app = FastAPI(title="Reddit Stonks")
TOP_N_TICKERS = 20


def extract_top_picks(analysis: str) -> list[str]:
    picks: list[str] = []
    for match in re.finditer(
        r"\*\*TOP PICK:\s*\$?(\w+)\*\*|\*\*RUNNER-UP:\s*\$?(\w+)\*\*|\*\*WILDCARD[^*]*:\s*\$?(\w+)\*\*",
        analysis,
    ):
        ticker = match.group(1) or match.group(2) or match.group(3)
        if ticker:
            picks.append(ticker)
    return picks


def parse_confidence(analysis: str) -> int:
    m = re.search(r"Confidence Score:\s*(\d+)/10", analysis, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def parse_top_ticker_price(ticker: str, stock_data: dict) -> float:
    sd = stock_data.get(ticker, {})
    return sd.get("price", 0)


def build_context(reddit_data: dict, stock_data: dict, euro: bool = False) -> str:
    ticker_counts = reddit_data["ticker_counts"]
    top_tickers = list(ticker_counts.keys())[:TOP_N_TICKERS]
    trends = reddit_data.get("trends", {})

    lines = [
        f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
        f"Total Reddit Posts Analyzed: {len(reddit_data['posts'])}",
        "",
        "=== STOCK DATA (with MOMENTUM TREND) ===",
    ]

    for ticker in top_tickers:
        sd = stock_data.get(ticker)
        if not sd:
            continue
        mentions = ticker_counts.get(ticker, 0)
        trend = trends.get(ticker, "steady")
        cap_str = f"${sd['market_cap']/1e9:.1f}B" if sd["market_cap"] else "N/A"
        target_str = f"${sd['target_mean']:.2f}" if sd.get("target_mean") else "N/A"
        short_str = f"{sd['short_pct']*100:.1f}%" if sd.get("short_pct") else "N/A"

        lines.append(
            f"${ticker} ({sd['short_name']}): "
            f"Price=${sd['price']:.2f}, "
            f"MktCap={cap_str}, "
            f"Sector={sd['sector']}, "
            f"1WkChange={sd['week_change_pct']:+.2f}%, "
            f"P/E={sd.get('pe_ratio', 'N/A')}, "
            f"FwdP/E={sd.get('forward_pe', 'N/A')}, "
            f"Beta={sd.get('beta', 'N/A')}, "
            f"50dMA={sd.get('fifty_day_avg', 'N/A')}, "
            f"200dMA={sd.get('two_hundred_day_avg', 'N/A')}, "
            f"Recommendation={sd['recommendation']}, "
            f"AnalystTarget={target_str}, "
            f"ShortFloat={short_str}, "
            f"VolRatio={sd['volume_ratio']}, "
            f"RedditMentions={mentions}, "
            f"MentionsTrend={trend} (rising=accelerating hype, falling=fading interest, new=first appearance, steady=same level)"
        )

    trending_up = [t for t in top_tickers if trends.get(t) == "rising"]
    trending_down = [t for t in top_tickers if trends.get(t) == "falling"]
    if trending_up:
        lines.append(f"\nRISING mentions (more hype this week vs last): {', '.join('$'+t for t in trending_up)}")
    if trending_down:
        lines.append(f"FALLING mentions (less hype this week vs last): {', '.join('$'+t for t in trending_down)}")

    lines.append("")
    lines.append("=== REDDIT MENTION RANKING ===")
    for ticker, count in list(ticker_counts.items())[:TOP_N_TICKERS]:
        trend_icon = {"rising": "↑", "falling": "↓", "new": "★", "steady": "→", "gone": "✗"}.get(trends.get(ticker, ""), "")
        lines.append(f"  ${ticker}: {count} mentions {trend_icon}")

    if euro:
        lines.append("")
        lines.append("=== NOTE ===")
        lines.append("Include European exchange equivalents section in your response.")

    return "\n".join(lines)


async def run_analysis(context: str) -> str:
    system_prompt = (
        "You are a senior quantitative analyst at a top hedge fund. "
        "Your specialty is combining social media sentiment analysis with "
        "fundamental and technical data to identify short-term trading opportunities. "
        "Output your analysis in clear sections with specific reasoning. "
        "Be concise and data-driven.\n\n"
        "CRITICAL: A stock with RISING mentions + strong fundamentals is a buy signal. "
        "A stock with FALLING mentions (fading hype) is a sell signal — do NOT pick these. "
        "A stock with RISING mentions but weak fundamentals is a hype trap — be skeptical. "
        "Weight fundamentals (P/E, beta, analyst consensus) at least as heavily as Reddit sentiment."
    )

    user_prompt = f"""Analyze the following data and determine which single stock has the highest probability of delivering the best return over the NEXT 7 DAYS (1 week).

Consider:
1. Reddit hype/momentum
2. Recent price action and technical setup
3. Valuation (P/E, forward P/E)
4. Short squeeze potential
5. Volume anomalies
6. Analyst sentiment and price targets
7. Sector momentum

Output format:

**TOP PICK: $TICKER**
- Rationale: (2-3 sentences)

**RUNNER-UP: $TICKER**
- Rationale: (1-2 sentences)

**WILDCARD (High Risk/Reward): $TICKER**
- Rationale: (1-2 sentences)

**Risk Factors to Watch:**
- (2-3 bullet points)

**Confidence Score: X/10**
- (1 sentence)

DATA:
{context}"""

    loop = asyncio.get_event_loop()
    try:
        response = await loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model="deepseek-v4-flash",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=1200,
            ),
        )
        return response.choices[0].message.content or "(no response)"
    except Exception as e:
        return f"Error calling Deepseek API: {e}"


async def send_event(msg_type: str, data: dict):
    yield f"data: {json.dumps({'type': msg_type, **data})}\n\n"


async def event_stream(posts_per_sub: int, euro: bool):
    try:
        yield f"data: {json.dumps({'type': 'status', 'message': 'Scraping Reddit...'})}\n\n"

        loop = asyncio.get_event_loop()
        reddit_data = await loop.run_in_executor(None, lambda: scrape_all(limit_per_sub=posts_per_sub))

        ticker_count = len(reddit_data["ticker_counts"])
        yield f"data: {json.dumps({'type': 'status', 'message': f'Found {ticker_count} unique tickers. Fetching stock data...'})}\n\n"

        top_tickers = list(reddit_data["ticker_counts"].keys())[:TOP_N_TICKERS]
        stock_data = await loop.run_in_executor(None, fetch_stock_data, top_tickers)

        yield f"data: {json.dumps({'type': 'status', 'message': f'Stock data ready for {len(stock_data)} tickers. Sending to AI...'})}\n\n"

        stock_rows = []
        for ticker in list(reddit_data["ticker_counts"].keys())[:TOP_N_TICKERS]:
            sd = stock_data.get(ticker)
            if not sd:
                continue
            stock_rows.append({
                "ticker": ticker,
                "price": sd["price"],
                "currency": sd["currency"],
                "market_cap": sd["market_cap"],
                "sector": sd["sector"],
                "short_name": sd["short_name"],
                "week_change_pct": sd["week_change_pct"],
                "pe_ratio": sd.get("pe_ratio"),
                "forward_pe": sd.get("forward_pe"),
                "beta": sd.get("beta"),
                "volume_ratio": sd["volume_ratio"],
                "short_pct": sd.get("short_pct"),
                "recommendation": sd["recommendation"],
                "target_mean": sd.get("target_mean"),
                "mentions": reddit_data["ticker_counts"].get(ticker, 0),
                "trend": reddit_data.get("trends", {}).get(ticker, "steady"),
            })

        context = build_context(reddit_data, stock_data, euro=euro)
        analysis = await run_analysis(context)

        picks = extract_top_picks(analysis)
        top_ticker = picks[0] if len(picks) > 0 else ""
        runner_ticker = picks[1] if len(picks) > 1 else ""
        wildcard_ticker = picks[2] if len(picks) > 2 else ""

        save_pick(
            top_pick=top_ticker,
            top_price=parse_top_ticker_price(top_ticker, stock_data),
            runner_up=runner_ticker,
            runner_up_price=parse_top_ticker_price(runner_ticker, stock_data),
            wildcard=wildcard_ticker,
            wildcard_price=parse_top_ticker_price(wildcard_ticker, stock_data),
            confidence=parse_confidence(analysis),
            posts_scraped=len(reddit_data["posts"]),
            tickers_found=len(reddit_data["ticker_counts"]),
            analysis=analysis,
        )

        euro_data = []
        if euro:
            picks = extract_top_picks(analysis)
            for us_ticker in picks:
                eq = await loop.run_in_executor(None, find_european_equivalents, us_ticker)
                euro_data.append({"us_ticker": us_ticker, "equivalents": eq})

        yield f"data: {json.dumps({'type': 'result', 'stocks': stock_rows, 'analysis': analysis, 'euro': euro_data})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"


@app.get("/api/analyze")
async def analyze(
    posts: int = Query(25, ge=10, le=25),
    euro: bool = Query(False),
):
    return StreamingResponse(
        event_stream(posts, euro),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/")
async def index():
    return HTMLResponse(open("static/index.html").read())


@app.get("/app")
async def app_page():
    return HTMLResponse(open("static/app.html").read())


@app.get("/track-record")
async def track_record_page():
    return HTMLResponse(open("static/track-record.html").read())


@app.get("/api/track-record")
async def track_record_api():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, compute_performance)


app.mount("/static", StaticFiles(directory="static"), name="static")
