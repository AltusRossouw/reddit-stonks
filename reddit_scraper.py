import re
import time
import json
import os
from collections import Counter
from datetime import datetime, timedelta

import requests

CACHE_FILE = "trend_cache.json"
CACHE_TTL_HOURS = 6

SUBREDDITS = [
    "wallstreetbets",
    "stocks",
    "investing",
    "pennystocks",
    "StockMarket",
    "thetagang",
    "dividends",
]

COMMON_FALSE_TICKERS = {
    "A", "I", "DD", "CEO", "CFO", "CTA", "ETF", "AI", "IPO", "YOLO",
    "IT", "EV", "FDA", "USA", "USD", "GDP", "CPI", "FOMC", "EPS",
    "IMO", "FYI", "TLDR", "PSA", "EDIT", "LMAO", "ROFL", "FUD",
    "HODL", "ATH", "BTFD", "DTF", "ELI5", "FOMO", "GAINS", "LOSS",
    "OTM", "ITM", "PM", "AH", "EOD", "ETF", "REIT", "SPAC", "BOGO",
    "GOAT", "OG", "OP", "TOS", "NYSE", "NASDAQ", "SEC", "FINRA",
    "IRA", "ROTH", "DTCC", "NSCC", "OCC", "CBOE", "CME", "ICE",
    "IS", "BE", "ARE", "AM", "PM", "OR", "ON", "IN", "AT", "TO",
    "FOR", "BY", "MY", "SO", "DO", "GO", "NO", "WE", "HE", "ME",
    "ALL", "ANY", "BIG", "NEW", "OLD", "LOW", "HIGH", "TOP",
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG",
    "SEP", "OCT", "NOV", "DEC", "MON", "TUE", "WED", "THU",
    "FRI", "SAT", "SUN", "RH", "TD", "IB", "TDA", "IRS",
}

USER_AGENT = "RedditStonks/1.0 (analysis bot)"


def _is_likely_ticker(word: str) -> bool:
    return (
        2 <= len(word) <= 5
        and word.isalpha()
        and word.isupper()
        and word not in COMMON_FALSE_TICKERS
    )


def extract_tickers(text: str) -> list[str]:
    tickers: list[str] = []

    dollar_matches = re.findall(r"\$([A-Z]{1,5})\b", text)
    tickers.extend(dollar_matches)

    words = re.findall(r"\b[A-Z]{2,5}\b", text)
    for w in words:
        if w in dollar_matches:
            continue
        if _is_likely_ticker(w):
            tickers.append(w)

    return tickers


def _parse_utc(ts: float) -> datetime:
    return datetime.utcfromtimestamp(ts)


def scrape_subreddit(subreddit: str, limit: int = 50) -> list[dict]:
    url = f"https://www.reddit.com/r/{subreddit}/hot.json"
    headers = {"User-Agent": USER_AGENT}
    params: dict = {"limit": limit, "t": "week"}

    posts: list[dict] = []
    after: str | None = None
    fetched = 0

    while fetched < limit:
        if after:
            params["after"] = after
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"  [!] r/{subreddit} returned HTTP {resp.status_code}")
            break

        data = resp.json()
        children = data.get("data", {}).get("children", [])
        if not children:
            break

        for child in children:
            post_data = child["data"]
            created = _parse_utc(post_data["created_utc"])
            posts.append({
                "subreddit": subreddit,
                "title": post_data.get("title", ""),
                "selftext": post_data.get("selftext", ""),
                "score": post_data.get("score", 0),
                "num_comments": post_data.get("num_comments", 0),
                "upvote_ratio": post_data.get("upvote_ratio", 0),
                "created": created.isoformat(),
                "url": f"https://reddit.com{post_data.get('permalink', '')}",
            })
            fetched += 1
            if fetched >= limit:
                break

        after = data.get("data", {}).get("after")
        if not after:
            break
        time.sleep(1.0)

    return posts


def compute_trends(current_counts: dict, prior_counts: dict) -> dict[str, str]:
    trends: dict[str, str] = {}
    all_tickers = set(current_counts.keys()) | set(prior_counts.keys())

    for ticker in all_tickers:
        curr = current_counts.get(ticker, 0)
        prior = prior_counts.get(ticker, 0)
        if curr > prior * 1.5:
            trends[ticker] = "rising"
        elif prior > curr * 1.5:
            trends[ticker] = "falling"
        elif curr > 0 and prior == 0:
            trends[ticker] = "new"
        elif curr > 0:
            trends[ticker] = "steady"
        else:
            trends[ticker] = "gone"

    return trends


