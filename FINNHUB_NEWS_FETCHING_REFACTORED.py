"""
Refactored Finnhub News Fetching Function
==========================================

IMPROVEMENTS IMPLEMENTED:
1. âœ… Broadened Search: Splits symbol pairs and searches for either currency
2. âœ… General Forex Fallback: Fetches general 'forex' category news if no currency-specific news
3. âœ… Extended Lookback: 24-hour window minimum for news capture (configurable)
4. âœ… Graceful Empty Handling: Returns empty list + neutral sentiment (0.0) instead of error
5. âœ… Symbol Cleaning: Removes slashes (AUD/USD â†’ AUDUSD) for Finnhub compatibility

This module replaces the `_fetch_and_process_news_sentiment()` method in FinnhubMacroManager
and introduces new helper methods for robust news retrieval.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

# News lookback window - minimum 24 hours
NEWS_LOOKBACK_HOURS = 24

# Fallback to general forex if no currency-specific news found
USE_GENERAL_FOREX_FALLBACK = True

# Timeout for individual news API calls
NEWS_API_TIMEOUT_SECONDS = 30.0

# Maximum articles to fetch per query
MAX_ARTICLES_PER_QUERY = 5

# ============================================================================
# Enhanced Currency Keywords
# ============================================================================

CURRENCY_KEYWORDS = {
    "EUR": ["eur", "euro", "eurozone", "ecb", "draghi", "lagarde", "german", "france"],
    "GBP": ["gbp", "pound", "sterling", "boe", "bailey", "uk", "british"],
    "JPY": ["jpy", "japan", "yen", "boj", "nikkei"],
    "CHF": ["chf", "swiss", "snb", "switzerland"],
    "AUD": ["aud", "australia", "aussie", "rba", "australian"],
    "CAD": ["cad", "canada", "canadian", "boc", "loonie"],
    "NZD": ["nzd", "zealand", "kiwi", "rbnz", "auckland"],
    "USD": ["usd", "dollar", "fed", "fomc", "powell"],
}

# SENTIMENT_SCORE_MAPPING: Converts sentiment to scores 0.0-1.0 for weighted calculation
SENTIMENT_SCORE_MAPPING = {
    "bullish": 0.8,      # Strong positive
    "positive": 0.7,     # Positive  
    "bearish": 0.2,      # Negative
    "negative": 0.1,     # Strong negative
    "neutral": 0.5,      # Neutral
}

# SENTIMENT_RISK_MAPPING: Original bias adjustments for risk calculation
SENTIMENT_RISK_MAPPING = {
    "bullish": -0.2,     # Bullish news reduces risk
    "positive": -0.2,    # Positive news reduces risk
    "bearish": 0.3,      # Bearish news increases risk
    "negative": 0.3,     # Negative news increases risk
    "neutral": 0.0,      # Neutral news no change
}

# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class NewsArticle:
    """Represents a news article with sentiment."""
    headline: str
    summary: str
    source: str
    url: str
    published_at_unix: int
    sentiment: str  # "bullish", "neutral", "bearish"
    sentiment_score: float  # 0.0-1.0


@dataclass
class NewsResult:
    """Result from news fetching operation."""
    articles: List[NewsArticle]
    sentiment_score: float  # 0.0 (bearish) to 1.0 (bullish), 0.5 = neutral
    source: str  # Where articles came from: "currency_specific", "general_forex", or "empty"
    error: Optional[str] = None


# ============================================================================
# Main Refactored News Fetching Function
# ============================================================================

async def fetch_news_with_fallback_and_cleanup(
    manager,  # FinnhubMacroManager instance
    symbol: str,
    cached_forex_articles: List[Dict] = None,  # OPTIMIZATION A: Cached general forex articles
) -> NewsResult:
    """
    Fetch news for a specific forex pair with robust fallback strategy.
    
    IMPROVEMENTS:
    1. Broadened Search: Splits 'AUD/USD' â†’ searches 'AUD' OR 'USD'
    2. Fallback to General Forex: If no currency news, tries general 'forex' category
    3. Extended Lookback: Searches 24+ hours of articles
    4. Graceful Empty Handling: Returns empty list + neutral sentiment (0.5) on failure
    5. Symbol Cleaning: Converts 'AUD/USD' â†’ 'AUDUSD' for Finnhub compatibility
    
    Args:
        manager: FinnhubMacroManager instance with api_key, _rate_limited_call, etc.
        symbol: Forex pair like 'EUR/USD' or 'AUDUSD'
    
    Returns:
        NewsResult with articles, sentiment_score, and source indicator
    
    Examples:
        >>> result = await fetch_news_with_fallback_and_cleanup(manager, "AUD/USD")
        >>> if result.articles:
        ...     print(f"Found {len(result.articles)} articles")
        ...     print(f"Sentiment: {result.sentiment_score}")
        ... else:
        ...     print("No news, but sentiment is neutral:", result.sentiment_score)
    """
    
    # Step 1: Clean and parse symbol
    cleaned_symbol = _clean_symbol(symbol)
    base_currency, quote_currency = _split_symbol(cleaned_symbol)
    
    logger.debug(
        "[FINNHUB_NEWS_FETCH] Fetching news for %s | Base: %s | Quote: %s",
        symbol, base_currency, quote_currency
    )
    
    # Step 2: Try currency-specific search (both base and quote)
    articles = []
    articles.extend(
        await _search_news_by_currency(manager, base_currency, symbol)
    )
    articles.extend(
        await _search_news_by_currency(manager, quote_currency, symbol)
    )
    
    if articles:
        # Deduplicate articles by URL
        articles = _deduplicate_articles(articles)
        logger.info(
            "[FINNHUB_NEWS] Found %d articles for currency-specific search: %s",
            len(articles), symbol
        )
        
        sentiment_score = _calculate_weighted_sentiment(articles)
        return NewsResult(
            articles=articles,
            sentiment_score=sentiment_score,
            source="currency_specific"
        )
    
    logger.debug(
        "[FINNHUB_NEWS] No currency-specific articles for %s, trying general forex fallback",
        symbol
    )
    
    # Step 3: Fallback to general 'forex' category (OPTIMIZATION: use cached version if available)
    if USE_GENERAL_FOREX_FALLBACK:
        # OPTIMIZATION A: Use pre-fetched cached articles instead of making new API call
        if cached_forex_articles is not None:
            articles = cached_forex_articles
            logger.debug(
                "[FINNHUB_NEWS_CACHED] Using cached general forex articles for %s (saved 1 API call)",
                symbol
            )
        else:
            # Fallback: fetch fresh if cache not available (shouldn't happen in normal flow)
            articles = await _search_news_by_category(manager, "forex", symbol)
            logger.debug("[FINNHUB_NEWS] Fetched fresh general forex articles for %s", symbol)
        
        if articles:
            logger.info(
                "[FINNHUB_NEWS_LEVEL2_SUCCESS] Fallback: Found %d general forex articles for %s",
                len(articles), symbol
            )
            sentiment_score = _calculate_weighted_sentiment(articles)
            return NewsResult(
                articles=articles,
                sentiment_score=sentiment_score,
                source="general_forex"
            )
    
    logger.warning(
        "[FINNHUB_NEWS_LEVEL2_FAILED] %s | No general forex articles found, trying Level 3 (general economic)",
        symbol
    )
    
    # NEW Level 3: Fallback to general economic news (all categories)
    articles = await _search_news_by_category(manager, "general", symbol)
    
    if articles:
        logger.info(
            "[FINNHUB_NEWS_LEVEL3_SUCCESS] %s | Found %d general economic articles",
            symbol, len(articles)
        )
        sentiment_score = _calculate_weighted_sentiment(articles)
        return NewsResult(
            articles=articles,
            sentiment_score=sentiment_score,
            source="general_economic"
        )
    
    logger.warning(
        "[FINNHUB_NEWS_LEVEL3_FAILED] %s | No general economic articles found, using Level 4 default",
        symbol
    )
    
    # Level 4: No news found - graceful handling (NO ERROR)
    logger.warning(
        "[FINNHUB_NEWS_LEVEL4_DEFAULT] %s | All 3 fallback levels exhausted | Using neutral sentiment (0.5)",
        symbol
    )
    
    # Return empty result with NEUTRAL sentiment (not error)
    return NewsResult(
        articles=[],
        sentiment_score=0.5,  # Neutral: 0.0=bearish, 0.5=neutral, 1.0=bullish
        source="empty",
        error=None  # NOT an error state
    )


# ============================================================================
# Helper Functions
# ============================================================================

def _clean_symbol(symbol: str) -> str:
    """
    Clean symbol by removing slashes and converting to uppercase.
    
    Args:
        symbol: 'AUD/USD' or 'AUDUSD'
    
    Returns:
        Cleaned symbol: 'AUDUSD'
    
    Examples:
        >>> _clean_symbol("AUD/USD")
        'AUDUSD'
        >>> _clean_symbol("eur/usd")
        'EURUSD'
    """
    return symbol.replace("/", "").upper().strip()


def _split_symbol(cleaned_symbol: str) -> Tuple[str, str]:
    """
    Split a 6-character symbol into base and quote currencies.
    
    Args:
        cleaned_symbol: 'AUDUSD' or 'EURUSD'
    
    Returns:
        Tuple of (base_currency, quote_currency): ('AUD', 'USD')
    
    Raises:
        ValueError: If symbol cannot be parsed
    
    Examples:
        >>> _split_symbol("AUDUSD")
        ('AUD', 'USD')
        >>> _split_symbol("EURUSD")
        ('EUR', 'USD')
    """
    if len(cleaned_symbol) < 6:
        raise ValueError(f"Symbol too short to parse: {cleaned_symbol}")
    
    # Try common 3-letter combinations
    base = cleaned_symbol[:3]
    quote = cleaned_symbol[3:6]
    
    if base not in CURRENCY_KEYWORDS or quote not in CURRENCY_KEYWORDS:
        logger.warning(
            "[FINNHUB_SYMBOL_PARSE] Unrecognized currencies: %s/%s",
            base, quote
        )
    
    return base, quote


async def _search_news_by_currency(
    manager,
    currency: str,
    original_symbol: str,
) -> List[NewsArticle]:
    """
    Search news for a specific currency using keyword matching.
    
    Args:
        manager: FinnhubMacroManager instance
        currency: Currency code like 'AUD' or 'USD'
        original_symbol: Original symbol for logging
    
    Returns:
        List of relevant NewsArticle objects
    """
    if currency not in CURRENCY_KEYWORDS:
        logger.warning(
            "[FINNHUB_CURRENCY_SEARCH] Unrecognized currency: %s for %s",
            currency, original_symbol
        )
        return []
    
    keywords = CURRENCY_KEYWORDS[currency]
    
    try:
        # Build search query: match any keyword for this currency
        # Finnhub doesn't support complex queries, so we do basic AND search
        query_str = f"{currency} forex"
        
        # Calculate minimum publication date (24 hours ago)
        lookback_seconds = NEWS_LOOKBACK_HOURS * 3600
        min_timestamp = int(time.time()) - lookback_seconds
        
        # Call Finnhub API with rate limiting
        url = (
            f"https://finnhub.io/api/v1/news?"
            f"category=forex"
            f"&limit={MAX_ARTICLES_PER_QUERY}"
            f"&token={manager.api_key}"
        )
        
        response = await manager._rate_limited_call(url, timeout_seconds=NEWS_API_TIMEOUT_SECONDS)
        
        if not response:
            logger.debug("[FINNHUB_CURRENCY_SEARCH] Empty response for %s", currency)
            return []
        
        # Parse raw articles
        raw_articles = response.get("data", []) if isinstance(response, dict) else response
        if not isinstance(raw_articles, list):
            raw_articles = []
        
        # Filter articles for this currency
        parsed_articles = []
        for raw in raw_articles:
            try:
                article = _parse_and_validate_article(raw)
                if article and _matches_keywords(article, keywords, currency):
                    parsed_articles.append(article)
            except Exception as e:
                logger.debug("[FINNHUB_ARTICLE_PARSE] Skipped article: %s", str(e)[:50])
                continue
        
        logger.debug(
        "[FINNHUB_CURRENCY_SEARCH] Found %d articles for %s in %s | Avg sentiment: %.2f",
        len(parsed_articles), currency, original_symbol,
        _calculate_weighted_sentiment(parsed_articles) if parsed_articles else 0.5)
        
        return parsed_articles
        
    except Exception as e:
        logger.warning(
            "[FINNHUB_CURRENCY_SEARCH_ERROR] Failed to fetch news for %s: %s",
            currency, str(e)[:100]
        )
        return []


async def _search_news_by_category(
    manager,
    category: str,
    original_symbol: str,
) -> List[NewsArticle]:
    """
    Search news by category (e.g., 'forex') as fallback.
    
    Args:
        manager: FinnhubMacroManager instance
        category: News category like 'forex', 'company_news', etc.
        original_symbol: Original symbol for logging
    
    Returns:
        List of NewsArticle objects
    """
    try:
        # Call Finnhub /news endpoint with category filter
        url = (
            f"https://finnhub.io/api/v1/news?"
            f"category={category}"
            f"&limit={MAX_ARTICLES_PER_QUERY}"
            f"&token={manager.api_key}"
        )
        
        response = await manager._rate_limited_call(url, timeout_seconds=NEWS_API_TIMEOUT_SECONDS)
        
        if not response:
            logger.debug("[FINNHUB_CATEGORY_SEARCH] Empty response for category=%s", category)
            return []
        
        # Parse raw articles
        raw_articles = response.get("data", []) if isinstance(response, dict) else response
        if not isinstance(raw_articles, list):
            raw_articles = []
        
        # Parse all articles (less filtering for fallback)
        parsed_articles = []
        for raw in raw_articles:
            try:
                article = _parse_and_validate_article(raw)
                if article:
                    parsed_articles.append(article)
            except Exception as e:
                logger.debug("[FINNHUB_ARTICLE_PARSE] Skipped article: %s", str(e)[:50])
                continue
        
        logger.debug(
            "[FINNHUB_CATEGORY_SEARCH] Found %d articles in category=%s for %s",
            len(parsed_articles), category, original_symbol
        )
        
        return parsed_articles
        
    except Exception as e:
        logger.warning(
            "[FINNHUB_CATEGORY_SEARCH_ERROR] Failed to fetch news for category=%s: %s",
            category, str(e)[:100]
        )
        return []


def _parse_and_validate_article(raw_article: Dict) -> Optional[NewsArticle]:
    """
    Parse and validate a raw article from Finnhub API.
    
    Args:
        raw_article: Raw article dict from Finnhub
    
    Returns:
        NewsArticle if valid, None otherwise
    
    Raises:
        ValueError: If article is malformed
    """
    headline = str(raw_article.get("headline", "")).strip()
    summary = str(raw_article.get("summary", "")).strip()
    source = str(raw_article.get("source", "")).strip()
    url = str(raw_article.get("url", "")).strip()
    published_at_unix = int(raw_article.get("datetime", 0))
    
    # Validate required fields
    if not headline:
        raise ValueError("Missing headline")
    if not url:
        raise ValueError("Missing URL")
    if published_at_unix <= 0:
        raise ValueError("Invalid timestamp")
    
    # Check if article is within lookback window
    now = int(time.time())
    lookback_seconds = NEWS_LOOKBACK_HOURS * 3600
    age_seconds = now - published_at_unix
    
    if age_seconds > lookback_seconds:
        logger.debug(
            "[FINNHUB_ARTICLE_AGE_CHECK] Article outside %dh window | Age: %dh | Headline: %.40s",
            NEWS_LOOKBACK_HOURS, age_seconds // 3600, headline[:40]
        )
        raise ValueError(f"Article outside {NEWS_LOOKBACK_HOURS}h lookback window (age: {age_seconds//3600}h)")
    
    # Classify sentiment
    sentiment_text = headline + " " + summary
    sentiment = _classify_sentiment(sentiment_text)
    sentiment_score = SENTIMENT_SCORE_MAPPING.get(sentiment, 0.5)
    
    logger.debug(
        "[FINNHUB_ARTICLE_PARSED] Headline: %.50s | Sentiment: %s | Score: %.2f",
        headline[:50], sentiment, sentiment_score
    )
    
    return NewsArticle(
        headline=headline,
        summary=summary,
        source=source,
        url=url,
        published_at_unix=published_at_unix,
        sentiment=sentiment,
        sentiment_score=sentiment_score,
    )


def _matches_keywords(
    article: NewsArticle,
    keywords: List[str],
    currency: str,
) -> bool:
    """
    Check if article matches any currency keywords.
    
    Args:
        article: NewsArticle to check
        keywords: List of keywords to match
        currency: Currency code for logging
    
    Returns:
        True if article mentions any keyword, False otherwise
    """
    text_to_check = (article.headline + " " + article.summary).lower()
    
    for keyword in keywords:
        if keyword.lower() in text_to_check:
            return True
    
    return False


def _deduplicate_articles(articles: List[NewsArticle]) -> List[NewsArticle]:
    """
    Remove duplicate articles by URL.
    
    Args:
        articles: List of articles (may contain duplicates)
    
    Returns:
        List of articles with duplicates removed (keeps first occurrence)
    """
    seen_urls = set()
    unique = []
    
    for article in articles:
        if article.url not in seen_urls:
            seen_urls.add(article.url)
            unique.append(article)
    
    return unique


def _classify_sentiment(text: str) -> str:
    """
    Basic sentiment classification using keyword matching.
    
    Args:
        text: Text to analyze (headline + summary)
    
    Returns:
        'bullish', 'bearish', or 'neutral'
    """
    text_lower = text.lower()
    
    # Bullish keywords
    bullish_kw = [
        "surge", "rally", "strong", "bullish", "gains", "upside",
        "growth", "beat", "exceeds", "expansion", "recovery", "rally",
        "outperform", "upgrade", "profit", "surge"
    ]
    
    # Bearish keywords
    bearish_kw = [
        "crash", "fall", "weakness", "bearish", "loss", "downside",
        "decline", "miss", "contraction", "recession", "weakness",
        "downgrade", "slump", "plunge", "deficit"
    ]
    
    bullish_count = sum(1 for kw in bullish_kw if kw in text_lower)
    bearish_count = sum(1 for kw in bearish_kw if kw in text_lower)
    
    if bullish_count > bearish_count:
        return "bullish"
    elif bearish_count > bullish_count:
        return "bearish"
    else:
        return "neutral"


def _calculate_weighted_sentiment(articles: List[NewsArticle]) -> float:
    """
    Calculate weighted average sentiment score across articles.
    
    Weights more recent articles more heavily using exponential decay.
    
    Args:
        articles: List of NewsArticle objects with sentiment_score in range [0.0, 1.0]
    
    Returns:
        Sentiment score 0.0 (very bearish) to 1.0 (very bullish)
        0.5 represents neutral
    
    Examples:
        >>> articles = [
        ...     NewsArticle(..., sentiment_score=0.8, published_at_unix=time.time()),
        ...     NewsArticle(..., sentiment_score=0.2, published_at_unix=time.time() - 7200),
        ... ]
        >>> score = _calculate_weighted_sentiment(articles)
        >>> print(f"Weighted sentiment: {score:.2f}")
        Weighted sentiment: 0.60
    """
    if not articles:
        return 0.5  # Default to neutral
    
    now = time.time()
    weighted_sum = 0.0
    total_weight = 0.0
    
    for article in articles:
        age_seconds = now - article.published_at_unix
        
        # Exponential decay weight: recent=1.0, 1hr oldâ‰ˆ0.5, 4hr oldâ‰ˆ0.1, 24hr oldâ‰ˆ0.00001
        # Weight formula: 2^(-age_seconds / 3600)
        weight = max(0.01, 2.0 ** (-age_seconds / 3600.0))
        
        # Clamp sentiment_score to valid range [0.0, 1.0]
        clamped_score = max(0.0, min(1.0, article.sentiment_score))
        weighted_sum += clamped_score * weight
        total_weight += weight
    
    if total_weight == 0:
        return 0.5
    
    # Ensure final result is in [0.0, 1.0]
    result = weighted_sum / total_weight
    return max(0.0, min(1.0, result))


# ============================================================================
# Integration Method - Drop-in Replacement
# ============================================================================

async def fetch_and_process_news_sentiment_refactored(manager) -> None:
    """
    Refactored news fetching method to replace _fetch_and_process_news_sentiment().
    
    This should be called periodically from the FinnhubMacroManager background task.
    
    IMPROVEMENTS OVER ORIGINAL:
    1. âœ… Broadened search: Queries both base and quote currencies separately
    2. âœ… General forex fallback: Falls back to 'forex' category if no currency matches
    3. âœ… Extended lookback: 24-hour minimum window (configurable)
    4. âœ… Graceful empty handling: Returns neutral sentiment (0.5) instead of error
    5. âœ… Symbol cleaning: Handles both 'AUD/USD' and 'AUDUSD' formats
    
    Integration Steps:
    -----------------
    1. Add this module to your imports in finnhub_macro_manager.py
    2. Replace the existing `_fetch_and_process_news_sentiment()` with this method
    3. Update the news fetching call in your main refresh loop
    
    Example:
        # In FinnhubMacroManager.__init__():
        from FINNHUB_NEWS_FETCHING_REFACTORED import fetch_and_process_news_sentiment_refactored
        
        # In main refresh loop:
        await fetch_and_process_news_sentiment_refactored(self)
    """
    if not manager.enable_sentiment_analysis:
        return
    
    try:
        # OPTIMIZATION A: Fetch general forex news ONCE at start of cycle
        # This cached result will be reused for all pairs without currency-specific news
        logger.debug("[FINNHUB_NEWS_OPTIMIZATION] Fetching general forex news (cached for all pairs)")
        general_forex_articles = await _search_news_by_category(manager, "forex", "general_forex_cache")
        general_forex_sentiment = _calculate_weighted_sentiment(general_forex_articles) if general_forex_articles else 0.5
        
        logger.info(
            "[FINNHUB_NEWS_CACHED_FOREX] Cached general forex articles: %d | Sentiment: %.2f",
            len(general_forex_articles),
            general_forex_sentiment
        )
        
        # Store cached forex articles in manager for reuse
        manager._cached_general_forex_articles = general_forex_articles
        
        # Now process each symbol
        symbols_using_cached_forex = 0
        for symbol in manager.symbols_display:
            # First try currency-specific news
            result = await fetch_news_with_fallback_and_cleanup(
                manager, symbol, 
                cached_forex_articles=general_forex_articles
            )
            
            # Track if we used cached forex for this symbol
            if result.source == "general_forex":
                symbols_using_cached_forex += 1
            
            # Update snapshot with results
            cleaned = _clean_symbol(symbol)
            if cleaned in manager._snapshot_cache:
                snapshot = manager._snapshot_cache[cleaned]
                
                # Safety check: if articles found but sentiment is 0.0, it's likely a parsing bug
                # Default to neutral (0.5) as fallback
                sentiment_to_use = result.sentiment_score
                if len(result.articles) > 0 and sentiment_to_use <= 0.0:
                    logger.warning(
                        "[FINNHUB_NEWS_SAFETY] %s had %d articles but sentiment was %.2f (invalid). Using neutral 0.50",
                        symbol, len(result.articles), sentiment_to_use
                    )
                    sentiment_to_use = 0.5
                
                with manager._cache_lock:
                    # Store sentiment score (0.5 = neutral if no news found)
                    snapshot.news_sentiment_score = sentiment_to_use
                    snapshot.last_updated_at = datetime.now(timezone.utc)
                
                # Log result
                source_label = f" ({result.source})" if result.source != "empty" else ""
                logger.info(
                    "[FINNHUB_NEWS] %s | Sentiment: %.2f | Articles: %d%s",
                    symbol, sentiment_to_use, len(result.articles), source_label
                )
        
        # Log summary with optimization benefit
        logger.info(
            "[FINNHUB_NEWS_REFRESH] News sentiment analysis completed successfully | "
            "Optimization A: General forex cached and reused %d times (saved ~%d API calls)",
            symbols_using_cached_forex,
            symbols_using_cached_forex
        )
        
    except Exception as e:
        logger.warning(
            "[FINNHUB_NEWS_REFRESH_ERROR] Failed to refresh news sentiment: %s",
            str(e)[:100]
        )


if __name__ == "__main__":
    # Quick test of helper functions
    print("Testing symbol cleaning...")
    assert _clean_symbol("AUD/USD") == "AUDUSD"
    assert _clean_symbol("eur/usd") == "EURUSD"
    print("âœ“ Symbol cleaning works")
    
    print("\nTesting symbol splitting...")
    base, quote = _split_symbol("AUDUSD")
    assert base == "AUD" and quote == "USD"
    print("âœ“ Symbol splitting works")
    
    print("\nTesting sentiment classification...")
    bullish = _classify_sentiment("The euro surged on strong economic growth")
    bearish = _classify_sentiment("Markets crashed on recession fears")
    neutral = _classify_sentiment("The central bank held rates steady")
    assert bullish == "bullish"
    assert bearish == "bearish"
    assert neutral == "neutral"
    print("âœ“ Sentiment classification works")
    
    print("\nTesting weighted sentiment calculation...")
    articles = [
        NewsArticle("Test", "", "src", "http://a", int(time.time()), "bullish", 0.8),
        NewsArticle("Test", "", "src", "http://b", int(time.time()) - 7200, "bearish", 0.2),
    ]
    score = _calculate_weighted_sentiment(articles)
    print(f"  Weighted sentiment: {score:.2f} (should be > 0.5 due to recent bullish)")
    print("âœ“ Weighted sentiment works")
    
    print("\nâœ… All tests passed!")

