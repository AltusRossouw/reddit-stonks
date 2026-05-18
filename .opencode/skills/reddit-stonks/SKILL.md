---
name: reddit-stonks
description: Scrape Reddit stock pages (r/wallstreetbets, r/stocks, etc.) and use Deepseek AI to analyze which stock has the highest 1-week return potential. Use when the user asks about stock picks, Reddit stock sentiment, meme stocks, investing ideas from Reddit, "what should I buy", "best stock this week", or similar. Supports --euro flag for European exchange equivalents.
---

# Reddit Stonks Analyzer

Analyze Reddit stock sentiment + AI-powered stock picks for short-term returns.

## Quickstart

```bash
# Standard run
python3 stonks.py

# Fewer posts (faster), with European equivalents
python3 stonks.py -p 25 -e

# Fast run
python3 stonks.py -p 10
```

## Flags

| Flag | Description |
|------|-------------|
| `-e`, `--euro` | Show European exchange equivalents for top picks |
| `-p N`, `--posts N` | Posts per subreddit (default: 50) |

## Setup (first time only)

```bash
cp .env.example .env
# Edit .env: add DEEPSEEK_API_KEY
pip install -r requirements.txt
```

## Architecture

- `stonks.py` — orchestrator + AI analysis via Deepseek
- `reddit_scraper.py` — scrapes 7 subreddits via Reddit JSON API (no auth)
- `stock_data.py` — fetches fundamentals/technicals via Yahoo Finance + European ticker lookup

## Output

Generates a stock data table, then AI analysis with:
- Top Pick (best 1-week return)
- Runner-up
- Wildcard (high risk/reward)
- Risk factors
- Confidence score
