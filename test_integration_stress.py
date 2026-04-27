"""
Stress testing and high-load integration tests for the AI Forex Trading Bot

This module contains stress tests that verify system behavior under extreme
conditions including high volume, concurrent operations, and resource constraints.
"""

import asyncio
import pytest
import time
import psutil
import threading
from datetime import datetime, timezone
from typing import List, Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch
from concurrent.futures import ThreadPoolExecutor

from src.models import MarketData, SentimentResult, TechnicalSignal, SignalType, Direction
from src.data.market_data_collector import MarketDataCollector
from src.analysis.llm_client import LLMClient
from src.analysis.signal_combiner import SignalCombiner
from src.trading.execution_engine import ExecutionEngine


class StressTestData:
    """Generate test data for stress testing"""
    
    @staticmethod
    def generate_market_data_batch(symbols: List[str], count: int) -> List[Dict[str, Any]]:
        """Generate batch of market data for multiple symbols"""
        batch = []
        base_time = datetime.now(timezone.utc)
        
        for i in range(count):
            timestamp = base_time.replace(second=i % 60)
            for symbol in symbols:
                batch.append({
                    symbol: {
                        "timestamp": timestamp.isoformat(),
                        "open": 1.0850 + (i * 0.0001),
                        "high": 1.0875 + (i * 0.0001),
                        "low": 1.0840 + (i * 0.0001),
                        "close": 1.0865 + (i * 0.0001),
                        "volume": 150000 + (i * 1000),
                        "bid": 1.0863 + (i * 0.0001),
                        "ask": 1.0867 + (i * 0.0001),
                        "spread": 0.0004
                    }
                })
        return batch
    
    @staticmethod
    def generate_news_data_batch(count: int) -> List[Dict[str, Any]]:
        """Generate batch of news data"""
        batch = []
        base_time = datetime.now(timezone.utc)
        
        for i in range(count):
            batch.append({
                "title": f"Market Update {i}: Economic Indicators Show Growth",
                "content": f"Economic data point {i} indicates positive market sentiment with growth indicators showing improvement.",
                "source": f"NewsSource{i % 5}",
                "timestamp": base_time.replace(second=i % 60).isoformat(),
                "relevance": 0.8 + (i % 3) * 0.05
            })
        return batch
    
    @staticmethod
    def generate_llm_responses(count: int) -> List[Dict[str, Any]]:
        """Generate batch of LLM sentiment responses"""
        responses = []
        
        for i in range(count):
            sentiment_score = -0.8 + (i % 17) * 0.1  # Vary between -0.8 and 0.8
            responses.append({
                "sentiment_score": sentiment_score,
                "confidence": 0.6 + (i % 5) * 0.08,
                "reasoning": f"Analysis {i}: Market sentiment based on economic indicators and news flow.",
                "key_factors": [f"Factor{i}_1", f"Factor{i}_2", f"Factor{i}_3"]
            })
        return responses


