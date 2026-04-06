"""Integration tests for LLM sentiment analysis engine"""

import pytest
import json
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone
from src.analysis.llm_client import LLMClient, LLMResponse
from src.analysis.prompt_engine import PromptEngine
from src.analysis.response_parser import ResponseParser
from src.analysis.sentiment_aggregator import SentimentAggregator
from src.config import LLMConfig
from src.models import SentimentResult


class TestLLMSentimentAnalysisIntegration:
    """Integration tests for the complete LLM sentiment analysis pipeline"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.config = LLMConfig(
            provider="openai",
            model="gpt-4",
            api_key="test-key",
            max_tokens=1000,
            temperature=0.1,
            timeout=30
        )
        
        self.llm_client = LLMClient(self.config)
        self.prompt_engine = PromptEngine()
        self.response_parser = ResponseParser()
        self.sentiment_aggregator = SentimentAggregator()
        
        self.symbol = "EUR/USD"
        self.text_data = [
            "European Central Bank raises interest rates by 0.25% to combat inflation",
            "EUR/USD reaches new monthly high as dollar weakens",
            "Market sentiment turns bullish on Euro following ECB decision"
        ]
    
    @pytest.mark.asyncio
    async def test_complete_sentiment_analysis_pipeline(self):
        """Test the complete sentiment analysis pipeline from text to aggregated result"""
        
        # Mock LLM responses for multiple analyses
        mock_responses = [
            {
                "sentiment_score": 0.7,
                "confidence": 0.8,
                "reasoning": "EUR/USD shows strong bullish momentum due to ECB rate hike",
                "sources": ["news"]
            },
            {
                "sentiment_score": 0.6,
                "confidence": 0.75,
                "reasoning": "Positive sentiment for EUR/USD based on central bank policy",
                "sources": ["news", "analysis"]
            },
            {
                "sentiment_score": 0.65,
                "confidence": 0.85,
                "reasoning": "EUR/USD technical and fundamental analysis shows upward trend",
                "sources": ["technical", "fundamental"]
            }
        ]
        
        # Mock the LLM client to return our test responses
        with patch.object(self.llm_client, 'generate_response') as mock_generate:
            mock_generate.side_effect = [
                LLMResponse(
                    content=json.dumps(response),
                    provider="openai",
                    model="gpt-4",
                    tokens_used=100,
                    response_time=1.0,
                    timestamp=datetime.now(timezone.utc).timestamp()
                )
                for response in mock_responses
            ]
            
            # Step 1: Generate prompts for different analysis types
            basic_prompt = self.prompt_engine.create_sentiment_prompt(
                self.text_data, 
                self.symbol, 
                template_name="sentiment_basic"
            )
            
            enhanced_prompt = self.prompt_engine.create_sentiment_prompt(
                self.text_data,
                self.symbol,
                template_name="sentiment_enhanced"
            )
            
            news_prompt = self.prompt_engine.create_sentiment_prompt(
                self.text_data,
                self.symbol,
                template_name="sentiment_news"
            )
            
            # Verify prompts contain expected elements
            assert self.symbol in basic_prompt
            assert "sentiment_score" in basic_prompt
            assert "confidence" in basic_prompt
            
            # Step 2: Get LLM responses
            basic_response = await self.llm_client.generate_response(basic_prompt)
            enhanced_response = await self.llm_client.generate_response(enhanced_prompt)
            news_response = await self.llm_client.generate_response(news_prompt)
            
            # Step 3: Parse responses into SentimentResult objects
            basic_result = self.response_parser.parse_sentiment_response(
                basic_response.content, 
                self.symbol,
                validate=True
            )
            
            enhanced_result = self.response_parser.parse_sentiment_response(
                enhanced_response.content,
                self.symbol,
                validate=True
            )
            
            news_result = self.response_parser.parse_sentiment_response(
                news_response.content,
                self.symbol,
                validate=True
            )
            
            # Verify individual results
            results = [basic_result, enhanced_result, news_result]
            for result in results:
                assert isinstance(result, SentimentResult)
                assert result.symbol == self.symbol
                assert -1.0 <= result.sentiment_score <= 1.0
                assert 0.0 <= result.confidence <= 1.0
                assert len(result.reasoning) > 10
                assert len(result.sources) > 0
            
            # Step 4: Aggregate multiple sentiment results
            aggregated = self.sentiment_aggregator.aggregate_sentiment(
                results,
                method="weighted_average"
            )
            
            # Verify aggregated result
            assert aggregated.symbol == self.symbol
            assert 0.6 <= aggregated.final_sentiment_score <= 0.7  # Should be positive
            assert 0.7 <= aggregated.final_confidence <= 0.9  # Should be high confidence
            assert aggregated.consistency_score > 0.8  # Should be consistent
            assert len(aggregated.individual_results) == 3
            assert "bullish" in aggregated.reasoning.lower()
            
            # Verify all calls were made
            assert mock_generate.call_count == 3
    
    @pytest.mark.asyncio
    async def test_error_handling_in_pipeline(self):
        """Test error handling throughout the pipeline"""
        
        # Test with malformed LLM response
        with patch.object(self.llm_client, 'generate_response') as mock_generate:
            mock_generate.return_value = LLMResponse(
                content="Invalid JSON response that cannot be parsed",
                provider="openai",
                model="gpt-4",
                tokens_used=50,
                response_time=1.0,
                timestamp=datetime.now(timezone.utc).timestamp()
            )
            
            # Generate prompt
            prompt = self.prompt_engine.create_sentiment_prompt(
                self.text_data,
                self.symbol
            )
            
            # Get response
            response = await self.llm_client.generate_response(prompt)
            
            # Parse response - should handle error gracefully
            result = self.response_parser.parse_sentiment_response(
                response.content,
                self.symbol,
                validate=False
            )
            
            # Should return fallback result
            assert isinstance(result, SentimentResult)
            assert result.symbol == self.symbol
            assert result.sentiment_score == 0.0  # Neutral fallback
            assert result.confidence <= 0.2  # Low confidence
    
    @pytest.mark.asyncio
    async def test_caching_integration(self):
        """Test sentiment caching integration"""
        
        mock_response = {
            "sentiment_score": 0.5,
            "confidence": 0.7,
            "reasoning": "Moderate bullish sentiment for EUR/USD",
            "sources": ["analysis"]
        }
        
        with patch.object(self.llm_client, 'generate_response') as mock_generate:
            mock_generate.return_value = LLMResponse(
                content=json.dumps(mock_response),
                provider="openai",
                model="gpt-4",
                tokens_used=100,
                response_time=1.0,
                timestamp=datetime.now(timezone.utc).timestamp()
            )
            
            # First analysis - should call LLM
            prompt = self.prompt_engine.create_sentiment_prompt(self.text_data, self.symbol)
            response = await self.llm_client.generate_response(prompt)
            result = self.response_parser.parse_sentiment_response(response.content, self.symbol)
            
            # Cache the result
            self.sentiment_aggregator.cache_sentiment(self.text_data, self.symbol, result)
            
            # Second analysis with same data - should use cache
            cached_result = self.sentiment_aggregator.get_cached_sentiment(self.text_data, self.symbol)
            
            assert cached_result is not None
            assert cached_result.symbol == result.symbol
            assert cached_result.sentiment_score == result.sentiment_score
            assert cached_result.confidence == result.confidence
            
            # Verify LLM was only called once
            assert mock_generate.call_count == 1
    
    def test_prompt_template_variations(self):
        """Test different prompt templates produce valid prompts"""
        
        templates = ["sentiment_basic", "sentiment_enhanced", "sentiment_news"]
        
        for template_name in templates:
            prompt = self.prompt_engine.create_sentiment_prompt(
                self.text_data,
                self.symbol,
                template_name=template_name
            )
            
            # Verify common elements
            assert self.symbol in prompt
            assert "sentiment_score" in prompt
            assert "confidence" in prompt
            assert "reasoning" in prompt
            
            # Verify template-specific elements
            if template_name == "sentiment_enhanced":
                assert "key_factors" in prompt
                assert "market_impact" in prompt
            elif template_name == "sentiment_news":
                assert "news_impact" in prompt
                assert "key_events" in prompt
    
    def test_response_parser_robustness(self):
        """Test response parser handles various response formats"""
        
        test_responses = [
            # Valid JSON
            '{"sentiment_score": 0.6, "confidence": 0.8, "reasoning": "EUR/USD analysis", "sources": ["news"]}',
            
            # JSON with markdown
            '```json\n{"sentiment_score": 0.5, "confidence": 0.7, "reasoning": "Test", "sources": ["test"]}\n```',
            
            # Partial JSON
            '{"sentiment_score": 0.4, "confidence": 0.6}',
            
            # Non-JSON text with extractable values
            'The sentiment score is 0.3 and confidence is 0.5. Reasoning: EUR/USD shows mixed signals.',
            
            # Completely invalid
            'This is not a valid response at all.'
        ]
        
        for response_content in test_responses:
            result = self.response_parser.parse_sentiment_response(
                response_content,
                self.symbol,
                validate=False
            )
            
            # Should always return a valid SentimentResult
            assert isinstance(result, SentimentResult)
            assert result.symbol == self.symbol
            assert -1.0 <= result.sentiment_score <= 1.0
            assert 0.0 <= result.confidence <= 1.0
            assert len(result.reasoning) > 0
            assert len(result.sources) > 0
    
    def test_aggregation_methods_comparison(self):
        """Test different aggregation methods produce reasonable results"""
        
        # Create test results with some variation
        results = [
            SentimentResult(
                symbol=self.symbol,
                sentiment_score=0.7,
                confidence=0.9,
                reasoning="Strong bullish signal",
                sources=["news"],
                timestamp=datetime.now(timezone.utc)
            ),
            SentimentResult(
                symbol=self.symbol,
                sentiment_score=0.5,
                confidence=0.6,
                reasoning="Moderate positive sentiment",
                sources=["social_media"],
                timestamp=datetime.now(timezone.utc)
            ),
            SentimentResult(
                symbol=self.symbol,
                sentiment_score=0.6,
                confidence=0.8,
                reasoning="Technical indicators positive",
                sources=["technical"],
                timestamp=datetime.now(timezone.utc)
            )
        ]
        
        methods = ["weighted_average", "confidence_weighted", "median", "consensus"]
        
        for method in methods:
            aggregated = self.sentiment_aggregator.aggregate_sentiment(results, method=method)
            
            # All methods should produce reasonable results
            assert 0.5 <= aggregated.final_sentiment_score <= 0.7
            assert 0.6 <= aggregated.final_confidence <= 0.9
            assert aggregated.consistency_score > 0.5
            assert aggregated.aggregation_method == method
            assert len(aggregated.individual_results) == 3
    
    def test_source_reliability_impact(self):
        """Test that source reliability affects aggregation"""
        
        # Create results with different source types
        high_reliability_result = SentimentResult(
            symbol=self.symbol,
            sentiment_score=0.8,
            confidence=0.9,
            reasoning="News analysis",
            sources=["news"],  # High reliability
            timestamp=datetime.now(timezone.utc)
        )
        
        low_reliability_result = SentimentResult(
            symbol=self.symbol,
            sentiment_score=0.2,
            confidence=0.9,
            reasoning="Social media analysis",
            sources=["social_media"],  # Lower reliability
            timestamp=datetime.now(timezone.utc)
        )
        
        # Aggregate with weighted average (considers source reliability)
        aggregated = self.sentiment_aggregator.aggregate_sentiment(
            [high_reliability_result, low_reliability_result],
            method="weighted_average"
        )
        
        # Result should be closer to high reliability source
        assert aggregated.final_sentiment_score > 0.5  # Closer to news result
        
        # Compare with simple average
        simple_average = (0.8 + 0.2) / 2  # 0.5
        assert aggregated.final_sentiment_score > simple_average
    
    def test_consistency_scoring_impact(self):
        """Test that consistency scoring affects final confidence"""
        
        # High consistency results
        consistent_results = [
            SentimentResult(
                symbol=self.symbol,
                sentiment_score=0.65,
                confidence=0.8,
                reasoning="Analysis 1",
                sources=["news"],
                timestamp=datetime.now(timezone.utc)
            ),
            SentimentResult(
                symbol=self.symbol,
                sentiment_score=0.67,
                confidence=0.8,
                reasoning="Analysis 2",
                sources=["technical"],
                timestamp=datetime.now(timezone.utc)
            )
        ]
        
        # Low consistency results
        inconsistent_results = [
            SentimentResult(
                symbol=self.symbol,
                sentiment_score=0.8,
                confidence=0.8,
                reasoning="Very bullish",
                sources=["news"],
                timestamp=datetime.now(timezone.utc)
            ),
            SentimentResult(
                symbol=self.symbol,
                sentiment_score=-0.6,
                confidence=0.8,
                reasoning="Bearish signal",
                sources=["technical"],
                timestamp=datetime.now(timezone.utc)
            )
        ]
        
        consistent_agg = self.sentiment_aggregator.aggregate_sentiment(consistent_results)
        inconsistent_agg = self.sentiment_aggregator.aggregate_sentiment(inconsistent_results)
        
        # Consistent results should have higher final confidence
        assert consistent_agg.consistency_score > inconsistent_agg.consistency_score
        assert consistent_agg.final_confidence > inconsistent_agg.final_confidence


if __name__ == "__main__":
    pytest.main([__file__])