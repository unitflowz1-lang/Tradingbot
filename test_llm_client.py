"""Unit tests for LLM client and API integration"""

import pytest
import asyncio
import json
from unittest.mock import Mock, patch, AsyncMock
from src.analysis.llm_client import (
    LLMClient, OpenAIProvider, AnthropicProvider, 
    LLMRequest, LLMResponse, RetryStrategy, LLMProvider
)
from src.config import LLMConfig
from src.exceptions import LLMAPIError


class TestRetryStrategy:
    """Test retry strategy implementation"""
    
    def test_get_delay_exponential_backoff(self):
        """Test exponential backoff delay calculation"""
        strategy = RetryStrategy(max_retries=3, base_delay=1.0, max_delay=60.0)
        
        assert strategy.get_delay(0) == 1.0
        assert strategy.get_delay(1) == 2.0
        assert strategy.get_delay(2) == 4.0
        assert strategy.get_delay(3) == 8.0
    
    def test_get_delay_max_limit(self):
        """Test delay is capped at max_delay"""
        strategy = RetryStrategy(max_retries=10, base_delay=1.0, max_delay=5.0)
        
        assert strategy.get_delay(10) == 5.0  # Should be capped at max_delay
    
    @pytest.mark.asyncio
    async def test_execute_with_retry_success(self):
        """Test successful execution without retry"""
        strategy = RetryStrategy(max_retries=3)
        
        async def success_func():
            return "success"
        
        result = await strategy.execute_with_retry(success_func)
        assert result == "success"
    
    @pytest.mark.asyncio
    async def test_execute_with_retry_eventual_success(self):
        """Test eventual success after retries"""
        strategy = RetryStrategy(max_retries=3, base_delay=0.01)  # Fast retry for testing
        call_count = 0
        
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Temporary failure")
            return "success"
        
        result = await strategy.execute_with_retry(flaky_func)
        assert result == "success"
        assert call_count == 3
    
    @pytest.mark.asyncio
    async def test_execute_with_retry_max_retries_exceeded(self):
        """Test failure after max retries"""
        strategy = RetryStrategy(max_retries=2, base_delay=0.01)
        
        async def always_fail():
            raise Exception("Always fails")
        
        with pytest.raises(Exception, match="Always fails"):
            await strategy.execute_with_retry(always_fail)


class TestOpenAIProvider:
    """Test OpenAI provider implementation"""
    
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
        self.provider = OpenAIProvider(self.config)
    
    def test_validate_config_valid(self):
        """Test valid configuration"""
        errors = self.provider.validate_config()
        assert errors == []
    
    def test_validate_config_missing_api_key(self):
        """Test validation with missing API key"""
        self.config.api_key = ""
        provider = OpenAIProvider(self.config)
        errors = provider.validate_config()
        assert "OpenAI API key is required" in errors
    
    def test_validate_config_invalid_model(self):
        """Test validation with invalid model"""
        self.config.model = "invalid-model"
        provider = OpenAIProvider(self.config)
        errors = provider.validate_config()
        assert any("Invalid OpenAI model" in error for error in errors)
    
    def test_validate_config_invalid_temperature(self):
        """Test validation with invalid temperature"""
        self.config.temperature = 3.0
        provider = OpenAIProvider(self.config)
        errors = provider.validate_config()
        assert any("temperature must be between" in error for error in errors)
    
    @pytest.mark.asyncio
    async def test_make_request_success(self):
        """Test successful API request"""
        request = LLMRequest(
            prompt="Test prompt",
            max_tokens=100,
            temperature=0.1,
            model="gpt-4",
            timeout=30
        )
        
        expected_response = LLMResponse(
            content="Test response",
            provider="openai",
            model="gpt-4",
            tokens_used=50,
            response_time=1.0,
            timestamp=1234567890.0
        )
        
        # Mock the retry strategy to avoid actual HTTP calls
        with patch.object(self.provider.retry_strategy, 'execute_with_retry') as mock_retry:
            mock_retry.return_value = expected_response
            
            response = await self.provider.make_request(request)
            
            assert response.content == "Test response"
            assert response.provider == "openai"
            assert response.model == "gpt-4"
            assert response.tokens_used == 50
            assert response.response_time > 0
    
    @pytest.mark.asyncio
    async def test_make_request_api_error(self):
        """Test API error handling"""
        request = LLMRequest(
            prompt="Test prompt",
            max_tokens=100,
            temperature=0.1,
            model="gpt-4",
            timeout=30
        )
        
        # Mock the retry strategy to raise an API error
        with patch.object(self.provider.retry_strategy, 'execute_with_retry') as mock_retry:
            mock_retry.side_effect = LLMAPIError(
                "OpenAI API error: 400 - Bad Request",
                error_code="OPENAI_API_ERROR",
                context={"status_code": 400, "response": "Bad Request", "model": "gpt-4"}
            )
            
            with pytest.raises(LLMAPIError, match="OpenAI API error"):
                await self.provider.make_request(request)
    
    @pytest.mark.asyncio
    async def test_make_request_no_choices(self):
        """Test handling of response with no choices"""
        request = LLMRequest(
            prompt="Test prompt",
            max_tokens=100,
            temperature=0.1,
            model="gpt-4",
            timeout=30
        )
        
        # Mock the retry strategy to raise a no choices error
        with patch.object(self.provider.retry_strategy, 'execute_with_retry') as mock_retry:
            mock_retry.side_effect = LLMAPIError(
                "No choices in OpenAI response",
                error_code="NO_CHOICES",
                context={"response": {"choices": []}}
            )
            
            with pytest.raises(LLMAPIError, match="No choices in OpenAI response"):
                await self.provider.make_request(request)