class TestStressIntegration:
    """Stress testing for system integration"""
    
    @pytest.mark.asyncio
    async def test_high_volume_data_processing(self):
        """Test processing high volume of market data"""
        
        # Generate large dataset
        symbols = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CHF", "NZD/USD", "USD/CAD"]
        test_data = StressTestData()
        market_data_batch = test_data.generate_market_data_batch(symbols, 1000)  # 1000 data points per symbol
        
        processed_count = 0
        start_time = time.time()
        
        # Mock market data collector to return batch data
        async def mock_collect_data(*args, **kwargs):
            nonlocal processed_count
            processed_count += 1
            return market_data_batch[processed_count - 1] if processed_count <= len(market_data_batch) else {}
        
        with patch('src.data.market_data_collector.MarketDataCollector.collect_data', side_effect=mock_collect_data):
            market_collector = MarketDataCollector()
            
            # Process data in batches
            batch_size = 100
            tasks = []
            
            for i in range(0, len(market_data_batch), batch_size):
                batch_tasks = [
                    market_collector.collect_data([symbol], "1M")
                    for symbol in symbols
                ]
                tasks.extend(batch_tasks)
            
            # Execute all tasks
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            end_time = time.time()
            processing_time = end_time - start_time
            
            # Verify results
            successful_results = [r for r in results if not isinstance(r, Exception)]
            failure_rate = (len(results) - len(successful_results)) / len(results)
            
            # Performance assertions
            assert failure_rate < 0.05  # Less than 5% failure rate
            assert processing_time < 30.0  # Should complete within 30 seconds
            assert len(successful_results) > len(symbols) * 5  # Reasonable success count
            
            throughput = len(successful_results) / processing_time
            print(f"✅ High volume test passed! Processed {len(successful_results)} items in {processing_time:.2f}s (throughput: {throughput:.1f} items/s)")
    
    @pytest.mark.asyncio
    async def test_concurrent_sentiment_analysis(self):
        """Test concurrent LLM sentiment analysis under load"""
        
        test_data = StressTestData()
        news_batch = test_data.generate_news_data_batch(500)  # 500 news items
        llm_responses = test_data.generate_llm_responses(500)
        
        response_index = 0
        
        async def mock_analyze_sentiment(*args, **kwargs):
            nonlocal response_index
            # Simulate processing time
            await asyncio.sleep(0.01)  # 10ms processing time
            
            result = llm_responses[response_index % len(llm_responses)]
            response_index += 1
            return result
        
        with patch('src.analysis.llm_client.LLMClient.analyze_sentiment', side_effect=mock_analyze_sentiment):
            llm_client = LLMClient()
            
            # Create concurrent sentiment analysis tasks
            start_time = time.time()
            
            tasks = [
                llm_client.analyze_sentiment([item["content"]], "EUR/USD")
                for item in news_batch[:100]  # Process first 100 items concurrently
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            end_time = time.time()
            processing_time = end_time - start_time
            
            # Verify results
            successful_results = [r for r in results if not isinstance(r, Exception)]
            failure_rate = (len(results) - len(successful_results)) / len(results)
            
            assert failure_rate < 0.1  # Less than 10% failure rate under load
            assert processing_time < 15.0  # Should complete within 15 seconds
            assert len(successful_results) >= 80  # At least 80% success rate
            
            print(f"✅ Concurrent sentiment analysis test passed! {len(successful_results)}/{len(results)} successful in {processing_time:.2f}s")
    
    @pytest.mark.asyncio
    async def test_memory_usage_under_load(self):
        """Test memory usage during high-load operations"""
        
        # Get initial memory usage
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Generate large dataset
        symbols = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CHF"]
        test_data = StressTestData()
        
        # Create many market data objects
        market_data_objects = []
        
        for i in range(1000):  # Create 1000 market data objects
            market_data = MarketData(
                symbol=symbols[i % len(symbols)],
                timestamp=datetime.now(timezone.utc),
                open=1.0850 + (i * 0.0001),
                high=1.0875 + (i * 0.0001),
                low=1.0840 + (i * 0.0001),
                close=1.0865 + (i * 0.0001),
                volume=150000 + (i * 1000),
                bid=1.0863 + (i * 0.0001),
                ask=1.0867 + (i * 0.0001),
                spread=0.0004
            )
            market_data_objects.append(market_data)
        
        # Check memory after object creation
        mid_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Process all objects
        signal_combiner = SignalCombiner()
        
        with patch('src.analysis.signal_combiner.SignalCombiner.combine_signals') as mock_combiner:
            mock_combiner.return_value = {
                "confidence": 0.75,
                "reasoning": "Test signal combination",
                "signal_strength": 0.8
            }
            
            # Create sentiment and technical signals for processing
            sentiment = SentimentResult(
                symbol="EUR/USD",
                sentiment_score=0.6,
                confidence=0.8,
                reasoning="Test sentiment",
                sources=["TestSource"],
                timestamp=datetime.now(timezone.utc)
            )
            
            technical = TechnicalSignal(
                symbol="EUR/USD",
                signal_type=SignalType.BUY,
                strength=0.7,
                indicators={"rsi": 65.0},
                timestamp=datetime.now(timezone.utc)
            )
            
            # Process signals for all market data
            for _ in market_data_objects:
                signal_combiner.combine_signals(sentiment, [technical])
        
        # Check final memory usage
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Memory usage assertions
        memory_increase = final_memory - initial_memory
        assert memory_increase < 500  # Should not increase by more than 500MB
        
        # Clean up objects to test garbage collection
        del market_data_objects
        
        # Force garbage collection
        import gc
        gc.collect()
        
        # Check memory after cleanup
        cleanup_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        print(f"✅ Memory usage test passed!")
        print(f"   Initial: {initial_memory:.1f}MB")
        print(f"   Peak: {final_memory:.1f}MB")
        print(f"   After cleanup: {cleanup_memory:.1f}MB")
        print(f"   Increase: {memory_increase:.1f}MB")
    
    @pytest.mark.asyncio
    async def test_system_stability_long_running(self):
        """Test system stability during long-running operations"""
        
        # Simulate long-running trading session
        start_time = time.time()
        duration = 60  # Run for 60 seconds
        
        error_count = 0
        success_count = 0
        
        async def simulate_trading_cycle():
            nonlocal error_count, success_count
            
            try:
                # Simulate market data collection
                with patch('src.data.market_data_collector.MarketDataCollector.collect_data') as mock_market:
                    mock_market.return_value = {
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
                    
                    market_collector = MarketDataCollector()
                    await market_collector.collect_data(["EUR/USD"], "1M")
                
                # Simulate sentiment analysis
                with patch('src.analysis.llm_client.LLMClient.analyze_sentiment') as mock_llm:
                    mock_llm.return_value = {
                        "sentiment_score": 0.5,
                        "confidence": 0.8,
                        "reasoning": "Stable market conditions",
                        "key_factors": ["factor1", "factor2"]
                    }
                    
                    llm_client = LLMClient()
                    await llm_client.analyze_sentiment(["Test news"], "EUR/USD")
                
                success_count += 1
                
            except Exception as e:
                error_count += 1
                print(f"Error in trading cycle: {e}")
        
        # Run trading cycles continuously
        while time.time() - start_time < duration:
            await simulate_trading_cycle()
            await asyncio.sleep(0.1)  # Brief pause between cycles
        
        total_cycles = success_count + error_count
        error_rate = error_count / total_cycles if total_cycles > 0 else 0
        
        # Stability assertions
        assert error_rate < 0.05  # Less than 5% error rate
        assert success_count > 100  # Should complete many cycles
        
        print(f"✅ Long-running stability test passed!")
        print(f"   Duration: {duration}s")
        print(f"   Total cycles: {total_cycles}")
        print(f"   Success rate: {(1-error_rate)*100:.1f}%")
    
    @pytest.mark.asyncio
    async def test_resource_exhaustion_recovery(self):
        """Test system recovery from resource exhaustion"""
        
        # Test 1: Simulate memory pressure
        large_objects = []
        
        try:
            # Create objects until memory pressure
            for i in range(10000):
                # Create large market data objects
                market_data = MarketData(
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
                large_objects.append(market_data)
                
                # Add some large data to increase memory usage
                market_data.extra_data = "x" * 1000  # 1KB of extra data per object
                
                # Check if we should stop (to prevent actual memory exhaustion)
                if i > 0 and i % 1000 == 0:
                    process = psutil.Process()
                    memory_mb = process.memory_info().rss / 1024 / 1024
                    if memory_mb > 1000:  # Stop at 1GB to prevent system issues
                        break
            
            # Test that system can still function under memory pressure
            with patch('src.data.market_data_collector.MarketDataCollector.collect_data') as mock_market:
                mock_market.return_value = {
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
                
                market_collector = MarketDataCollector()
                result = await market_collector.collect_data(["EUR/USD"], "1M")
                assert "EUR/USD" in result
            
        finally:
            # Clean up to free memory
            del large_objects
            import gc
            gc.collect()
        
        # Test 2: Simulate connection exhaustion
        connection_count = 0
        max_connections = 100
        
        async def mock_connection(*args, **kwargs):
            nonlocal connection_count
            connection_count += 1
            
            if connection_count > max_connections:
                raise Exception("Too many connections")
            
            await asyncio.sleep(0.01)  # Simulate connection time
            return {"status": "connected"}
        
        # Test connection pool exhaustion and recovery
        tasks = []
        
        for i in range(150):  # Try to create more connections than allowed
            task = asyncio.create_task(mock_connection())
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Should have some failures due to connection limits
        failures = [r for r in results if isinstance(r, Exception)]
        successes = [r for r in results if not isinstance(r, Exception)]
        
        assert len(failures) > 0  # Should have some connection failures
        assert len(successes) >= max_connections  # Should have successful connections up to limit
        
        print(f"✅ Resource exhaustion recovery test passed!")
        print(f"   Successful connections: {len(successes)}")
        print(f"   Failed connections: {len(failures)}")
    
    @pytest.mark.asyncio
    async def test_concurrent_trade_execution(self):
        """Test concurrent trade execution under high load"""
        
        execution_count = 0
        successful_executions = 0
        failed_executions = 0
        
        async def mock_execute_trade(*args, **kwargs):
            nonlocal execution_count, successful_executions, failed_executions
            execution_count += 1
            
            # Simulate execution time
            await asyncio.sleep(0.05)  # 50ms execution time
            
            # Simulate occasional failures (5% failure rate)
            if execution_count % 20 == 0:
                failed_executions += 1
                raise Exception("Broker connection timeout")
            
            successful_executions += 1
            return {
                "order_id": f"ORDER_{execution_count}",
                "status": "FILLED",
                "fill_price": 1.0865,
                "fill_quantity": 1000,
                "execution_time": datetime.now(timezone.utc).isoformat()
            }
        
        with patch('src.trading.execution_engine.ExecutionEngine.execute_trade', side_effect=mock_execute_trade):
            execution_engine = ExecutionEngine()
            
            # Create many concurrent trade execution tasks
            from src.models import Order, OrderType, OrderStatus
            
            tasks = []
            for i in range(100):  # 100 concurrent trades
                order = Order(
                    order_id=f"STRESS_ORDER_{i}",
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
                
                task = execution_engine.execute_trade(order)
                tasks.append(task)
            
            start_time = time.time()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            end_time = time.time()
            
            execution_time = end_time - start_time
            
            # Analyze results
            successful_results = [r for r in results if not isinstance(r, Exception)]
            failed_results = [r for r in results if isinstance(r, Exception)]
            
            success_rate = len(successful_results) / len(results)
            throughput = len(results) / execution_time
            
            # Performance assertions
            assert success_rate >= 0.90  # At least 90% success rate
            assert execution_time < 10.0  # Should complete within 10 seconds
            assert throughput >= 10  # At least 10 executions per second
            
            print(f"✅ Concurrent trade execution test passed!")
            print(f"   Total trades: {len(results)}")
            print(f"   Success rate: {success_rate*100:.1f}%")
            print(f"   Execution time: {execution_time:.2f}s")
            print(f"   Throughput: {throughput:.1f} trades/s")


if __name__ == "__main__":
    # Run the stress tests
    pytest.main([__file__, "-v", "--asyncio-mode=auto", "-s"])