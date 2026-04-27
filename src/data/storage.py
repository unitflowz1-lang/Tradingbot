"""Data storage and caching system for the AI Forex Trading Bot"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Union
import json
from dataclasses import asdict
from pathlib import Path
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime, Text, Boolean, JSON, text,
    Index, ForeignKey, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.dialects.postgresql import JSONB

from src.models import MarketData, SentimentResult
from src.data.news_data_collector import NewsArticle
from src.data.social_media_collector import SocialMediaPost
from src.exceptions import DataValidationError, DatabaseError
from src.config import Config


logger = logging.getLogger(__name__)
Base = declarative_base()
PORTABLE_JSON = JSON().with_variant(JSONB, "postgresql")


def _iter_exception_chain(exc: Exception):
    current = exc
    while current is not None:
        yield current
        current = current.__cause__ or current.__context__


def _is_network_refused_error(exc: Exception) -> bool:
    for err in _iter_exception_chain(exc):
        winerror = getattr(err, "winerror", None)
        errno_val = getattr(err, "errno", None)
        message = str(err).lower()
        if winerror == 1225:
            return True
        if errno_val in {111, 61, 10061}:
            return True
        if "refused the network connection" in message:
            return True
        if "connection refused" in message:
            return True
        if "actively refused" in message:
            return True
    return False


def _build_masked_db_target(config: Config) -> str:
    db_config = config.database
    return (
        f"driver=postgresql+asyncpg "
        f"user={db_config.username} "
        f"host={db_config.host} "
        f"port={db_config.port} "
        f"database={db_config.database} "
        f"password=<masked>"
    )


def _build_sqlite_fallback_url() -> str:
    fallback_name = os.environ.get("FALLBACK_SQLITE_PATH", "fallback_trade_history.db")
    fallback_path = Path(fallback_name)
    if not fallback_path.is_absolute():
        fallback_path = Path.cwd() / fallback_path
    fallback_path = fallback_path.resolve()
    return f"sqlite+aiosqlite:///{fallback_path.as_posix()}"


class MarketDataModel(Base):
    """Database model for market data"""
    __tablename__ = 'market_data'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Integer, nullable=False)
    bid = Column(Float, nullable=False)
    ask = Column(Float, nullable=False)
    spread = Column(Float, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Unique constraint to prevent duplicate data
    __table_args__ = (
        UniqueConstraint('symbol', 'timestamp', name='uq_market_data_symbol_timestamp'),
        Index('idx_market_data_symbol_timestamp', 'symbol', 'timestamp'),
        Index('idx_market_data_created_at', 'created_at'),
    )


class NewsDataModel(Base):
    """Database model for news articles"""
    __tablename__ = 'news_data'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    processed_content = Column(Text)
    source = Column(String(100), nullable=False, index=True)
    published_at = Column(DateTime, nullable=False, index=True)
    url = Column(Text, nullable=False)
    symbols = Column(PORTABLE_JSON)  # Store as JSON array
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Unique constraint to prevent duplicate articles
    __table_args__ = (
        UniqueConstraint('url', name='uq_news_data_url'),
        Index('idx_news_data_published_at', 'published_at'),
        Index('idx_news_data_source', 'source'),
        Index('idx_news_data_created_at', 'created_at'),
    )


class SocialMediaDataModel(Base):
    """Database model for social media posts"""
    __tablename__ = 'social_media_data'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    processed_content = Column(Text)
    platform = Column(String(50), nullable=False, index=True)
    author = Column(String(100), nullable=False)
    posted_at = Column(DateTime, nullable=False, index=True)
    post_id = Column(String(200), nullable=False)
    engagement_score = Column(Float, default=0.0)
    symbols = Column(PORTABLE_JSON)  # Store as JSON array
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Unique constraint to prevent duplicate posts
    __table_args__ = (
        UniqueConstraint('platform', 'post_id', name='uq_social_media_platform_post_id'),
        Index('idx_social_media_posted_at', 'posted_at'),
        Index('idx_social_media_platform', 'platform'),
        Index('idx_social_media_created_at', 'created_at'),
    )


class SentimentDataModel(Base):
    """Database model for sentiment analysis results"""
    __tablename__ = 'sentiment_data'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    sentiment_score = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    reasoning = Column(Text, nullable=False)
    sources = Column(PORTABLE_JSON)  # Store as JSON array
    timestamp = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_sentiment_data_symbol_timestamp', 'symbol', 'timestamp'),
        Index('idx_sentiment_data_created_at', 'created_at'),
    )


class CacheEntryModel(Base):
    """Database model for cache entries"""
    __tablename__ = 'cache_entries'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    cache_key = Column(String(255), nullable=False, unique=True, index=True)
    data = Column(PORTABLE_JSON, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    accessed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    access_count = Column(Integer, default=0)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc)
        if not self.accessed_at:
            self.accessed_at = datetime.now(timezone.utc)
        if self.access_count is None:
            self.access_count = 0
    
    __table_args__ = (
        Index('idx_cache_entries_expires_at', 'expires_at'),
        Index('idx_cache_entries_accessed_at', 'accessed_at'),
    )


class DataStorage:
    """Main data storage and caching system"""
    
    def __init__(self, config: Config):
        self.config = config
        self.engine = None
        self.async_session = None
        self._cache: Dict[str, Any] = {}
        self._cache_ttl = timedelta(minutes=15)
        
        # Data retention policies (in days)
        self.retention_policies = {
            'market_data': 365,  # 1 year
            'news_data': 90,     # 3 months
            'social_media_data': 30,  # 1 month
            'sentiment_data': 180,    # 6 months
            'cache_entries': 7        # 1 week
        }

    async def _initialize_engine(self, database_url: str, *, engine_kwargs: Optional[Dict[str, Any]] = None) -> None:
        """Create engine, session factory, and ensure schema exists."""
        self.engine = create_async_engine(
            database_url,
            echo=False,
            pool_pre_ping=True,
            **(engine_kwargs or {}),
        )
        self.async_session = sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def initialize(self) -> None:
        """Initialize database connection and create tables"""
        db_config = self.config.database
        database_url = (
            f"postgresql+asyncpg://{db_config.username}:{db_config.password}"
            f"@{db_config.host}:{db_config.port}/{db_config.database}"
        )
        masked_target = _build_masked_db_target(self.config)

        try:
            await self._initialize_engine(
                database_url,
                engine_kwargs={"pool_size": 10, "max_overflow": 20},
            )
            logger.info("Database initialized successfully | %s", masked_target)
        except Exception as e:
            logger.error("Failed to initialize primary database | %s | error=%s", masked_target, e)
            if self.engine is not None:
                try:
                    await self.engine.dispose()
                except Exception:
                    pass
                self.engine = None
                self.async_session = None

            if _is_network_refused_error(e):
                fallback_url = _build_sqlite_fallback_url()
                try:
                    await self._initialize_engine(fallback_url)
                    logger.warning(
                        "Primary database connection refused. Falling back to local SQLite archive at %s",
                        fallback_url.replace("sqlite+aiosqlite:///", ""),
                    )
                    return
                except Exception as fallback_err:
                    logger.error(
                        "SQLite fallback initialization failed after primary DB refusal | fallback=%s | error=%s",
                        fallback_url,
                        fallback_err,
                    )
                    raise DatabaseError(
                        f"Primary DB connection refused and SQLite fallback failed: {fallback_err}",
                        error_code="DB_INIT_FALLBACK_FAILED",
                        context={
                            "error": str(e),
                            "fallback_error": str(fallback_err),
                            "host": db_config.host,
                            "port": db_config.port,
                            "fallback_url": fallback_url,
                        }
                    )

            raise DatabaseError(
                f"Database initialization failed: {e}",
                error_code="DB_INIT_FAILED",
                context={
                    "error": str(e),
                    "host": db_config.host,
                    "port": db_config.port,
                }
            )

    async def close(self) -> None:
        """Close database connections"""
        if self.engine:
            await self.engine.dispose()
            logger.info("Database connections closed")
    
    async def store_market_data(self, market_data: List[MarketData]) -> int:
        """
        Store market data in database
        
        Args:
            market_data: List of MarketData objects to store
            
        Returns:
            Number of records stored
        """
        if not market_data:
            return 0
        
        try:
            async with self.async_session() as session:
                stored_count = 0
                
                for data in market_data:
                    # Check if data already exists
                    from sqlalchemy import text
                    existing = await session.execute(
                        text("SELECT id FROM market_data WHERE symbol = :symbol "
                             "AND timestamp = :timestamp"),
                        {"symbol": data.symbol, "timestamp": data.timestamp}
                    )
                    
                    if existing.fetchone() is None:
                        db_record = MarketDataModel(
                            symbol=data.symbol,
                            timestamp=data.timestamp,
                            open=data.open,
                            high=data.high,
                            low=data.low,
                            close=data.close,
                            volume=data.volume,
                            bid=data.bid,
                            ask=data.ask,
                            spread=data.spread
                        )
                        session.add(db_record)
                        stored_count += 1
                
                await session.commit()
                logger.info(f"Stored {stored_count} market data records")
                return stored_count
                
        except Exception as e:
            logger.error(f"Error storing market data: {e}")
            raise DatabaseError(
                f"Failed to store market data: {e}",
                error_code="MARKET_DATA_STORE_FAILED",
                context={"error": str(e), "count": len(market_data)}
            )
    
    async def store_news_data(self, news_articles: List[NewsArticle]) -> int:
        """
        Store news articles in database
        
        Args:
            news_articles: List of NewsArticle objects to store
            
        Returns:
            Number of records stored
        """
        if not news_articles:
            return 0
        
        try:
            async with self.async_session() as session:
                stored_count = 0
                
                for article in news_articles:
                    # Check if article already exists
                    from sqlalchemy import text
                    existing = await session.execute(
                        text("SELECT id FROM news_data WHERE url = :url"),
                        {"url": article.url}
                    )
                    
                    if existing.fetchone() is None:
                        db_record = NewsDataModel(
                            title=article.title,
                            content=article.content,
                            processed_content=article.processed_content,
                            source=article.source,
                            published_at=article.published_at,
                            url=article.url,
                            symbols=article.symbols
                        )
                        session.add(db_record)
                        stored_count += 1
                
                await session.commit()
                logger.info(f"Stored {stored_count} news articles")
                return stored_count
                
        except Exception as e:
            logger.error(f"Error storing news data: {e}")
            raise DatabaseError(
                f"Failed to store news data: {e}",
                error_code="NEWS_DATA_STORE_FAILED",
                context={"error": str(e), "count": len(news_articles)}
            )  
  
    async def store_social_media_data(self, posts: List[SocialMediaPost]) -> int:
        """
        Store social media posts in database
        
        Args:
            posts: List of SocialMediaPost objects to store
            
        Returns:
            Number of records stored
        """
        if not posts:
            return 0
        
        try:
            async with self.async_session() as session:
                stored_count = 0
                
                for post in posts:
                    # Check if post already exists
                    from sqlalchemy import text
                    existing = await session.execute(
                        text("SELECT id FROM social_media_data WHERE platform = :platform "
                             "AND post_id = :post_id"),
                        {"platform": post.platform, "post_id": post.post_id}
                    )
                    
                    if existing.fetchone() is None:
                        db_record = SocialMediaDataModel(
                            content=post.content,
                            processed_content=post.processed_content,
                            platform=post.platform,
                            author=post.author,
                            posted_at=post.posted_at,
                            post_id=post.post_id,
                            engagement_score=post.engagement_score,
                            symbols=post.symbols
                        )
                        session.add(db_record)
                        stored_count += 1
                
                await session.commit()
                logger.info(f"Stored {stored_count} social media posts")
                return stored_count
                
        except Exception as e:
            logger.error(f"Error storing social media data: {e}")
            raise DatabaseError(
                f"Failed to store social media data: {e}",
                error_code="SOCIAL_MEDIA_STORE_FAILED",
                context={"error": str(e), "count": len(posts)}
            )
    
    async def store_sentiment_data(self, sentiment_results: List[SentimentResult]) -> int:
        """
        Store sentiment analysis results in database
        
        Args:
            sentiment_results: List of SentimentResult objects to store
            
        Returns:
            Number of records stored
        """
        if not sentiment_results:
            return 0
        
        try:
            async with self.async_session() as session:
                stored_count = 0
                
                for result in sentiment_results:
                    db_record = SentimentDataModel(
                        symbol=result.symbol,
                        sentiment_score=result.sentiment_score,
                        confidence=result.confidence,
                        reasoning=result.reasoning,
                        sources=result.sources,
                        timestamp=result.timestamp
                    )
                    session.add(db_record)
                    stored_count += 1
                
                await session.commit()
                logger.info(f"Stored {stored_count} sentiment results")
                return stored_count
                
        except Exception as e:
            logger.error(f"Error storing sentiment data: {e}")
            raise DatabaseError(
                f"Failed to store sentiment data: {e}",
                error_code="SENTIMENT_DATA_STORE_FAILED",
                context={"error": str(e), "count": len(sentiment_results)}
            )

    async def get_market_data(self, symbol: str, start_time: datetime, 
                             end_time: datetime) -> List[MarketData]:
        """
        Retrieve market data from database
        
        Args:
            symbol: Currency pair symbol
            start_time: Start time for data retrieval
            end_time: End time for data retrieval
            
        Returns:
            List of MarketData objects
        """
        try:
            async with self.async_session() as session:
                from sqlalchemy import text
                result = await session.execute(
                    text("SELECT * FROM market_data WHERE symbol = :symbol "
                         "AND timestamp >= :start_time AND timestamp <= :end_time "
                         "ORDER BY timestamp ASC"),
                    {"symbol": symbol, "start_time": start_time, "end_time": end_time}
                )
                
                market_data = []
                for row in result.fetchall():
                    data = MarketData(
                        symbol=row.symbol,
                        timestamp=row.timestamp,
                        open=row.open,
                        high=row.high,
                        low=row.low,
                        close=row.close,
                        volume=row.volume,
                        bid=row.bid,
                        ask=row.ask,
                        spread=row.spread
                    )
                    market_data.append(data)
                
                logger.debug(f"Retrieved {len(market_data)} market data records for {symbol}")
                return market_data
                
        except Exception as e:
            logger.error(f"Error retrieving market data: {e}")
            raise DatabaseError(
                f"Failed to retrieve market data: {e}",
                error_code="MARKET_DATA_RETRIEVE_FAILED",
                context={"symbol": symbol, "start_time": start_time, "end_time": end_time}
            )
    
    async def get_news_data(self, symbols: List[str], start_time: datetime, 
                           end_time: datetime) -> List[NewsArticle]:
        """
        Retrieve news articles from database
        
        Args:
            symbols: List of currency pair symbols
            start_time: Start time for data retrieval
            end_time: End time for data retrieval
            
        Returns:
            List of NewsArticle objects
        """
        try:
            async with self.async_session() as session:
                from sqlalchemy import text
                # Build query for symbols using JSON contains operator
                symbol_conditions = []
                params = {"start_time": start_time, "end_time": end_time}
                
                for i, symbol in enumerate(symbols):
                    symbol_conditions.append(f"symbols @> :symbol_{i}")
                    params[f"symbol_{i}"] = f'["{symbol}"]'
                
                symbol_filter = " OR ".join(symbol_conditions)
                
                result = await session.execute(
                    text(f"SELECT * FROM news_data WHERE ({symbol_filter}) "
                         f"AND published_at >= :start_time AND published_at <= :end_time "
                         f"ORDER BY published_at DESC"),
                    params
                )
                
                news_articles = []
                for row in result.fetchall():
                    article = NewsArticle(
                        title=row.title,
                        content=row.content,
                        source=row.source,
                        published_at=row.published_at,
                        url=row.url,
                        symbols=row.symbols or []
                    )
                    article.processed_content = row.processed_content or ""
                    news_articles.append(article)
                
                logger.debug(f"Retrieved {len(news_articles)} news articles")
                return news_articles
                
        except Exception as e:
            logger.error(f"Error retrieving news data: {e}")
            raise DatabaseError(
                f"Failed to retrieve news data: {e}",
                error_code="NEWS_DATA_RETRIEVE_FAILED",
                context={"symbols": symbols, "start_time": start_time, "end_time": end_time}
            )
    
    async def get_social_media_data(self, symbols: List[str], start_time: datetime, 
                                   end_time: datetime) -> List[SocialMediaPost]:
        """
        Retrieve social media posts from database
        
        Args:
            symbols: List of currency pair symbols
            start_time: Start time for data retrieval
            end_time: End time for data retrieval
            
        Returns:
            List of SocialMediaPost objects
        """
        try:
            async with self.async_session() as session:
                from sqlalchemy import text
                # Build query for symbols using JSON contains operator
                symbol_conditions = []
                params = {"start_time": start_time, "end_time": end_time}
                
                for i, symbol in enumerate(symbols):
                    symbol_conditions.append(f"symbols @> :symbol_{i}")
                    params[f"symbol_{i}"] = f'["{symbol}"]'
                
                symbol_filter = " OR ".join(symbol_conditions)
                
                result = await session.execute(
                    text(f"SELECT * FROM social_media_data WHERE ({symbol_filter}) "
                         f"AND posted_at >= :start_time AND posted_at <= :end_time "
                         f"ORDER BY posted_at DESC, engagement_score DESC"),
                    params
                )
                
                posts = []
                for row in result.fetchall():
                    post = SocialMediaPost(
                        content=row.content,
                        platform=row.platform,
                        author=row.author,
                        posted_at=row.posted_at,
                        post_id=row.post_id,
                        engagement_score=row.engagement_score,
                        symbols=row.symbols or []
                    )
                    post.processed_content = row.processed_content or ""
                    posts.append(post)
                
                logger.debug(f"Retrieved {len(posts)} social media posts")
                return posts
                
        except Exception as e:
            logger.error(f"Error retrieving social media data: {e}")
            raise DatabaseError(
                f"Failed to retrieve social media data: {e}",
                error_code="SOCIAL_MEDIA_RETRIEVE_FAILED",
                context={"symbols": symbols, "start_time": start_time, "end_time": end_time}
            )
    
    async def get_sentiment_data(self, symbol: str, start_time: datetime, 
                                end_time: datetime) -> List[SentimentResult]:
        """
        Retrieve sentiment analysis results from database
        
        Args:
            symbol: Currency pair symbol
            start_time: Start time for data retrieval
            end_time: End time for data retrieval
            
        Returns:
            List of SentimentResult objects
        """
        try:
            async with self.async_session() as session:
                from sqlalchemy import text
                result = await session.execute(
                    text("SELECT * FROM sentiment_data WHERE symbol = :symbol "
                         "AND timestamp >= :start_time AND timestamp <= :end_time "
                         "ORDER BY timestamp DESC"),
                    {"symbol": symbol, "start_time": start_time, "end_time": end_time}
                )
                
                sentiment_results = []
                for row in result.fetchall():
                    result_obj = SentimentResult(
                        symbol=row.symbol,
                        sentiment_score=row.sentiment_score,
                        confidence=row.confidence,
                        reasoning=row.reasoning,
                        sources=row.sources or [],
                        timestamp=row.timestamp
                    )
                    sentiment_results.append(result_obj)
                
                logger.debug(f"Retrieved {len(sentiment_results)} sentiment results for {symbol}")
                return sentiment_results
                
        except Exception as e:
            logger.error(f"Error retrieving sentiment data: {e}")
            raise DatabaseError(
                f"Failed to retrieve sentiment data: {e}",
                error_code="SENTIMENT_DATA_RETRIEVE_FAILED",
                context={"symbol": symbol, "start_time": start_time, "end_time": end_time}
            )


class CacheManager:
    """Advanced caching system with database persistence"""
    
    def __init__(self, storage: DataStorage):
        self.storage = storage
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._default_ttl = timedelta(minutes=15)
    
    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache (memory first, then database)
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        # Check memory cache first
        if key in self._memory_cache:
            entry = self._memory_cache[key]
            if datetime.now(timezone.utc) < entry['expires_at']:
                logger.debug(f"Cache hit (memory): {key}")
                return entry['data']
            else:
                # Remove expired entry
                del self._memory_cache[key]
        
        # Check database cache
        try:
            async with self.storage.async_session() as session:
                from sqlalchemy import text
                result = await session.execute(
                    text("SELECT data, expires_at FROM cache_entries WHERE cache_key = :key"),
                    {"key": key}
                )
                row = result.fetchone()
                
                if row and datetime.now(timezone.utc) < row.expires_at:
                    # Update access statistics
                    await session.execute(
                        text("UPDATE cache_entries SET accessed_at = :accessed_at, "
                             "access_count = access_count + 1 WHERE cache_key = :key"),
                        {"accessed_at": datetime.now(timezone.utc), "key": key}
                    )
                    await session.commit()
                    
                    # Store in memory cache for faster access
                    self._memory_cache[key] = {
                        'data': row.data,
                        'expires_at': row.expires_at
                    }
                    
                    logger.debug(f"Cache hit (database): {key}")
                    return row.data
                elif row:
                    # Remove expired entry
                    await session.execute(
                        text("DELETE FROM cache_entries WHERE cache_key = :key"),
                        {"key": key}
                    )
                    await session.commit()
        
        except Exception as e:
            logger.error(f"Error retrieving from cache: {e}")
        
        logger.debug(f"Cache miss: {key}")
        return None
    
    async def set(self, key: str, value: Any, ttl: Optional[timedelta] = None) -> None:
        """
        Set value in cache (both memory and database)
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live (optional)
        """
        ttl = ttl or self._default_ttl
        expires_at = datetime.now(timezone.utc) + ttl
        
        # Store in memory cache
        self._memory_cache[key] = {
            'data': value,
            'expires_at': expires_at
        }
        
        # Store in database cache
        try:
            async with self.storage.async_session() as session:
                from sqlalchemy import text
                # Check if entry exists
                result = await session.execute(
                    text("SELECT id FROM cache_entries WHERE cache_key = :key"),
                    {"key": key}
                )
                existing = result.fetchone()
                
                if existing:
                    # Update existing entry
                    await session.execute(
                        text("UPDATE cache_entries SET data = :data, "
                             "expires_at = :expires_at, accessed_at = :accessed_at "
                             "WHERE cache_key = :key"),
                        {
                            "data": value,
                            "expires_at": expires_at,
                            "accessed_at": datetime.now(timezone.utc),
                            "key": key
                        }
                    )
                else:
                    # Create new entry
                    cache_entry = CacheEntryModel(
                        cache_key=key,
                        data=value,
                        expires_at=expires_at
                    )
                    session.add(cache_entry)
                
                await session.commit()
                logger.debug(f"Cache set: {key}")
                
        except Exception as e:
            logger.error(f"Error setting cache: {e}")
    
    async def delete(self, key: str) -> None:
        """
        Delete value from cache
        
        Args:
            key: Cache key to delete
        """
        # Remove from memory cache
        if key in self._memory_cache:
            del self._memory_cache[key]
        
        # Remove from database cache
        try:
            async with self.storage.async_session() as session:
                from sqlalchemy import text
                await session.execute(
                    text("DELETE FROM cache_entries WHERE cache_key = :key"),
                    {"key": key}
                )
                await session.commit()
                logger.debug(f"Cache deleted: {key}")
                
        except Exception as e:
            logger.error(f"Error deleting from cache: {e}")
    
    async def clear(self) -> None:
        """Clear all cache entries"""
        # Clear memory cache
        self._memory_cache.clear()
        
        # Clear database cache
        try:
            async with self.storage.async_session() as session:
                from sqlalchemy import text
                await session.execute(text("DELETE FROM cache_entries"))
                await session.commit()
                logger.info("Cache cleared")
                
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
    
    async def cleanup_expired(self) -> int:
        """
        Remove expired cache entries
        
        Returns:
            Number of entries removed
        """
        # Clean memory cache
        expired_keys = [
            key for key, entry in self._memory_cache.items()
            if datetime.now(timezone.utc) >= entry['expires_at']
        ]
        for key in expired_keys:
            del self._memory_cache[key]
        
        # Clean database cache
        try:
            async with self.storage.async_session() as session:
                from sqlalchemy import text
                result = await session.execute(
                    text("DELETE FROM cache_entries WHERE expires_at < :cutoff_time"),
                    {"cutoff_time": datetime.now(timezone.utc)}
                )
                await session.commit()
                
                db_cleaned = result.rowcount
                total_cleaned = len(expired_keys) + db_cleaned
                
                logger.info(f"Cleaned {total_cleaned} expired cache entries")
                return total_cleaned
                
        except Exception as e:
            logger.error(f"Error cleaning expired cache: {e}")
            return len(expired_keys)


class DataRetentionManager:
    """Manages data retention policies and cleanup"""
    
    def __init__(self, storage: DataStorage):
        self.storage = storage
    
    async def cleanup_old_data(self) -> Dict[str, int]:
        """
        Clean up old data based on retention policies
        
        Returns:
            Dictionary with table names and number of records cleaned
        """
        cleanup_results = {}
        
        try:
            async with self.storage.async_session() as session:
                from sqlalchemy import text
                for table_name, retention_days in self.storage.retention_policies.items():
                    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
                    
                    if table_name == 'market_data':
                        result = await session.execute(
                            text("DELETE FROM market_data WHERE created_at < :cutoff_date"),
                            {"cutoff_date": cutoff_date}
                        )
                    elif table_name == 'news_data':
                        result = await session.execute(
                            text("DELETE FROM news_data WHERE created_at < :cutoff_date"),
                            {"cutoff_date": cutoff_date}
                        )
                    elif table_name == 'social_media_data':
                        result = await session.execute(
                            text("DELETE FROM social_media_data WHERE created_at < :cutoff_date"),
                            {"cutoff_date": cutoff_date}
                        )
                    elif table_name == 'sentiment_data':
                        result = await session.execute(
                            text("DELETE FROM sentiment_data WHERE created_at < :cutoff_date"),
                            {"cutoff_date": cutoff_date}
                        )
                    elif table_name == 'cache_entries':
                        result = await session.execute(
                            text("DELETE FROM cache_entries WHERE created_at < :cutoff_date"),
                            {"cutoff_date": cutoff_date}
                        )
                    else:
                        continue
                    
                    cleanup_results[table_name] = result.rowcount
                    logger.info(f"Cleaned {result.rowcount} old records from {table_name}")
                
                await session.commit()
                
        except Exception as e:
            logger.error(f"Error during data cleanup: {e}")
            raise DatabaseError(
                f"Data cleanup failed: {e}",
                error_code="DATA_CLEANUP_FAILED",
                context={"error": str(e)}
            )
        
        return cleanup_results
    
    async def get_storage_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics
        
        Returns:
            Dictionary with storage statistics
        """
        stats = {}
        
        try:
            async with self.storage.async_session() as session:
                from sqlalchemy import text
                # Count records in each table
                tables = ['market_data', 'news_data', 'social_media_data', 
                         'sentiment_data', 'cache_entries']
                
                for table in tables:
                    result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    count = result.fetchone()[0]
                    stats[f"{table}_count"] = count
                
                # Get oldest and newest records
                for table in ['market_data', 'news_data', 'social_media_data', 'sentiment_data']:
                    # Oldest record
                    result = await session.execute(
                        text(f"SELECT MIN(created_at) FROM {table}")
                    )
                    oldest = result.fetchone()[0]
                    stats[f"{table}_oldest"] = oldest
                    
                    # Newest record
                    result = await session.execute(
                        text(f"SELECT MAX(created_at) FROM {table}")
                    )
                    newest = result.fetchone()[0]
                    stats[f"{table}_newest"] = newest
                
                # Cache statistics
                result = await session.execute(
                    text("SELECT AVG(access_count), MAX(access_count) FROM cache_entries")
                )
                avg_access, max_access = result.fetchone()
                stats['cache_avg_access'] = avg_access or 0
                stats['cache_max_access'] = max_access or 0
                
        except Exception as e:
            logger.error(f"Error getting storage stats: {e}")
            stats['error'] = str(e)
        
        return stats