def scrape_prior_week(subreddit: str, limit: int = 50) -> list[dict]:
    """Scrape posts from 7-14 days ago for trend comparison."""
    url = f"https://www.reddit.com/r/{subreddit}/top.json"
    headers = {"User-Agent": USER_AGENT}
    params: dict = {"limit": limit, "t": "month"}

    posts: list[dict] = []
    cutoff_old = datetime.utcnow() - timedelta(days=14)
    cutoff_new = datetime.utcnow() - timedelta(days=7)
    fetched = 0

    while fetched < limit:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            break
        data = resp.json()
        children = data.get("data", {}).get("children", [])
        if not children:
            break
        for child in children:
            post_data = child["data"]
            created = _parse_utc(post_data["created_utc"])
            if cutoff_old <= created <= cutoff_new:
                posts.append({
                    "subreddit": subreddit,
                    "title": post_data.get("title", ""),
                    "selftext": post_data.get("selftext", ""),
                    "created": created.isoformat(),
                })
                fetched += 1
            if fetched >= limit:
                break
        after = data.get("data", {}).get("after")
        if not after:
            break
        params["after"] = after
        time.sleep(1.0)
    return posts


def _load_trend_cache() -> tuple[dict, float]:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                data = json.load(f)
            return data.get("counts", {}), data.get("ts", 0)
        except (json.JSONDecodeError, KeyError):
            pass
    return {}, 0


def _save_trend_cache(counter: Counter):
    with open(CACHE_FILE, "w") as f:
        json.dump({"counts": dict(counter), "ts": time.time()}, f)


def scrape_prior_period(limit_per_sub: int = 50) -> Counter:
    cached_counts, cached_ts = _load_trend_cache()
    if cached_counts and (time.time() - cached_ts) < CACHE_TTL_HOURS * 3600:
        print(f"\n  Using cached trend data ({len(cached_counts)} tickers)")
        return Counter(cached_counts)

    counter: Counter = Counter()
    for sub in SUBREDDITS:
        print(f"  r/{sub} (prior week)...", end=" ", flush=True)
        posts = scrape_prior_week(sub, limit=limit_per_sub)
        print(f"{len(posts)} posts")
        for post in posts:
            full_text = f"{post['title']} {post['selftext']}"
            for t in set(extract_tickers(full_text)):
                counter[t] += 1
        time.sleep(1.5)

    _save_trend_cache(counter)
    return counter


def scrape_all(limit_per_sub: int = 50) -> dict:
    print(f"\nScraping {len(SUBREDDITS)} subreddits "
          f"(~{limit_per_sub} posts each)...\n")

    all_posts: list[dict] = []
    ticker_counter: Counter = Counter()
    ticker_posts: dict[str, list[dict]] = {}

    for sub in SUBREDDITS:
        print(f"  r/{sub} ...", end=" ", flush=True)
        posts = scrape_subreddit(sub, limit=limit_per_sub)
        print(f"{len(posts)} posts")

        for post in posts:
            all_posts.append(post)
            full_text = f"{post['title']} {post['selftext']}"
            tickers = extract_tickers(full_text)
            for t in set(tickers):
                ticker_counter[t] += 1
                if t not in ticker_posts:
                    ticker_posts[t] = []
                ticker_posts[t].append(post)

        time.sleep(2.0)

    print(f"\nTotal posts scraped: {len(all_posts)}")
    print(f"Unique tickers found: {len(ticker_counter)}")

    ranked = ticker_counter.most_common(30)
    print("\nTop mentioned tickers:")
    for ticker, count in ranked[:15]:
        print(f"  ${ticker}: {count} mentions")

    print("\nCollecting prior week data for trend comparison...")
    prior_counter = scrape_prior_period(limit_per_sub=limit_per_sub)
    trends = compute_trends(ticker_counter, prior_counter)

    rising = [t for t, tr in trends.items() if tr == "rising"]
    falling = [t for t, tr in trends.items() if tr == "falling"]
    new = [t for t, tr in trends.items() if tr == "new"]
    print(f"  Rising: {len(rising)}, Falling: {len(falling)}, New: {len(new)}")

    return {
        "posts": all_posts,
        "ticker_counts": dict(ranked),
        "ticker_posts": ticker_posts,
        "trends": trends,
    }
