"""
Currency-based news caching to reduce API calls.
Instead of fetching per symbol (AUD/USD), fetch per currency (AUD, USD).
Reduces API calls by 70-80%.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)

class CurrencyNewsCache:
    """
    Manages news caching at currency level instead of symbol level.
    Reduces API calls by fetching once per currency (AUD, USD, EUR) 
    instead of once per pair (AUD/USD, USD/CAD, EUR/USD).
    """
    
    # Class-level shared cache (persists across instances)
    _currency_cache: Dict[str, Any] = {}
    _cache_timestamps: Dict[str, datetime] = {}
    
    # 60-minute cache TTL (increased from 15 minutes)
    CACHE_TTL_SECONDS = 3600
    
    @staticmethod
    def extract_currencies(symbol: str) -> List[str]:
        """
        Extract base and quote currencies from symbol.
        AUD/USD -> ['AUD', 'USD']
        EUR/GBP -> ['EUR', 'GBP']
        """
        # Remove slashes and split
        clean_symbol = symbol.replace("/", "").replace("-", "")
        
        # Major currencies (3-letter codes)
        currencies = []
        major_currencies = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'NZD']
        
        for currency in major_currencies:
            if currency in clean_symbol:
                currencies.append(currency)
        
        return currencies[:2]  # Return base and quote only
    
    @classmethod
    def get_currency_news(cls, symbol: str) -> Optional[List[Any]]:
        """
        Get cached news for a symbol by checking currency-level cache.
        Returns combined news from both base and quote currencies.
        """
        currencies = cls.extract_currencies(symbol)
        if not currencies:
            return None
        
        all_news = []
        now = datetime.now(timezone.utc)
        
        for currency in currencies:
            # Check if cache is still valid
            last_fetch = cls._cache_timestamps.get(currency)
            if last_fetch and (now - last_fetch).total_seconds() < cls.CACHE_TTL_SECONDS:
                # Cache is valid
                cached_news = cls._currency_cache.get(currency, [])
                all_news.extend(cached_news)
            else:
                # Cache expired or missing - signal caller to fetch
                return None
        
        return all_news if all_news else None
    
    @classmethod
    def set_currency_news(cls, symbol: str, news_articles: List[Any]) -> None:
        """
        Store news at currency level.
        """
        currencies = cls.extract_currencies(symbol)
        now = datetime.now(timezone.utc)
        
        for currency in currencies:
            cls._currency_cache[currency] = news_articles
            cls._cache_timestamps[currency] = now
        
        logger.info(
            "[CURRENCY_NEWS_CACHE] Cached %d articles for currencies: %s",
            len(news_articles),
            ", ".join(currencies)
        )
    
    @classmethod
    def is_cache_valid(cls, symbol: str) -> bool:
        """
        Check if currency-level cache is still valid for this symbol.
        """
        currencies = cls.extract_currencies(symbol)
        now = datetime.now(timezone.utc)
        
        for currency in currencies:
            last_fetch = cls._cache_timestamps.get(currency)
            if not last_fetch:
                return False
            if (now - last_fetch).total_seconds() >= cls.CACHE_TTL_SECONDS:
                return False
        
        return True
    
    @classmethod
    def get_cache_stats(cls) -> Dict[str, Any]:
        """
        Get cache statistics for monitoring.
        """
        now = datetime.now(timezone.utc)
        stats = {
            "currencies_cached": len(cls._currency_cache),
            "cache_entries": {},
        }
        
        for currency, timestamp in cls._cache_timestamps.items():
            age_seconds = (now - timestamp).total_seconds()
            stats["cache_entries"][currency] = {
                "age_minutes": age_seconds / 60,
                "valid": age_seconds < cls.CACHE_TTL_SECONDS,
                "articles": len(cls._currency_cache.get(currency, []))
            }
        
        return stats
