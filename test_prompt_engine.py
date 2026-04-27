"""Unit tests for PromptEngine"""

import pytest
from datetime import datetime
from src.analysis.prompt_engine import PromptEngine, PromptTemplate
from src.exceptions import DataValidationError


class TestPromptEngine:
    """Test PromptEngine functionality"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.engine = PromptEngine()
        self.valid_symbol = "EUR/USD"
        self.valid_text_data = [
            "EUR/USD is showing strong bullish momentum today.",
            "European Central Bank hints at rate hikes.",
            "USD weakening against major currencies."
        ]
    
    def test_init(self):
        """Test PromptEngine initialization"""
        assert len(self.engine.templates) > 0
        assert "sentiment_basic" in self.engine.templates
        assert "sentiment_enhanced" in self.engine.templates
        assert "sentiment_news" in self.engine.templates
    
    def test_create_sentiment_prompt_basic(self):
        """Test basic sentiment prompt creation"""
        prompt = self.engine.create_sentiment_prompt(
            self.valid_text_data, 
            self.valid_symbol
        )
        
        assert self.valid_symbol in prompt
        assert "EUR/USD" in prompt
        assert "sentiment_score" in prompt
        assert "confidence" in prompt
        assert "reasoning" in prompt
        assert "sources" in prompt
        assert all(text in prompt for text in self.valid_text_data)
    
    def test_create_sentiment_prompt_enhanced(self):
        """Test enhanced sentiment prompt creation"""
        prompt = self.engine.create_sentiment_prompt(
            self.valid_text_data,
            self.valid_symbol,
            template_name="sentiment_enhanced"
        )
        
        assert self.valid_symbol in prompt
        assert "EUR" in prompt  # base currency
        assert "USD" in prompt  # quote currency
        assert "Market Session" in prompt
        assert "key_factors" in prompt
        assert "market_impact" in prompt
    
    def test_create_sentiment_prompt_news(self):
        """Test news-focused sentiment prompt creation"""
        news_data = [
            "ECB raises interest rates by 0.25%",
            "US inflation data shows cooling trend",
            "EUR/USD reaches new monthly high"
        ]
        
        prompt = self.engine.create_sentiment_prompt(
            news_data,
            self.valid_symbol,
            template_name="sentiment_news"
        )
        
        assert self.valid_symbol in prompt
        assert "news_impact" in prompt
        assert "key_events" in prompt
        assert "Central bank" in prompt
    
    def test_invalid_symbol(self):
        """Test invalid symbol handling"""
        with pytest.raises(DataValidationError, match="Invalid forex symbol"):
            self.engine.create_sentiment_prompt(
                self.valid_text_data,
                "INVALID"
            )
    
    def test_empty_text_data(self):
        """Test empty text data handling"""
        with pytest.raises(DataValidationError, match="Text data must be a non-empty list"):
            self.engine.create_sentiment_prompt(
                [],
                self.valid_symbol
            )
    
    def test_invalid_text_data_type(self):
        """Test invalid text data type"""
        with pytest.raises(DataValidationError, match="Text data must be a non-empty list"):
            self.engine.create_sentiment_prompt(
                "not a list",
                self.valid_symbol
            )
    
    def test_unknown_template(self):
        """Test unknown template handling"""
        with pytest.raises(DataValidationError, match="Unknown template"):
            self.engine.create_sentiment_prompt(
                self.valid_text_data,
                self.valid_symbol,
                template_name="unknown_template"
            )
    
    def test_text_too_short(self):
        """Test handling of text that's too short"""
        short_texts = ["Hi", "OK", "Yes"]
        
        with pytest.raises(DataValidationError, match="No valid text items found"):
            self.engine.create_sentiment_prompt(
                short_texts,
                self.valid_symbol
            )
    
    def test_text_length_optimization(self):
        """Test text length optimization"""
        # Create moderately long text data that will fit within limits
        long_texts = ["This is a moderately long text about EUR/USD trading patterns and analysis. " * 10] * 5
        
        prompt = self.engine.create_sentiment_prompt(
            long_texts,
            self.valid_symbol
        )
        
        # Should not exceed reasonable length
        assert len(prompt) < 6000  # Template + processed text should be reasonable
    
    def test_process_text_data(self):
        """Test text data processing"""
        mixed_texts = [
            "Valid long text about EUR/USD trading today",
            "",  # Empty
            "Hi",  # Too short
            "Another valid text about European Central Bank policy",
            None,  # Invalid type
            123,  # Invalid type
            "Final valid text about USD strength"
        ]
        
        processed = self.engine._process_text_data(mixed_texts, self.valid_symbol)
        
        # Should only include valid texts
        assert "Valid long text" in processed
        assert "Another valid text" in processed
        assert "Final valid text" in processed
        assert "Hi" not in processed
    
    def test_prepare_template_variables(self):
        """Test template variable preparation"""
        text_data = "Test text about EUR/USD"
        variables = self.engine._prepare_template_variables(
            self.valid_symbol, 
            text_data,
            custom_var="custom_value"
        )
        
        assert variables["symbol"] == "EUR/USD"
        assert variables["base_currency"] == "EUR"
        assert variables["quote_currency"] == "USD"
        assert variables["text_data"] == text_data
        assert "timestamp" in variables
        assert "market_session" in variables
        assert variables["custom_var"] == "custom_value"
    
    def test_get_market_session(self):
        """Test market session detection"""
        session = self.engine._get_market_session()
        valid_sessions = ["Asian Session", "European Session", "American Session", "Off-Hours"]
        assert session in valid_sessions
    
    def test_get_available_templates(self):
        """Test getting available templates"""
        templates = self.engine.get_available_templates()
        
        assert len(templates) >= 3
        assert all("name" in template for template in templates)
        assert all("description" in template for template in templates)
        assert all("required_variables" in template for template in templates)
    
    def test_validate_template_variables(self):
        """Test template variable validation"""
        # Valid variables
        valid_vars = {
            "symbol": "EUR/USD",
            "timestamp": "2023-01-01",
            "text_data": "test data"
        }
        errors = self.engine.validate_template_variables("sentiment_basic", valid_vars)
        assert errors == []
        
        # Missing variables
        incomplete_vars = {"symbol": "EUR/USD"}
        errors = self.engine.validate_template_variables("sentiment_basic", incomplete_vars)
        assert len(errors) > 0
        assert "Missing required variables" in errors[0]
        
        # Unknown template
        errors = self.engine.validate_template_variables("unknown", valid_vars)
        assert len(errors) > 0
        assert "Unknown template" in errors[0]
    
    def test_estimate_token_count(self):
        """Test token count estimation"""
        short_prompt = "Short prompt"
        long_prompt = "This is a much longer prompt " * 50
        
        short_tokens = self.engine.estimate_token_count(short_prompt)
        long_tokens = self.engine.estimate_token_count(long_prompt)
        
        assert short_tokens < long_tokens
        assert short_tokens > 0
        assert long_tokens > 0
    
    def test_optimize_prompt_length(self):
        """Test prompt length optimization"""
        long_texts = [
            "This is a very long text about EUR/USD trading patterns and market analysis. " * 20,
            "Another long text about European Central Bank monetary policy decisions. " * 20,
            "Third long text about USD strength and Federal Reserve actions. " * 20
        ]
        
        optimized = self.engine.optimize_prompt_length(long_texts, self.valid_symbol, max_tokens=1000)
        
        # Should return fewer or truncated texts
        total_length = sum(len(text) for text in optimized)
        assert total_length < sum(len(text) for text in long_texts)
        assert len(optimized) <= len(long_texts)
    
    def test_template_formatting_with_kwargs(self):
        """Test template formatting with additional kwargs"""
        prompt = self.engine.create_sentiment_prompt(
            self.valid_text_data,
            self.valid_symbol,
            template_name="sentiment_enhanced",
            custom_field="custom_value"
        )
        
        # Should not raise error even with extra kwargs
        assert self.valid_symbol in prompt
    
    def test_missing_template_variables(self):
        """Test handling of missing template variables"""
        # Create a custom template that requires a variable we don't provide
        custom_template = PromptTemplate(
            name="test_template",
            template="Test {symbol} with {missing_var}",
            required_variables=["symbol", "missing_var"],
            description="Test template"
        )
        
        self.engine.templates["test_template"] = custom_template
        
        with pytest.raises(DataValidationError, match="Missing required template variables"):
            self.engine.create_sentiment_prompt(
                self.valid_text_data,
                self.valid_symbol,
                template_name="test_template"
            )


if __name__ == "__main__":
    pytest.main([__file__])