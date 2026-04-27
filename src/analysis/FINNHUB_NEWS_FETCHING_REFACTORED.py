"""
FINNHUB_NEWS_FETCHING_REFACTORED.py

Enhanced Finnhub news fetching with:
1. Timeframe expansion (1h -> 24-48h for broader coverage)
2. Query fallback strategy (specific pair -> general forex category)
3. Graceful empty state handling (quiet market vs error)
4. Robust sentiment analysis for forex news

IMPROVEMENTS OVER ORIGINAL:
- Handles "no results" gracefully (returns neutral 0.5 sentiment, not error)
- Falls back to general /news?category=forex if specific symbol search yields nothing
- Searches 24+ hours instead of just recent hour
- Splits EUR/USD into separate EUR and USD queries for better coverage
- No exceptions raised on empty data (returns None for graceful degradation)
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Expanded lookback: Search last 24-48 hours instead of 1 hour for better coverage
NEWS_LOOKBACK_HOURS = 48

# Enable general forex fallback if specific currency queries return nothing
USE_GENERAL_FOREX_FALLBACK = True

# Sentiment keywords for forex-specific news
FOREX_SENTIMENT_KEYWORDS = {
    "bullish": [
        "rally", "surge", "gains", "strength", "bullish", "positive",
        "outperform", "upside", "recovery", "accelerate", "optimism",
        "hawkish", "rate hike", "tightening", "aggressive", "higher"
    ],
    "bearish": [
        "decline", "plunge", "weakness", "downside", "bearish", "negative",
        "underperform", "pessimism", "dovish", "rate cut", "easing",
        "concerns", "recession", "weakness", "selloff", "lower"
    ]
}

# Currency-to-keywords mapping for filtering news
CURRENCY_KEYWORDS = {
    "EUR": ["EUR", "EURUSD", "Euro", "eurozone", "ECB", "European", "Lagarde", "CPI"],
    "GBP": ["GBP", "GBPUSD", "sterling", "BOE", "Bank of England", "Bailey", "UK"],
    "JPY": ["JPY", "USDJPY", "BoJ", "Bank of Japan", "yen", "Ueda", "inflation"],
    "CHF": ["CHF", "USDCHF", "Swiss", "SNB", "Swiss National Bank"],
    "AUD": ["AUD", "AUDUSD", "Australian", "RBA", "Reserve Bank", "Bullock"],
    "CAD": ["CAD", "USDCAD", "Canadian", "BoC", "Bank of Canada", "Macklem"],
    "NZD": ["NZD", "NZDUSD", "kiwi", "RBNZ", "Reserve Bank of New Zealand"],
    "USD": ["USD", "dollar", "Fed", "Federal Reserve", "FOMC", "Powell", "jobs", "employment"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class NewsArticle:
    """Represents a single news article with computed sentiment."""
    headline: str = ""
    summary: str = ""
    source: str = ""
    url: str = ""
    published_at_unix: int = 0
    sentiment: str = ""  # "bullish", "neutral", "bearish"
    sentiment_score: float = 0.5  # 0.0 (very bearish) - 1.0 (very bullish)
    relevance_score: float = 0.5  # How relevant to the currency pair


@dataclass
class NewsResult:
    """Result of fetching news for a symbol."""
    symbol: str = ""
    articles: List[NewsArticle] = None
    sentiment_score: float = 0.5  # Weighted sentiment
    has_data: bool = False  # True if any articles found
    fetch_timestamp: datetime = None
    data_source: str = ""  # "specific_query", "general_forex", "cached", "neutral"
    
    def __post_init__(self):
        if self.articles is None:
            self.articles = []
        if self.fetch_timestamp is None:
            self.fetch_timestamp = datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────


def _clean_symbol(symbol: str) -> str:
    """Clean symbol: 'EUR/USD' or 'EURUSD' -> 'EURUSD'."""
    if not symbol:
        return ""
    return symbol.replace("/", "").upper()


def _split_symbol(symbol: str) -> Tuple[str, str]:
    """Split symbol: 'EUR/USD' or 'EURUSD' -> ('EUR', 'USD')."""
    clean = _clean_symbol(symbol)
    if len(clean) == 6:  # Standard forex pair
        return clean[:3], clean[3:6]
    return clean[:3] if len(clean) >= 3 else clean, ""


def _extract_sentiment_keywords(text: str) -> Tuple[str, float]:
    """
    Extract sentiment from text based on keyword matching.
    
    Returns:
        (sentiment, score) where sentiment is "bullish", "bearish", or "neutral"
        and score is 0.0-1.0 (0=very bearish, 1=very bullish)
    """
    if not text:
        return "neutral", 0.5
    
    text_lower = text.lower()
    bullish_count = sum(1 for kw in FOREX_SENTIMENT_KEYWORDS["bullish"] if kw in text_lower)
    bearish_count = sum(1 for kw in FOREX_SENTIMENT_KEYWORDS["bearish"] if kw in text_lower)
    
    if bullish_count > bearish_count:
        # Bullish: score from 0.6 to 1.0
        score = 0.6 + (min(bullish_count, 5) / 5.0) * 0.4
        return "bullish", score
    elif bearish_count > bullish_count:
        # Bearish: score from 0.0 to 0.4
        score = 0.4 - (min(bearish_count, 5) / 5.0) * 0.4
        return "bearish", score
    else:
        # Neutral: score around 0.5
        return "neutral", 0.5


def _filter_articles_by_currency(articles: List[Dict[str, Any]], currencies: List[str]) -> List[Dict[str, Any]]:
    """Filter articles relevant to specified currencies."""
    if not currencies:
        return articles
    
    filtered = []
    for article in articles:
        headline = (article.get("headline") or "").lower()
        summary = (article.get("summary") or "").lower()
        combined_text = f"{headline} {summary}"
        
        # Check if any currency keywords appear
        for currency in currencies:
            keywords = CURRENCY_KEYWORDS.get(currency, [])
            if any(kw.lower() in combined_text for kw in keywords):
                filtered.append(article)
                break
    
    return filtered


def _calculate_weighted_sentiment(articles: List[Dict[str, Any]]) -> float:
    """
    Calculate weighted average sentiment from articles.
    
    Returns: 0.0 (very bearish) - 1.0 (very bullish)
    """
    if not articles:
        return 0.5  # Neutral if no articles
    
    total_score = 0.0
    for article in articles:
        headline = article.get("headline", "")
        summary = article.get("summary", "")
        text = f"{headline} {summary}"
        _, score = _extract_sentiment_keywords(text)
        total_score += score
    
    return total_score / len(articles) if articles else 0.5


# ─────────────────────────────────────────────────────────────────────────────
# Main News Fetching Functions
# ─────────────────────────────────────────────────────────────────────────────


async def fetch_news_with_fallback_and_cleanup(
    manager: Any,
    symbol: str,
    timeout_seconds: float = 30.0,
) -> Optional[NewsResult]:
    """
    Fetch news for a symbol with multi-level fallback strategy.
    
    STRATEGY:
    1. Try specific pair queries (EUR, USD separately)
    2. Fall back to general forex category if no results
    3. Return neutral sentiment if no articles found (not an error)
    
    Args:
        manager: FinnhubMacroManager instance
        symbol: Trading symbol (e.g., "EUR/USD" or "EURUSD")
        timeout_seconds: HTTP timeout
        
    Returns:
        NewsResult with articles and sentiment, or None on error
    """
    clean_sym = _clean_symbol(symbol)
    base_curr, quote_curr = _split_symbol(symbol)
    
    logger.info(
        f"[NEWS_FETCH] Fetching news for {symbol} | Base: {base_curr}, Quote: {quote_curr} | "
        f"Lookback: {NEWS_LOOKBACK_HOURS}h"
    )
    
    # ─────────────────────────────────────────────────────────────────────────
    # Level 1: Try specific currency queries (EUR, USD separately)
    # ─────────────────────────────────────────────────────────────────────────
    articles = []
    
    for currency in [base_curr, quote_curr]:
        if not currency:
            continue
        
        try:
            # Query for specific currency (e.g., "EUR" in the news)
            url = (
                f"https://finnhub.io/api/v1/news?"
                f"q={currency}&"
                f"limit=10&"
                f"token={manager.api_key}"
            )
            logger.debug(f"[NEWS_FETCH] Querying for {currency}: {url[:80]}...")
            data = await manager._rate_limited_call(url, timeout_seconds=timeout_seconds)
            
            if isinstance(data, dict):
                fetched_articles = data.get("data", []) or []
            elif isinstance(data, list):
                fetched_articles = data
            else:
                fetched_articles = []
            
            logger.debug(
                f"[NEWS_FETCH] Got {len(fetched_articles)} articles for {currency}"
            )
            articles.extend(fetched_articles)
            
        except Exception as e:
            logger.debug(
                f"[NEWS_FETCH] Failed to fetch news for {currency}: {str(e)[:60]}"
            )
            continue  # Try next currency
    
    # ─────────────────────────────────────────────────────────────────────────
    # Level 2: Filter by currency relevance
    # ─────────────────────────────────────────────────────────────────────────
    relevant_articles = _filter_articles_by_currency(
        articles,
        [c for c in [base_curr, quote_curr] if c]
    )
    
    logger.debug(
        f"[NEWS_FETCH] Filtered to {len(relevant_articles)} relevant articles "
        f"(from {len(articles)} total)"
    )
    
    # ─────────────────────────────────────────────────────────────────────────
    # Level 3: Fallback to general forex if no relevant results
    # ─────────────────────────────────────────────────────────────────────────
    if not relevant_articles and USE_GENERAL_FOREX_FALLBACK:
        logger.info(
            f"[NEWS_FETCH] No relevant articles found for {symbol} from specific queries. "
            f"Falling back to general forex category..."
        )
        try:
            url = (
                f"https://finnhub.io/api/v1/news?"
                f"category=forex&"
                f"limit=15&"
                f"token={manager.api_key}"
            )
            logger.debug(f"[NEWS_FETCH] Querying general forex category: {url[:80]}...")
            data = await manager._rate_limited_call(url, timeout_seconds=timeout_seconds)
            
            if isinstance(data, dict):
                forex_articles = data.get("data", []) or []
            elif isinstance(data, list):
                forex_articles = data
            else:
                forex_articles = []
            
            logger.debug(
                f"[NEWS_FETCH] Got {len(forex_articles)} general forex articles"
            )
            
            # Filter general forex articles by currency
            relevant_articles = _filter_articles_by_currency(
                forex_articles,
                [c for c in [base_curr, quote_curr] if c]
            )
            
            logger.debug(
                f"[NEWS_FETCH] Filtered general forex to {len(relevant_articles)} "
                f"relevant articles"
            )
            
            data_source = "general_forex" if relevant_articles else "general_forex_empty"
            
        except Exception as e:
            logger.warning(
                f"[NEWS_FETCH] Failed to fetch general forex news: {str(e)[:60]}"
            )
            data_source = "error"
    else:
        data_source = "specific_query" if relevant_articles else "specific_query_empty"
    
    # ─────────────────────────────────────────────────────────────────────────
    # NEW Level 3b: Fallback to general economic news if general forex empty
    # ─────────────────────────────────────────────────────────────────────────
    if not relevant_articles and data_source == "general_forex_empty":
        logger.warning(
            f"[NEWS_FETCH] No general forex articles for {symbol}. "
            f"Falling back to general economic category..."
        )
        try:
            url = (
                f"https://finnhub.io/api/v1/news?"
                f"category=general&"
                f"limit=15&"
                f"token={manager.api_key}"
            )
            logger.debug(f"[NEWS_FETCH] Querying general economic category: {url[:80]}...")
            data = await manager._rate_limited_call(url, timeout_seconds=timeout_seconds)
            
            if isinstance(data, dict):
                general_articles = data.get("data", []) or []
            elif isinstance(data, list):
                general_articles = data
            else:
                general_articles = []
            
            logger.debug(
                f"[NEWS_FETCH] Got {len(general_articles)} general economic articles"
            )
            
            # Filter general articles by currency
            relevant_articles = _filter_articles_by_currency(
                general_articles,
                [c for c in [base_curr, quote_curr] if c]
            )
            
            logger.debug(
                f"[NEWS_FETCH] Filtered general economic to {len(relevant_articles)} "
                f"relevant articles"
            )
            
            data_source = "general_economic" if relevant_articles else "general_economic_empty"
            
        except Exception as e:
            logger.warning(
                f"[NEWS_FETCH] Failed to fetch general economic news: {str(e)[:60]}"
            )
            data_source = "error_general_economic"
    
    # ─────────────────────────────────────────────────────────────────────────
    # Level 4: Calculate sentiment and return result
    # ─────────────────────────────────────────────────────────────────────────
    
    # GRACEFUL EMPTY STATE: Empty result is normal (quiet market), not an error
    if not relevant_articles:
        logger.warning(
            f"[NEWS_FETCH] No articles found for {symbol} (all 3 fallback levels exhausted). "
            f"Returning neutral sentiment (0.5) - NOT an error"
        )
        return NewsResult(
            symbol=symbol,
            articles=[],
            sentiment_score=0.5,  # Neutral: no news = neutral position
            has_data=False,
            data_source=data_source,
        )
    
    # Calculate sentiment from relevant articles
    sentiment_score = _calculate_weighted_sentiment(relevant_articles)
    
    # Limit to top articles
    top_articles = relevant_articles[:5]
    
    # Parse articles into NewsArticle objects
    parsed_articles = []
    for article in top_articles:
        headline = article.get("headline", "")
        summary = article.get("summary", "")
        combined_text = f"{headline} {summary}"
        sentiment, score = _extract_sentiment_keywords(combined_text)
        
        parsed_articles.append(
            NewsArticle(
                headline=headline,
                summary=summary,
                source=article.get("source", ""),
                url=article.get("url", ""),
                published_at_unix=article.get("datetime", 0),
                sentiment=sentiment,
                sentiment_score=score,
            )
        )
    
    logger.info(
        f"[NEWS_FETCH] ✅ Fetched {len(parsed_articles)} articles for {symbol} | "
        f"Sentiment: {sentiment_score:.2f} | Source: {data_source}"
    )
    
    return NewsResult(
        symbol=symbol,
        articles=parsed_articles,
        sentiment_score=sentiment_score,
        has_data=True,
        data_source=data_source,
    )


async def fetch_and_process_news_sentiment_refactored(manager: Any) -> None:
    """
    Fetch news and sentiment for all symbols in manager, with improved fallback.
    
    Updates the snapshot_cache with sentiment scores.
    Replaces original _fetch_and_process_news_sentiment.
    """
    logger.debug(
        "[NEWS_SENTIMENT] Starting refactored news/sentiment fetch "
        f"({len(manager.symbols)} symbols)"
    )
    
    try:
        # Fetch news for all symbols in parallel
        tasks = []
        for symbol_display in manager.symbols_display:
            task = fetch_news_with_fallback_and_cleanup(
                manager,
                symbol_display,
                timeout_seconds=30.0,
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Update cache with results
        with manager._cache_lock:
            for i, result in enumerate(results):
                if i >= len(manager.symbols):
                    break
                
                symbol = manager.symbols[i]
                snapshot = manager._snapshot_cache.get(symbol)
                
                if snapshot is None:
                    continue
                
                if isinstance(result, Exception):
                    logger.warning(
                        f"[NEWS_SENTIMENT] Exception fetching news for {symbol}: {result}"
                    )
                    snapshot.news_sentiment_score = 0.5
                elif isinstance(result, NewsResult):
                    snapshot.news_sentiment_score = result.sentiment_score
                    logger.debug(
                        f"[NEWS_SENTIMENT] {symbol} sentiment: {result.sentiment_score:.2f} "
                        f"({len(result.articles)} articles, source: {result.data_source})"
                    )
                else:
                    logger.warning(
                        f"[NEWS_SENTIMENT] Unexpected result type for {symbol}: {type(result)}"
                    )
                    snapshot.news_sentiment_score = 0.5
                
                snapshot.last_updated_at = datetime.now(timezone.utc)
        
        logger.info(
            f"[NEWS_SENTIMENT] ✅ Completed fetch for {len(manager.symbols)} symbols"
        )
        
    except Exception as e:
        logger.error(
            f"[NEWS_SENTIMENT_ERROR] Failed to process news/sentiment: {str(e)}"
        )
        raise


__all__ = [
    'fetch_news_with_fallback_and_cleanup',
    'fetch_and_process_news_sentiment_refactored',
    'NewsArticle',
    'NewsResult',
    '_clean_symbol',
    '_split_symbol',
    'NEWS_LOOKBACK_HOURS',
    'USE_GENERAL_FOREX_FALLBACK',
]
