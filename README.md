# Reddit Stonks

Scrape Reddit stock pages + AI-powered analysis to find the best stock for a 1-week return.

## How it works

1. **Scrapes** 7 stock-related subreddits (r/wallstreetbets, r/stocks, r/investing, etc.) for hot posts
2. **Extracts** stock tickers from post titles and bodies
3. **Fetches** real-time stock data via Yahoo Finance (price, P/E, beta, volume, short float, analyst targets)
4. **Analyzes** everything with Deepseek AI to identify the single best stock for a 7-day return

## Quickstart

```bash
# 1. Install
pip install -r requirements.txt

# 2. Add your Deepseek API key
cp .env.example .env
# Edit .env: DEEPSEEK_API_KEY=sk-your-key

# 3. Run
python3 stonks.py

# With European exchange equivalents
python3 stonks.py -e

# Fast run (fewer posts)
python3 stonks.py -p 10
```

## Flags

| Flag | Description |
|------|-------------|
| `-e`, `--euro` | Show European exchange equivalents (Xetra, Vienna, etc.) |
| `-p N`, `--posts N` | Posts per subreddit (default: 50) |

## Output

- Stock data table with all relevant metrics
- AI analysis: Top Pick, Runner-up, Wildcard, Risk Factors, Confidence Score
- Optional European equivalents with tickers and exchanges

## Files

| File | Purpose |
|------|---------|
| `stonks.py` | Main orchestrator + AI analysis |
| `reddit_scraper.py` | Reddit JSON API scraper (no auth required) |
| `stock_data.py` | Yahoo Finance data + European ticker lookup |

## Disclaimer

AI-generated analysis for entertainment/educational purposes only. Not financial advice.
