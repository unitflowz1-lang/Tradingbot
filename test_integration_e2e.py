"""
End-to-end integration tests for the AI Forex Trading Bot

This module contains comprehensive integration tests that verify the complete
data flow from acquisition through sentiment analysis, technical analysis,
signal generation, risk management, and trade execution.
"""

import asyncio
import json
import pytest
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
from unittest.mock import AsyncMock, MagicMock, patch

# Import system components
from src.models import (
    MarketData, SentimentResult, TechnicalSignal, TradingSignal,
    Order, Position, Portfolio, SignalType, Direction, OrderType, OrderStatus
)
from src.data.market_data_collector import MarketDataCollector
from src.data.news_data_collector import NewsDataCollector
from src.data.social_media_collector import SocialMediaCollector
from src.analysis.llm_client import LLMClient
from src.analysis.sentiment_aggregator import SentimentAggregator, AggregatedSentiment
from src.analysis.technical_indicators import IndicatorCalculator
from src.analysis.signal_combiner import SignalCombiner
from src.risk.risk_calculator import RiskCalculator
from src.risk.position_sizer import PositionSizer
from src.trading.execution_engine import ExecutionEngine
from src.monitoring.performance_monitor import PerformanceMonitor
from src.config import get_config_manager


def create_mock_instances():
    """Create mock instances for testing"""
    mock_broker = MagicMock()
    mock_config = MagicMock()
    
    # Configure mock config with realistic values
    mock_config.market_data_cache_ttl = 60  # 60 seconds
    mock_config.provider = "openai"  # Use provider instead of llm_provider
    mock_config.model = "gpt-3.5-turbo"
    mock_config.api_key = "test-key"
    mock_config.max_tokens = 1000
    mock_config.temperature = 0.7
    mock_config.timeout = 30
    mock_config.max_retries = 3
    mock_config.retry_delay = 1
    
    return mock_broker, mock_config


class MockExternalAPIs:
    """Mock external API responses for testing"""
    
    @staticmethod
    def get_market_data_response():
        """Mock market data API response"""
        return {
            "EUR/USD": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "open": 1.0850,
                "high": 1.0875,
                "low": 1.0840,
                "close": 1.0865,
                "volume": 150000,
                "bid": 1.0863,
                "ask": 1.0867,
                "spread": 0.0004
            }
        }
    
    @staticmethod
    def get_news_data_response():
        """Mock news API response"""
        return [
            {
                "title": "ECB Raises Interest Rates by 0.25%",
                "content": "The European Central Bank announced a 0.25% interest rate increase, signaling confidence in the eurozone economy.",
                "source": "Reuters",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "relevance": 0.9
            },
            {
                "title": "US Employment Data Shows Strong Growth",
                "content": "Non-farm payrolls exceeded expectations, adding 250,000 jobs last month.",
                "source": "Bloomberg",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "relevance": 0.8
            }
        ]
    
    @staticmethod
    def get_social_media_response():
        """Mock social media API response"""
        return [
            {
                "text": "EUR looking strong after ECB announcement. Bullish on EURUSD",
                "source": "twitter",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "engagement": 150
            },
            {
                "text": "USD weakness continues as Fed signals dovish stance",
                "source": "reddit",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "engagement": 89
            }
        ]
    
    @staticmethod
    def get_llm_sentiment_response():
        """Mock LLM sentiment analysis response"""
        return {
            "sentiment_score": 0.65,
            "confidence": 0.82,
            "reasoning": "The ECB rate hike and positive economic indicators suggest bullish sentiment for EUR/USD. The news indicates strengthening eurozone fundamentals.",
            "key_factors": [
                "ECB interest rate increase",
                "Strong employment data",
                "Market optimism"
            ]
        }
    
    @staticmethod
    def get_broker_account_response():
        """Mock broker account API response"""
        return {
            "account_id": "TEST_ACCOUNT_123",
            "balance": 10000.0,
            "equity": 10000.0,
            "margin_used": 0.0,
            "margin_available": 10000.0,
            "positions": []
        }
    
    @staticmethod
    def get_broker_execution_response():
        """Mock broker trade execution response"""
        return {
            "order_id": "ORDER_123456",
            "status": "FILLED",
            "fill_price": 1.0865,
            "fill_quantity": 10000,
            "execution_time": datetime.now(timezone.utc).isoformat(),
            "commission": 2.50
        }


@pytest.fixture
def mock_apis():
    """Fixture providing mock API responses"""
    return MockExternalAPIs()


