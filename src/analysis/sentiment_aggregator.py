"""Sentiment aggregation and confidence scoring for multiple LLM responses"""

import hashlib
import time
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean, stdev
from src.models import SentimentResult
from src.exceptions import DataValidationError
from src.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class AggregatedSentiment:
    """Aggregated sentiment result from multiple sources"""
    symbol: str
    final_sentiment_score: float
    final_confidence: float
    reasoning: str
    sources: List[str]
    individual_results: List[SentimentResult]
    aggregation_method: str
    consistency_score: float
    timestamp: datetime


@dataclass
class CacheEntry:
    """Cache entry for sentiment results"""
    content_hash: str
    result: SentimentResult
    timestamp: datetime
    access_count: int


class SentimentCache:
    """Cache for sentiment analysis results"""
    
    def __init__(self, max_size: int = 1000, ttl_hours: int = 24):
        self.cache: Dict[str, CacheEntry] = {}
        self.max_size = max_size
        self.ttl = timedelta(hours=ttl_hours)
    
    def _generate_hash(self, text_data: List[str], symbol: str) -> str:
        """Generate hash for text data and symbol"""
        combined_text = f"{symbol}:{':'.join(sorted(text_data))}"
        return hashlib.md5(combined_text.encode()).hexdigest()
    
    def get(self, text_data: List[str], symbol: str) -> Optional[SentimentResult]:
        """Get cached sentiment result"""
        cache_key = self._generate_hash(text_data, symbol)
        
        if cache_key in self.cache:
            entry = self.cache[cache_key]
            
            # Check if entry is still valid
            if datetime.now(timezone.utc) - entry.timestamp <= self.ttl:
                entry.access_count += 1
                logger.debug(f"Cache hit for {symbol}: {cache_key[:8]}")
                return entry.result
            else:
                # Remove expired entry
                del self.cache[cache_key]
                logger.debug(f"Cache expired for {symbol}: {cache_key[:8]}")
        
        return None
    
    def put(self, text_data: List[str], symbol: str, result: SentimentResult) -> None:
        """Store sentiment result in cache"""
        cache_key = self._generate_hash(text_data, symbol)
        
        # Clean cache if at max size
        if len(self.cache) >= self.max_size:
            self._cleanup_cache()
        
        self.cache[cache_key] = CacheEntry(
            content_hash=cache_key,
            result=result,
            timestamp=datetime.now(timezone.utc),
            access_count=1
        )
        
        logger.debug(f"Cached sentiment for {symbol}: {cache_key[:8]}")
    
    def _cleanup_cache(self) -> None:
        """Remove least recently used and expired entries"""
        now = datetime.now(timezone.utc)
        
        # Remove expired entries first
        expired_keys = [
            key for key, entry in self.cache.items()
            if now - entry.timestamp > self.ttl
        ]
        
        for key in expired_keys:
            del self.cache[key]
        
        # If still at max size, remove least accessed entries
        if len(self.cache) >= self.max_size:
            # Sort by access count (ascending) and timestamp (ascending)
            sorted_entries = sorted(
                self.cache.items(),
                key=lambda x: (x[1].access_count, x[1].timestamp)
            )
            
            # Remove oldest 25% of entries
            remove_count = max(1, len(sorted_entries) // 4)
            for key, _ in sorted_entries[:remove_count]:
                del self.cache[key]
        
        logger.debug(f"Cache cleanup completed. Size: {len(self.cache)}")
    
    def clear(self) -> None:
        """Clear all cache entries"""
        self.cache.clear()
        logger.debug("Cache cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        now = datetime.now(timezone.utc)
        valid_entries = sum(
            1 for entry in self.cache.values()
            if now - entry.timestamp <= self.ttl
        )
        
        return {
            "total_entries": len(self.cache),
            "valid_entries": valid_entries,
            "expired_entries": len(self.cache) - valid_entries,
            "max_size": self.max_size,
            "ttl_hours": self.ttl.total_seconds() / 3600
        }


class SentimentAggregator:
    """Aggregates multiple sentiment analysis results with confidence scoring"""
    
    def __init__(self, cache_enabled: bool = True):
        self.cache = SentimentCache() if cache_enabled else None
        self.source_weights = {
            "news": 1.0,
            "social_media": 0.7,
            "technical": 0.8,
            "fundamental": 0.9,
            "LLM Analysis": 0.6,
            "Error": 0.1
        }
        self.min_results_for_aggregation = 2
        self.consistency_threshold = 0.3  # Maximum std dev for high consistency
    
    def aggregate_sentiment(
        self,
        results: List[SentimentResult],
        method: str = "weighted_average"
    ) -> AggregatedSentiment:
        """Aggregate multiple sentiment results"""
        
        if not results:
            raise DataValidationError(
                "Cannot aggregate empty results list",
                error_code="EMPTY_RESULTS",
                context={"results_count": 0}
            )
        
        # Validate all results are for the same symbol
        symbols = set(result.symbol for result in results)
        if len(symbols) > 1:
            raise DataValidationError(
                f"All results must be for the same symbol. Found: {symbols}",
                error_code="MIXED_SYMBOLS",
                context={"symbols": list(symbols)}
            )
        
        symbol = results[0].symbol
        
        # Filter out error results if we have valid ones
        valid_results = [r for r in results if "Error" not in r.sources]
        if valid_results:
            results = valid_results
        
        logger.info(f"Aggregating {len(results)} sentiment results for {symbol} using {method}")
        
        # Apply aggregation method
        if method == "weighted_average":
            final_score, final_confidence = self._weighted_average_aggregation(results)
        elif method == "confidence_weighted":
            final_score, final_confidence = self._confidence_weighted_aggregation(results)
        elif method == "median":
            final_score, final_confidence = self._median_aggregation(results)
        elif method == "consensus":
            final_score, final_confidence = self._consensus_aggregation(results)
        else:
            raise DataValidationError(
                f"Unknown aggregation method: {method}",
                error_code="UNKNOWN_METHOD",
                context={"method": method, "available": ["weighted_average", "confidence_weighted", "median", "consensus"]}
            )
        
        # Calculate consistency score
        consistency_score = self._calculate_consistency_score(results)
        
        # Adjust final confidence based on consistency
        final_confidence = self._adjust_confidence_for_consistency(final_confidence, consistency_score)
        
        # Generate aggregated reasoning
        reasoning = self._generate_aggregated_reasoning(results, final_score, final_confidence, consistency_score)
        
        # Collect all sources
        all_sources = []
        for result in results:
            all_sources.extend(result.sources)
        unique_sources = list(set(all_sources))
        
        return AggregatedSentiment(
            symbol=symbol,
            final_sentiment_score=final_score,
            final_confidence=final_confidence,
            reasoning=reasoning,
            sources=unique_sources,
            individual_results=results,
            aggregation_method=method,
            consistency_score=consistency_score,
            timestamp=datetime.now()
        )
    
    def _weighted_average_aggregation(self, results: List[SentimentResult]) -> Tuple[float, float]:
        """Aggregate using weighted average based on source reliability"""
        total_weight = 0.0
        weighted_score_sum = 0.0
        weighted_confidence_sum = 0.0
        
        for result in results:
            # Calculate weight based on sources
            source_weight = max(
                self.source_weights.get(source, 0.5) for source in result.sources
            )
            
            # Adjust weight by result confidence
            final_weight = source_weight * result.confidence
            
            weighted_score_sum += result.sentiment_score * final_weight
            weighted_confidence_sum += result.confidence * final_weight
            total_weight += final_weight
        
        if total_weight == 0:
            return 0.0, 0.1
        
        final_score = weighted_score_sum / total_weight
        final_confidence = weighted_confidence_sum / total_weight
        
        return final_score, final_confidence
    
    def _confidence_weighted_aggregation(self, results: List[SentimentResult]) -> Tuple[float, float]:
        """Aggregate using confidence as weights"""
        total_confidence = sum(result.confidence for result in results)
        
        if total_confidence == 0:
            return 0.0, 0.1
        
        weighted_score = sum(
            result.sentiment_score * result.confidence for result in results
        ) / total_confidence
        
        # Final confidence is the average confidence
        final_confidence = total_confidence / len(results)
        
        return weighted_score, final_confidence
    
    def _median_aggregation(self, results: List[SentimentResult]) -> Tuple[float, float]:
        """Aggregate using median values"""
        scores = [result.sentiment_score for result in results]
        confidences = [result.confidence for result in results]
        
        scores.sort()
        confidences.sort()
        
        n = len(scores)
        if n % 2 == 0:
            median_score = (scores[n//2 - 1] + scores[n//2]) / 2
            median_confidence = (confidences[n//2 - 1] + confidences[n//2]) / 2
        else:
            median_score = scores[n//2]
            median_confidence = confidences[n//2]
        
        return median_score, median_confidence
    
    def _consensus_aggregation(self, results: List[SentimentResult]) -> Tuple[float, float]:
        """Aggregate using consensus approach - only high-agreement results"""
        scores = [result.sentiment_score for result in results]
        
        if len(scores) < 2:
            return scores[0], results[0].confidence
        
        # Calculate standard deviation
        score_std = stdev(scores) if len(scores) > 1 else 0.0
        
        # If high consensus (low std dev), use weighted average
        if score_std <= self.consistency_threshold:
            return self._weighted_average_aggregation(results)
        
        # If low consensus, be more conservative
        mean_score = mean(scores)
        mean_confidence = mean(result.confidence for result in results)
        
        # Reduce confidence due to disagreement
        consensus_penalty = min(score_std / self.consistency_threshold, 1.0)
        adjusted_confidence = mean_confidence * (1.0 - consensus_penalty * 0.5)
        
        return mean_score, adjusted_confidence
    
    def _calculate_consistency_score(self, results: List[SentimentResult]) -> float:
        """Calculate consistency score (0.0 = inconsistent, 1.0 = highly consistent)"""
        if len(results) < 2:
            return 1.0
        
        scores = [result.sentiment_score for result in results]
        score_std = stdev(scores) if len(scores) > 1 else 0.0
        
        # Convert std dev to consistency score (inverse relationship)
        # High std dev = low consistency, low std dev = high consistency
        max_possible_std = 2.0  # Maximum possible std dev for sentiment scores (-1 to 1)
        consistency = 1.0 - min(score_std / max_possible_std, 1.0)
        
        return consistency
    
    def _adjust_confidence_for_consistency(self, base_confidence: float, consistency_score: float) -> float:
        """Adjust confidence based on result consistency"""
        # High consistency boosts confidence, low consistency reduces it
        consistency_factor = 0.5 + (consistency_score * 0.5)  # Range: 0.5 to 1.0
        adjusted_confidence = base_confidence * consistency_factor
        
        return max(0.0, min(1.0, adjusted_confidence))
    
    def _generate_aggregated_reasoning(
        self,
        results: List[SentimentResult],
        final_score: float,
        final_confidence: float,
        consistency_score: float
    ) -> str:
        """Generate reasoning for aggregated result"""
        symbol = results[0].symbol
        
        # Determine sentiment direction
        if final_score > 0.1:
            sentiment_desc = "bullish"
        elif final_score < -0.1:
            sentiment_desc = "bearish"
        else:
            sentiment_desc = "neutral"
        
        # Determine confidence level
        if final_confidence > 0.7:
            confidence_desc = "high"
        elif final_confidence > 0.4:
            confidence_desc = "moderate"
        else:
            confidence_desc = "low"
        
        # Determine consistency level
        if consistency_score > 0.8:
            consistency_desc = "high agreement"
        elif consistency_score > 0.5:
            consistency_desc = "moderate agreement"
        else:
            consistency_desc = "mixed signals"
        
        reasoning = f"Aggregated analysis for {symbol} shows {sentiment_desc} sentiment " \
                   f"(score: {final_score:.3f}) with {confidence_desc} confidence " \
                   f"({final_confidence:.3f}). Based on {len(results)} analysis sources " \
                   f"with {consistency_desc} (consistency: {consistency_score:.3f})."
        
        # Add key insights from individual results
        key_insights = []
        for result in results[:3]:  # Limit to top 3 results
            if len(result.reasoning) > 20:
                insight = result.reasoning[:100] + "..." if len(result.reasoning) > 100 else result.reasoning
                key_insights.append(f"• {insight}")
        
        if key_insights:
            reasoning += f" Key insights: {' '.join(key_insights)}"
        
        return reasoning
    
    def calculate_source_reliability(self, results: List[SentimentResult]) -> Dict[str, float]:
        """Calculate reliability scores for different sources"""
        source_performance = {}
        
        for result in results:
            for source in result.sources:
                if source not in source_performance:
                    source_performance[source] = {
                        "total_confidence": 0.0,
                        "count": 0,
                        "consistency_scores": []
                    }
                
                source_performance[source]["total_confidence"] += result.confidence
                source_performance[source]["count"] += 1
        
        # Calculate reliability scores
        reliability_scores = {}
        for source, perf in source_performance.items():
            avg_confidence = perf["total_confidence"] / perf["count"]
            base_weight = self.source_weights.get(source, 0.5)
            
            # Combine base weight with observed performance
            reliability_scores[source] = (base_weight + avg_confidence) / 2
        
        return reliability_scores
    
    def get_cached_sentiment(self, text_data: List[str], symbol: str) -> Optional[SentimentResult]:
        """Get cached sentiment result"""
        if self.cache:
            return self.cache.get(text_data, symbol)
        return None
    
    def cache_sentiment(self, text_data: List[str], symbol: str, result: SentimentResult) -> None:
        """Cache sentiment result"""
        if self.cache:
            self.cache.put(text_data, symbol, result)
    
    def clear_cache(self) -> None:
        """Clear sentiment cache"""
        if self.cache:
            self.cache.clear()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        if self.cache:
            return self.cache.get_stats()
        return {"cache_enabled": False}
    
    def update_source_weights(self, new_weights: Dict[str, float]) -> None:
        """Update source reliability weights"""
        for source, weight in new_weights.items():
            if 0.0 <= weight <= 1.0:
                self.source_weights[source] = weight
                logger.info(f"Updated weight for {source}: {weight}")
            else:
                logger.warning(f"Invalid weight for {source}: {weight}. Must be between 0.0 and 1.0")
    
    def analyze_result_patterns(self, results: List[SentimentResult]) -> Dict[str, Any]:
        """Analyze patterns in sentiment results"""
        if not results:
            return {}
        
        scores = [r.sentiment_score for r in results]
        confidences = [r.confidence for r in results]
        
        analysis = {
            "count": len(results),
            "score_stats": {
                "mean": mean(scores),
                "std": stdev(scores) if len(scores) > 1 else 0.0,
                "min": min(scores),
                "max": max(scores),
                "range": max(scores) - min(scores)
            },
            "confidence_stats": {
                "mean": mean(confidences),
                "std": stdev(confidences) if len(confidences) > 1 else 0.0,
                "min": min(confidences),
                "max": max(confidences)
            },
            "source_distribution": {},
            "sentiment_distribution": {
                "bullish": sum(1 for s in scores if s > 0.1),
                "bearish": sum(1 for s in scores if s < -0.1),
                "neutral": sum(1 for s in scores if -0.1 <= s <= 0.1)
            }
        }
        
        # Count source distribution
        for result in results:
            for source in result.sources:
                analysis["source_distribution"][source] = analysis["source_distribution"].get(source, 0) + 1
        
        return analysis