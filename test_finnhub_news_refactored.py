#!/usr/bin/env python3
"""
Test Suite for Refactored Finnhub News Fetching
================================================

Run this standalone to verify all helper functions work correctly.
No external dependencies needed for basic tests.

Usage:
    python test_finnhub_news_refactored.py

Expected output:
    ✓ All tests passed!
"""

import asyncio
import sys
import time
from datetime import datetime, timezone
from typing import List

# Import the refactored module
try:
    from FINNHUB_NEWS_FETCHING_REFACTORED import (
        NewsArticle,
        NewsResult,
        _clean_symbol,
        _split_symbol,
        _classify_sentiment,
        _calculate_weighted_sentiment,
        _matches_keywords,
        _deduplicate_articles,
        CURRENCY_KEYWORDS,
        SENTIMENT_RISK_MAPPING,
    )
    print("✓ Successfully imported refactored module\n")
except ImportError as e:
    print(f"✗ Failed to import refactored module: {e}")
    sys.exit(1)


# ============================================================================
# Test Suite
# ============================================================================

class TestSuite:
    """Test suite for refactored news fetching functions."""
    
    def __init__(self):
        self.tests_passed = 0
        self.tests_failed = 0
        self.test_results = []
    
    def assert_equal(self, actual, expected, message):
        """Assert that actual equals expected."""
        if actual == expected:
            self.tests_passed += 1
            self.test_results.append(f"✓ {message}")
            return True
        else:
            self.tests_failed += 1
            self.test_results.append(
                f"✗ {message}\n  Expected: {expected}\n  Got: {actual}"
            )
            return False
    
    def assert_true(self, condition, message):
        """Assert that condition is True."""
        if condition:
            self.tests_passed += 1
            self.test_results.append(f"✓ {message}")
            return True
        else:
            self.tests_failed += 1
            self.test_results.append(f"✗ {message}")
            return False
    
    def assert_in(self, item, container, message):
        """Assert that item is in container."""
        if item in container:
            self.tests_passed += 1
            self.test_results.append(f"✓ {message}")
            return True
        else:
            self.tests_failed += 1
            self.test_results.append(
                f"✗ {message}\n  {item} not found in {container}"
            )
            return False
    
    def test_symbol_cleaning(self):
        """Test symbol cleaning and normalization."""
        print("\n" + "=" * 70)
        print("TEST 1: Symbol Cleaning")
        print("=" * 70)
        
        test_cases = [
            ("AUD/USD", "AUDUSD", "Clean AUD/USD"),
            ("eur/usd", "EURUSD", "Clean lowercase eur/usd"),
            ("GBPUSD", "GBPUSD", "Already clean GBPUSD"),
            ("usd/jpy", "USDJPY", "Clean usd/jpy"),
            ("chf/usd", "CHFUSD", "Clean chf/usd"),
        ]
        
        for input_sym, expected, message in test_cases:
            result = _clean_symbol(input_sym)
            self.assert_equal(result, expected, message)
    
    def test_symbol_splitting(self):
        """Test symbol pair splitting."""
        print("\n" + "=" * 70)
        print("TEST 2: Symbol Splitting")
        print("=" * 70)
        
        test_cases = [
            ("AUDUSD", ("AUD", "USD"), "Split AUDUSD"),
            ("EURUSD", ("EUR", "USD"), "Split EURUSD"),
            ("GBPUSD", ("GBP", "USD"), "Split GBPUSD"),
            ("USDJPY", ("USD", "JPY"), "Split USDJPY"),
        ]
        
        for input_sym, expected, message in test_cases:
            result = _split_symbol(input_sym)
            self.assert_equal(result, expected, message)
    
    def test_sentiment_classification(self):
        """Test sentiment classification."""
        print("\n" + "=" * 70)
        print("TEST 3: Sentiment Classification")
        print("=" * 70)
        
        test_cases = [
            ("The euro surged on strong economic growth", "bullish", "Bullish: surge"),
            ("Markets crashed on recession fears", "bearish", "Bearish: crashed"),
            ("The central bank held rates steady", "neutral", "Neutral: no sentiment"),
            ("Stock market rally as inflation eases", "bullish", "Bullish: rally"),
            ("Currency plunges amid weak data", "bearish", "Bearish: plunges"),
            ("Forex markets unchanged today", "neutral", "Neutral: unchanged"),
        ]
        
        for text, expected, message in test_cases:
            result = _classify_sentiment(text)
            self.assert_equal(result, expected, message)
    
    def test_weighted_sentiment_calculation(self):
        """Test weighted sentiment score calculation."""
        print("\n" + "=" * 70)
        print("TEST 4: Weighted Sentiment Calculation")
        print("=" * 70)
        
        now = int(time.time())
        
        # Test 1: Empty articles -> neutral
        result = _calculate_weighted_sentiment([])
        self.assert_equal(result, 0.5, "Empty articles returns neutral (0.5)")
        
        # Test 2: Single recent bullish article
        articles = [
            NewsArticle("Test", "", "src", "http://a", now, "bullish", 0.8)
        ]
        result = _calculate_weighted_sentiment(articles)
        self.assert_equal(result, 0.8, "Single bullish article = 0.8")
        
        # Test 3: Single recent bearish article
        articles = [
            NewsArticle("Test", "", "src", "http://b", now, "bearish", 0.2)
        ]
        result = _calculate_weighted_sentiment(articles)
        self.assert_equal(result, 0.2, "Single bearish article = 0.2")
        
        # Test 4: Recent bullish weighted more than old bearish
        articles = [
            NewsArticle("Recent", "", "src", "http://c", now, "bullish", 0.8),
            NewsArticle("Old", "", "src", "http://d", now - 7200, "bearish", 0.2),
        ]
        result = _calculate_weighted_sentiment(articles)
        self.assert_true(
            result > 0.5,
            "Recent bullish (0.8) weighted more than old bearish (0.2), result > 0.5"
        )
    
    def test_keyword_matching(self):
        """Test keyword matching for currency relevance."""
        print("\n" + "=" * 70)
        print("TEST 5: Keyword Matching")
        print("=" * 70)
        
        # Test AUD keywords
        aud_keywords = CURRENCY_KEYWORDS["AUD"]
        article_aud = NewsArticle(
            "Australian dollar surges", "", "src", "http://x", int(time.time()),
            "bullish", 0.8
        )
        matches_aud = _matches_keywords(article_aud, aud_keywords, "AUD")
        self.assert_true(
            matches_aud,
            "Article about 'Australian dollar' matches AUD keywords"
        )
        
        # Test USD keywords
        usd_keywords = CURRENCY_KEYWORDS["USD"]
        article_usd = NewsArticle(
            "Fed raises interest rates", "", "src", "http://y", int(time.time()),
            "bearish", 0.3
        )
        matches_usd = _matches_keywords(article_usd, usd_keywords, "USD")
        self.assert_true(
            matches_usd,
            "Article about 'Fed' matches USD keywords"
        )
        
        # Test non-matching
        article_other = NewsArticle(
            "Tech stocks rally", "", "src", "http://z", int(time.time()),
            "bullish", 0.8
        )
        matches_other = _matches_keywords(article_other, aud_keywords, "AUD")
        self.assert_true(
            not matches_other,
            "Article about 'Tech stocks' does NOT match AUD keywords"
        )
    
    def test_article_deduplication(self):
        """Test article deduplication by URL."""
        print("\n" + "=" * 70)
        print("TEST 6: Article Deduplication")
        print("=" * 70)
        
        now = int(time.time())
        articles = [
            NewsArticle("Article 1", "", "src1", "http://a", now, "bullish", 0.8),
            NewsArticle("Article 2", "", "src2", "http://b", now, "bearish", 0.2),
            NewsArticle("Duplicate 1", "", "src3", "http://a", now, "bullish", 0.7),  # Duplicate
            NewsArticle("Article 3", "", "src4", "http://c", now, "neutral", 0.5),
            NewsArticle("Duplicate 2", "", "src5", "http://b", now - 3600, "bearish", 0.3),  # Duplicate
        ]
        
        deduped = _deduplicate_articles(articles)
        
        self.assert_equal(
            len(deduped), 3,
            "Deduplication removes 2 duplicates (5 -> 3 articles)"
        )
        
        urls = [a.url for a in deduped]
        self.assert_in("http://a", urls, "URL http://a present in deduped results")
        self.assert_in("http://b", urls, "URL http://b present in deduped results")
        self.assert_in("http://c", urls, "URL http://c present in deduped results")
    
    def test_sentiment_risk_mapping(self):
        """Test sentiment to risk score mapping."""
        print("\n" + "=" * 70)
        print("TEST 7: Sentiment Risk Mapping")
        print("=" * 70)
        
        test_cases = [
            ("bullish", -0.2, "Bullish reduces risk"),
            ("positive", -0.2, "Positive reduces risk"),
            ("bearish", 0.3, "Bearish increases risk"),
            ("negative", 0.3, "Negative increases risk"),
            ("neutral", 0.0, "Neutral no change"),
        ]
        
        for sentiment, expected_risk, message in test_cases:
            result = SENTIMENT_RISK_MAPPING.get(sentiment, 0.0)
            self.assert_equal(result, expected_risk, message)
    
    def test_currency_keywords_coverage(self):
        """Test that all major currencies have keywords."""
        print("\n" + "=" * 70)
        print("TEST 8: Currency Keywords Coverage")
        print("=" * 70)
        
        required_currencies = ["EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD", "USD"]
        
        for currency in required_currencies:
            self.assert_true(
                currency in CURRENCY_KEYWORDS,
                f"Currency {currency} has keywords defined"
            )
            
            keywords = CURRENCY_KEYWORDS[currency]
            self.assert_true(
                len(keywords) > 0,
                f"Currency {currency} has at least one keyword"
            )
    
    def test_news_result_dataclass(self):
        """Test NewsResult dataclass."""
        print("\n" + "=" * 70)
        print("TEST 9: NewsResult Dataclass")
        print("=" * 70)
        
        now = int(time.time())
        articles = [
            NewsArticle("Test", "", "src", "http://test", now, "bullish", 0.8)
        ]
        
        result = NewsResult(
            articles=articles,
            sentiment_score=0.8,
            source="currency_specific"
        )
        
        self.assert_equal(len(result.articles), 1, "NewsResult stores articles")
        self.assert_equal(result.sentiment_score, 0.8, "NewsResult stores sentiment_score")
        self.assert_equal(result.source, "currency_specific", "NewsResult stores source")
        self.assert_equal(result.error, None, "NewsResult default error is None")
    
    def run_all(self):
        """Run all tests."""
        print("\n" + "=" * 70)
        print("FINNHUB NEWS FETCHING - REFACTORED CODE TEST SUITE")
        print("=" * 70)
        
        self.test_symbol_cleaning()
        self.test_symbol_splitting()
        self.test_sentiment_classification()
        self.test_weighted_sentiment_calculation()
        self.test_keyword_matching()
        self.test_article_deduplication()
        self.test_sentiment_risk_mapping()
        self.test_currency_keywords_coverage()
        self.test_news_result_dataclass()
        
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        for result in self.test_results:
            print(result)
        
        print("\n" + "=" * 70)
        if self.tests_failed == 0:
            print(f"✅ ALL TESTS PASSED ({self.tests_passed}/{self.tests_passed})")
            print("=" * 70)
            return True
        else:
            print(f"❌ TESTS FAILED: {self.tests_failed} failed, {self.tests_passed} passed")
            print("=" * 70)
            return False


# ============================================================================
# Main Execution
# ============================================================================

if __name__ == "__main__":
    suite = TestSuite()
    success = suite.run_all()
    sys.exit(0 if success else 1)