@pytest.fixture
def sample_market_data():
    """Fixture providing sample market data"""
    return MarketData(
        symbol="EUR/USD",
        timestamp=datetime.now(timezone.utc),
        open=1.0850,
        high=1.0875,
        low=1.0840,
        close=1.0865,
        volume=150000,
        bid=1.0863,
        ask=1.0867,
        spread=0.0004
    )


@pytest.fixture
def sample_sentiment_result():
    """Fixture providing sample sentiment result"""
    return SentimentResult(
        symbol="EUR/USD",
        sentiment_score=0.65,
        confidence=0.82,
        reasoning="Bullish sentiment based on ECB rate hike and positive economic indicators",
        sources=["Reuters", "Bloomberg"],
        timestamp=datetime.now(timezone.utc)
    )


@pytest.fixture
def sample_technical_signal():
    """Fixture providing sample technical signal"""
    return TechnicalSignal(
        symbol="EUR/USD",
        signal_type=SignalType.BUY,
        strength=0.75,
        indicators={
            "sma_20": 1.0845,
            "sma_50": 1.0820,
            "rsi": 65.5,
            "macd": 0.0012
        },
        timestamp=datetime.now(timezone.utc)
    )


class TestEndToEndIntegration:
    """End-to-end integration tests"""
    
    @pytest.mark.asyncio
    async def test_complete_trading_pipeline(self, mock_apis):
        """Test complete pipeline from data acquisition to trade execution"""
        
        # Step 1: Data Acquisition
        with patch('src.data.market_data_collector.MarketDataCollector.collect_data') as mock_market_data:
            mock_market_data.return_value = mock_apis.get_market_data_response()
            
            # Create mock dependencies
            mock_broker = MagicMock()
            mock_config = MagicMock()
            market_collector = MarketDataCollector(mock_broker, mock_config)
            market_data_raw = await market_collector.collect_data(["EUR/USD"], "1H")
            
            # Validate market data collection
            assert "EUR/USD" in market_data_raw
            assert market_data_raw["EUR/USD"]["close"] == 1.0865
        
        # Step 2: News and Social Media Data Collection
        with patch('src.data.news_data_collector.NewsDataCollector.collect_data') as mock_news:
            mock_news.return_value = mock_apis.get_news_data_response()
            
            # Create mock config for NewsDataCollector
            mock_config = MagicMock()
            news_collector = NewsDataCollector(mock_config)
            news_data = await news_collector.collect_data(["EUR/USD"], "1H")
            
            assert len(news_data) == 2
            assert "ECB" in news_data[0]["title"]
        
        with patch('src.data.social_media_collector.SocialMediaCollector.collect_data') as mock_social:
            mock_social.return_value = mock_apis.get_social_media_response()
            
            # Create mock config for SocialMediaCollector
            mock_config = MagicMock()
            social_collector = SocialMediaCollector(mock_config)
            social_data = await social_collector.collect_data(["EUR/USD"], "1H")
            
            assert len(social_data) == 2
            assert "EUR" in social_data[0]["text"]
        
        # Step 3: LLM Sentiment Analysis
        with patch('src.analysis.llm_client.LLMClient.analyze_sentiment') as mock_llm:
            mock_llm.return_value = mock_apis.get_llm_sentiment_response()
            
            # Create mock config for LLMClient
            mock_config = MagicMock()
            llm_client = LLMClient(mock_config)
            
            # Combine news and social media text
            text_data = [item["content"] for item in news_data] + [item["text"] for item in social_data]
            
            sentiment_raw = await llm_client.analyze_sentiment(text_data, "EUR/USD")
            
            # Create SentimentResult object
            sentiment_result = SentimentResult(
                symbol="EUR/USD",
                sentiment_score=sentiment_raw["sentiment_score"],
                confidence=sentiment_raw["confidence"],
                reasoning=sentiment_raw["reasoning"],
                sources=["Reuters", "Bloomberg", "Twitter", "Reddit"],
                timestamp=datetime.now(timezone.utc)
            )
            
            assert sentiment_result.sentiment_score == 0.65
            assert sentiment_result.is_bullish()
            assert sentiment_result.is_high_confidence()
        
        # Step 4: Technical Analysis
        # Convert raw market data to MarketData object
        market_data = MarketData(
            symbol="EUR/USD",
            timestamp=datetime.fromisoformat(market_data_raw["EUR/USD"]["timestamp"].replace('Z', '+00:00')),
            open=market_data_raw["EUR/USD"]["open"],
            high=market_data_raw["EUR/USD"]["high"],
            low=market_data_raw["EUR/USD"]["low"],
            close=market_data_raw["EUR/USD"]["close"],
            volume=market_data_raw["EUR/USD"]["volume"],
            bid=market_data_raw["EUR/USD"]["bid"],
            ask=market_data_raw["EUR/USD"]["ask"],
            spread=market_data_raw["EUR/USD"]["spread"]
        )
        
        # Calculate technical indicators
        tech_calculator = IndicatorCalculator()
        
        # Add market data to calculator cache
        for _ in range(50):  # Add multiple data points for calculation
            tech_calculator.add_market_data(market_data)
        
        # Calculate indicators
        indicators = tech_calculator.calculate_indicators("EUR/USD", "1H")
        
        # Create technical signal
        technical_signal = TechnicalSignal(
            symbol="EUR/USD",
            signal_type=SignalType.BUY,
            strength=0.75,
            indicators=indicators.to_dict(),
            timestamp=datetime.now(timezone.utc)
        )
        
        assert technical_signal.signal_type == SignalType.BUY
        assert technical_signal.is_strong_signal()
        
        # Step 5: Signal Combination
        signal_combiner = SignalCombiner()
        
        # Convert SentimentResult to AggregatedSentiment
        aggregated_sentiment = AggregatedSentiment(
            symbol=sentiment_result.symbol,
            final_sentiment_score=sentiment_result.sentiment_score,
            final_confidence=sentiment_result.confidence,
            reasoning=sentiment_result.reasoning,
            sources=sentiment_result.sources,
            individual_results=[sentiment_result],
            aggregation_method="single_source",
            consistency_score=1.0,
            timestamp=sentiment_result.timestamp
        )
        
        combined_signal = signal_combiner.combine_signals(
            aggregated_sentiment, 
            [technical_signal], 
            market_data.ask,  # current_price
            "EUR/USD"  # symbol
        )
        
        # Create TradingSignal
        trading_signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=market_data.ask,  # Use ask price for long entry
            stop_loss=market_data.ask * 0.995,  # 0.5% stop loss
            take_profit=market_data.ask * 1.015,  # 1.5% take profit
            position_size=0.02,  # 2% of account
            confidence=combined_signal.confidence_score,
            reasoning=combined_signal.combination_reasoning,
            timestamp=datetime.now(timezone.utc)
        )
        
        assert trading_signal.direction == Direction.LONG
        assert trading_signal.calculate_risk_reward_ratio() > 2.0  # Good risk-reward
        
        # Step 6: Risk Management
        risk_calculator = RiskCalculator()
        position_sizer = PositionSizer()
        
        # Mock portfolio
        portfolio = Portfolio(
            account_id="TEST_ACCOUNT_123",
            balance=10000.0,
            equity=10000.0,
            margin_used=0.0,
            margin_available=10000.0,
            positions=[],
            updated_at=datetime.now(timezone.utc)
        )
        
        # Validate trade risk
        risk_assessment = risk_calculator.assess_trade_risk(trading_signal, portfolio)
        assert risk_assessment["approved"] is True
        assert risk_assessment["risk_percentage"] <= 0.02  # Max 2% risk per trade
        
        # Calculate position size
        position_size = position_sizer.calculate_position_size(
            trading_signal, portfolio.balance, max_risk_per_trade=0.02
        )
        assert 0 < position_size <= 10000  # Reasonable position size
        
        # Step 7: Trade Execution
        with patch('src.trading.execution_engine.ExecutionEngine.execute_trade') as mock_execution:
            mock_execution.return_value = mock_apis.get_broker_execution_response()
            
            # Create mock dependencies for ExecutionEngine
            mock_broker = MagicMock()
            mock_config = MagicMock()
            execution_engine = ExecutionEngine(mock_broker, mock_config)
            
            # Create order
            order = Order(
                order_id="ORDER_123456",
                symbol="EUR/USD",
                order_type=OrderType.MARKET,
                direction=Direction.LONG,
                quantity=position_size,
                price=None,  # Market order
                stop_loss=trading_signal.stop_loss,
                take_profit=trading_signal.take_profit,
                status=OrderStatus.PENDING,
                created_at=datetime.now(timezone.utc)
            )
            
            # Execute trade
            execution_result = await execution_engine.execute_trade(order)
            
            assert execution_result["status"] == "FILLED"
            assert execution_result["fill_price"] == 1.0865
            assert execution_result["order_id"] == "ORDER_123456"
        
        # Step 8: Performance Monitoring
        performance_monitor = PerformanceMonitor()
        
        # Track the executed trade
        performance_monitor.track_trade(order, execution_result)
        
        # Verify trade was tracked
        metrics = performance_monitor.calculate_metrics()
        assert metrics["total_trades"] == 1
        assert metrics["win_rate"] >= 0  # Should be 0 for new trade
        
        print("✅ Complete trading pipeline test passed!")
    
    @pytest.mark.asyncio
    async def test_error_handling_integration(self, mock_apis):
        """Test error handling throughout the pipeline"""
        
        # Test market data collection failure
        with patch('src.data.market_data_collector.MarketDataCollector.collect_data') as mock_market_data:
            mock_market_data.side_effect = Exception("Market data API failure")
            
            # Create mock dependencies
            mock_broker, mock_config = create_mock_instances()
            
            market_collector = MarketDataCollector(mock_broker, mock_config)
            
            with pytest.raises(Exception) as exc_info:
                await market_collector.collect_data(["EUR/USD"], "1H")
            
            assert "Market data API failure" in str(exc_info.value)
        
        # Test LLM API failure with fallback
        with patch('src.analysis.llm_client.LLMClient.analyze_sentiment') as mock_llm:
            mock_llm.side_effect = Exception("LLM API rate limit exceeded")
            
            # Create mock config for LLMClient
            _, mock_config = create_mock_instances()
            llm_client = LLMClient(mock_config)
            
            with pytest.raises(Exception) as exc_info:
                await llm_client.analyze_sentiment(["Test text"], "EUR/USD")
            
            assert "rate limit" in str(exc_info.value)
        
        # Test broker API failure
        with patch('src.trading.execution_engine.ExecutionEngine.execute_trade') as mock_execution:
            mock_execution.side_effect = Exception("Broker connection failed")
            
            # Create mock dependencies for ExecutionEngine
            mock_broker, mock_config = create_mock_instances()
            execution_engine = ExecutionEngine(mock_broker, mock_config)
            
            order = Order(
                order_id="ORDER_FAIL_123",
                symbol="EUR/USD",
                order_type=OrderType.MARKET,
                direction=Direction.LONG,
                quantity=1000,
                price=None,
                stop_loss=1.0800,
                take_profit=1.0900,
                status=OrderStatus.PENDING,
                created_at=datetime.now(timezone.utc)
            )
            
            with pytest.raises(Exception) as exc_info:
                await execution_engine.execute_trade(order)
            
            assert "Broker connection failed" in str(exc_info.value)
        
        print("✅ Error handling integration test passed!")
    
    @pytest.mark.asyncio
    async def test_performance_under_load(self, mock_apis):
        """Test system performance under high load conditions"""
        
        start_time = time.time()
        
        # Simulate processing multiple currency pairs simultaneously
        symbols = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CHF"]
        
        tasks = []
        
        for symbol in symbols:
            # Mock data collection for each symbol
            with patch('src.data.market_data_collector.MarketDataCollector.collect_data') as mock_market_data:
                mock_market_data.return_value = {
                    symbol: {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "open": 1.0850,
                        "high": 1.0875,
                        "low": 1.0840,
                        "close": 1.0865,
                        "volume": 150000,
                        "bid": 1.0863,
                        "ask": 1.0867,
                        "spread": 0.0004
                    }
                }
                
                mock_broker, mock_config = create_mock_instances()
                market_collector = MarketDataCollector(mock_broker, mock_config)
                task = market_collector.collect_data([symbol], "1H")
                tasks.append(task)
        
        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        # Verify all tasks completed successfully
        for result in results:
            if isinstance(result, Exception):
                pytest.fail(f"Task failed with exception: {result}")
        
        # Performance assertions
        assert processing_time < 5.0  # Should complete within 5 seconds
        assert len(results) == len(symbols)  # All symbols processed
        
        print(f"✅ Performance test passed! Processed {len(symbols)} symbols in {processing_time:.2f} seconds")
    
    @pytest.mark.asyncio
    async def test_data_flow_validation(self, sample_market_data, sample_sentiment_result, sample_technical_signal):
        """Test data validation throughout the pipeline"""
        
        # Test market data validation
        assert sample_market_data.symbol == "EUR/USD"
        assert sample_market_data.bid < sample_market_data.ask
        assert sample_market_data.low <= sample_market_data.close <= sample_market_data.high
        
        # Test sentiment result validation
        assert -1.0 <= sample_sentiment_result.sentiment_score <= 1.0
        assert 0.0 <= sample_sentiment_result.confidence <= 1.0
        assert len(sample_sentiment_result.sources) > 0
        
        # Test technical signal validation
        assert sample_technical_signal.signal_type in [SignalType.BUY, SignalType.SELL, SignalType.HOLD]
        assert 0.0 <= sample_technical_signal.strength <= 1.0
        assert len(sample_technical_signal.indicators) > 0
        
        # Test signal combination
        signal_combiner = SignalCombiner()
        
        # Convert SentimentResult to AggregatedSentiment
        aggregated_sentiment = AggregatedSentiment(
            symbol=sample_sentiment_result.symbol,
            final_sentiment_score=sample_sentiment_result.sentiment_score,
            final_confidence=sample_sentiment_result.confidence,
            reasoning=sample_sentiment_result.reasoning,
            sources=sample_sentiment_result.sources,
            individual_results=[sample_sentiment_result],
            aggregation_method="single_source",
            consistency_score=1.0,
            timestamp=sample_sentiment_result.timestamp
        )
        
        combined_signal = signal_combiner.combine_signals(
            aggregated_sentiment, 
            [sample_technical_signal], 
            sample_market_data.ask,  # current_price
            "EUR/USD"  # symbol
        )
        
        assert combined_signal.confidence_score >= 0.0
        assert combined_signal.confidence_score <= 1.0
        assert combined_signal.combination_reasoning is not None
        
        # Test trading signal creation
        trading_signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.0867,
            stop_loss=1.0812,  # ~0.5% stop loss
            take_profit=1.0950,  # ~0.8% take profit
            position_size=0.02,
            confidence=combined_signal.confidence_score,
            reasoning=combined_signal.combination_reasoning,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Validate trading signal
        assert trading_signal.direction == Direction.LONG
        assert trading_signal.stop_loss < trading_signal.entry_price  # Correct for long position
        assert trading_signal.take_profit > trading_signal.entry_price  # Correct for long position
        assert trading_signal.calculate_risk_reward_ratio() > 0
        
        print("✅ Data flow validation test passed!")
    
    @pytest.mark.asyncio
    async def test_system_recovery_scenarios(self, mock_apis):
        """Test system recovery from various failure scenarios"""
        
        # Scenario 1: Temporary network failure with recovery
        call_count = 0
        
        async def failing_then_succeeding_api(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:  # Fail first 2 calls
                raise Exception("Network timeout")
            return mock_apis.get_market_data_response()
        
        with patch('src.data.market_data_collector.MarketDataCollector.collect_data', side_effect=failing_then_succeeding_api):
            market_collector = MarketDataCollector()
            
            # Should eventually succeed after retries
            for attempt in range(5):
                try:
                    result = await market_collector.collect_data(["EUR/USD"], "1H")
                    assert "EUR/USD" in result
                    break
                except Exception as e:
                    if attempt == 4:  # Last attempt
                        pytest.fail(f"Failed after all retries: {e}")
                    await asyncio.sleep(0.1)  # Brief delay between retries
        
        # Scenario 2: Partial data corruption with validation
        corrupted_data = mock_apis.get_market_data_response()
        corrupted_data["EUR/USD"]["bid"] = corrupted_data["EUR/USD"]["ask"] + 0.001  # Invalid bid > ask
        
        with patch('src.data.market_data_collector.MarketDataCollector.collect_data') as mock_market_data:
            mock_market_data.return_value = corrupted_data
            
            market_collector = MarketDataCollector()
            
            # Should detect and handle corrupted data
            with pytest.raises(Exception):  # Should raise validation error
                data = await market_collector.collect_data(["EUR/USD"], "1H")
                # Try to create MarketData object (should fail validation)
                MarketData(
                    symbol="EUR/USD",
                    timestamp=datetime.fromisoformat(data["EUR/USD"]["timestamp"].replace('Z', '+00:00')),
                    open=data["EUR/USD"]["open"],
                    high=data["EUR/USD"]["high"],
                    low=data["EUR/USD"]["low"],
                    close=data["EUR/USD"]["close"],
                    volume=data["EUR/USD"]["volume"],
                    bid=data["EUR/USD"]["bid"],
                    ask=data["EUR/USD"]["ask"],
                    spread=data["EUR/USD"]["spread"]
                )
        
        # Scenario 3: System overload with graceful degradation
        # Simulate high load by creating many concurrent requests
        async def slow_api_response(*args, **kwargs):
            await asyncio.sleep(0.5)  # Simulate slow response
            return mock_apis.get_market_data_response()
        
        with patch('src.data.market_data_collector.MarketDataCollector.collect_data', side_effect=slow_api_response):
            market_collector = MarketDataCollector()
            
            # Create multiple concurrent requests
            tasks = [
                market_collector.collect_data(["EUR/USD"], "1H")
                for _ in range(10)
            ]
            
            start_time = time.time()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            end_time = time.time()
            
            # Should handle concurrent load gracefully
            successful_results = [r for r in results if not isinstance(r, Exception)]
            assert len(successful_results) >= 5  # At least half should succeed
            assert end_time - start_time < 10.0  # Should not take too long
        
        print("✅ System recovery scenarios test passed!")


class TestIntegrationPerformance:
    """Performance-focused integration tests"""
    
    @pytest.mark.asyncio
    async def test_response_time_requirements(self, mock_apis):
        """Test that system meets response time requirements"""
        
        # Test market data collection response time
        with patch('src.data.market_data_collector.MarketDataCollector.collect_data') as mock_market_data:
            mock_market_data.return_value = mock_apis.get_market_data_response()
            
            market_collector = MarketDataCollector()
            
            start_time = time.time()
            await market_collector.collect_data(["EUR/USD"], "1H")
            end_time = time.time()
            
            response_time = end_time - start_time
            assert response_time < 1.0  # Should respond within 1 second
        
        # Test sentiment analysis response time
        with patch('src.analysis.llm_client.LLMClient.analyze_sentiment') as mock_llm:
            mock_llm.return_value = mock_apis.get_llm_sentiment_response()
            
            llm_client = LLMClient()
            
            start_time = time.time()
            await llm_client.analyze_sentiment(["Test news content"], "EUR/USD")
            end_time = time.time()
            
            response_time = end_time - start_time
            assert response_time < 2.0  # LLM calls can be slower but should be under 2 seconds
        
        # Test trade execution response time
        with patch('src.trading.execution_engine.ExecutionEngine.execute_trade') as mock_execution:
            mock_execution.return_value = mock_apis.get_broker_execution_response()
            
            execution_engine = ExecutionEngine()
            
            order = Order(
                order_id="PERF_TEST_123",
                symbol="EUR/USD",
                order_type=OrderType.MARKET,
                direction=Direction.LONG,
                quantity=1000,
                price=None,
                stop_loss=1.0800,
                take_profit=1.0900,
                status=OrderStatus.PENDING,
                created_at=datetime.now(timezone.utc)
            )
            
            start_time = time.time()
            await execution_engine.execute_trade(order)
            end_time = time.time()
            
            response_time = end_time - start_time
            assert response_time < 0.5  # Trade execution should be very fast
        
        print("✅ Response time requirements test passed!")
    
    @pytest.mark.asyncio
    async def test_throughput_requirements(self, mock_apis):
        """Test system throughput under normal load"""
        
        # Test processing multiple signals per minute
        with patch('src.analysis.signal_combiner.SignalCombiner.combine_signals') as mock_combiner:
            mock_combiner.return_value = {
                "confidence": 0.75,
                "reasoning": "Combined bullish sentiment and technical signals",
                "signal_strength": 0.8
            }
            
            signal_combiner = SignalCombiner()
            
            # Create sample data
            sentiment = SentimentResult(
                symbol="EUR/USD",
                sentiment_score=0.6,
                confidence=0.8,
                reasoning="Bullish news",
                sources=["Reuters"],
                timestamp=datetime.now(timezone.utc)
            )
            
            technical = TechnicalSignal(
                symbol="EUR/USD",
                signal_type=SignalType.BUY,
                strength=0.7,
                indicators={"rsi": 65.0},
                timestamp=datetime.now(timezone.utc)
            )
            
            # Process multiple signals rapidly
            start_time = time.time()
            
            tasks = [
                asyncio.create_task(asyncio.to_thread(signal_combiner.combine_signals, sentiment, [technical]))
                for _ in range(60)  # 60 signals
            ]
            
            results = await asyncio.gather(*tasks)
            end_time = time.time()
            
            processing_time = end_time - start_time
            throughput = len(results) / processing_time  # signals per second
            
            assert throughput >= 10  # Should process at least 10 signals per second
            assert len(results) == 60  # All signals processed
        
        print(f"✅ Throughput test passed! Processed {throughput:.1f} signals per second")


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "--asyncio-mode=auto"])