class TestAnthropicProvider:
    """Test Anthropic provider implementation"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.config = LLMConfig(
            provider="anthropic",
            model="claude-3-sonnet-20240229",
            api_key="test-key",
            max_tokens=1000,
            temperature=0.1,
            timeout=30
        )
        self.provider = AnthropicProvider(self.config)
    
    def test_validate_config_valid(self):
        """Test valid configuration"""
        errors = self.provider.validate_config()
        assert errors == []
    
    def test_validate_config_missing_api_key(self):
        """Test validation with missing API key"""
        self.config.api_key = ""
        provider = AnthropicProvider(self.config)
        errors = provider.validate_config()
        assert "Anthropic API key is required" in errors
    
    @pytest.mark.asyncio
    async def test_make_request_success(self):
        """Test successful API request"""
        request = LLMRequest(
            prompt="Test prompt",
            max_tokens=100,
            temperature=0.1,
            model="claude-3-sonnet-20240229",
            timeout=30
        )
        
        expected_response = LLMResponse(
            content="Test response",
            provider="anthropic",
            model="claude-3-sonnet-20240229",
            tokens_used=50,
            response_time=1.0,
            timestamp=1234567890.0
        )
        
        # Mock the retry strategy to avoid actual HTTP calls
        with patch.object(self.provider.retry_strategy, 'execute_with_retry') as mock_retry:
            mock_retry.return_value = expected_response
            
            response = await self.provider.make_request(request)
            
            assert response.content == "Test response"
            assert response.provider == "anthropic"
            assert response.model == "claude-3-sonnet-20240229"
            assert response.tokens_used == 50


class TestLLMClient:
    """Test main LLM client"""
    
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
    
    def test_create_openai_provider(self):
        """Test OpenAI provider creation"""
        client = LLMClient(self.config)
        assert isinstance(client.provider, OpenAIProvider)
    
    def test_create_anthropic_provider(self):
        """Test Anthropic provider creation"""
        self.config.provider = "anthropic"
        self.config.model = "claude-3-sonnet-20240229"
        client = LLMClient(self.config)
        assert isinstance(client.provider, AnthropicProvider)
    
    def test_unsupported_provider(self):
        """Test unsupported provider error"""
        self.config.provider = "unsupported"
        with pytest.raises(LLMAPIError, match="Unsupported LLM provider"):
            LLMClient(self.config)
    
    def test_invalid_configuration(self):
        """Test invalid configuration error"""
        self.config.api_key = ""
        with pytest.raises(LLMAPIError, match="Invalid LLM configuration"):
            LLMClient(self.config)
    
    @pytest.mark.asyncio
    async def test_generate_response_success(self):
        """Test successful response generation"""
        client = LLMClient(self.config)
        
        mock_response = LLMResponse(
            content="Test response",
            provider="openai",
            model="gpt-4",
            tokens_used=50,
            response_time=1.0,
            timestamp=1234567890.0
        )
        
        with patch.object(client.provider, 'make_request', return_value=mock_response):
            response = await client.generate_response("Test prompt")
            assert response.content == "Test response"
    
    @pytest.mark.asyncio
    async def test_generate_response_empty_prompt(self):
        """Test empty prompt error"""
        client = LLMClient(self.config)
        
        with pytest.raises(LLMAPIError, match="Prompt cannot be empty"):
            await client.generate_response("")
    
    @pytest.mark.asyncio
    async def test_analyze_sentiment(self):
        """Test sentiment analysis method"""
        client = LLMClient(self.config)
        
        mock_response = LLMResponse(
            content='{"sentiment_score": 0.5, "confidence": 0.8}',
            provider="openai",
            model="gpt-4",
            tokens_used=50,
            response_time=1.0,
            timestamp=1234567890.0
        )
        
        with patch.object(client.provider, 'make_request', return_value=mock_response):
            response = await client.analyze_sentiment("Test sentiment prompt")
            assert response.content == '{"sentiment_score": 0.5, "confidence": 0.8}'
    
    def test_get_provider_info(self):
        """Test provider info retrieval"""
        client = LLMClient(self.config)
        info = client.get_provider_info()
        
        assert info["provider"] == "openai"
        assert info["model"] == "gpt-4"
        assert info["max_tokens"] == 1000
        assert info["temperature"] == 0.1
        assert info["timeout"] == 30
    
    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        """Test healthy health check"""
        client = LLMClient(self.config)
        
        mock_response = LLMResponse(
            content="OK",
            provider="openai",
            model="gpt-4",
            tokens_used=5,
            response_time=0.5,
            timestamp=1234567890.0
        )
        
        with patch.object(client.provider, 'make_request', return_value=mock_response):
            health = await client.health_check()
            assert health["status"] == "healthy"
            assert health["provider"] == "openai"
            assert health["response_time"] == 0.5
    
    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self):
        """Test unhealthy health check"""
        client = LLMClient(self.config)
        
        with patch.object(client.provider, 'make_request', side_effect=Exception("API Error")):
            health = await client.health_check()
            assert health["status"] == "unhealthy"
            assert health["provider"] == "openai"
            assert "API Error" in health["error"]


if __name__ == "__main__":
    pytest.main([__file__])