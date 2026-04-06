"""Unit tests for ResponseParser"""

import pytest
import json
from datetime import datetime
from src.analysis.response_parser import ResponseParser
from src.models import SentimentResult
from src.exceptions import DataValidationError


class TestResponseParser:
    """Test ResponseParser functionality"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.parser = ResponseParser()
        self.valid_symbol = "EUR/USD"
        self.valid_json_response = json.dumps({
            "sentiment_score": 0.7,
            "confidence": 0.8,
            "reasoning": "EUR/USD shows strong bullish momentum due to ECB policy changes",
            "sources": ["news", "social_media"]
        })
    
    def test_parse_valid_json_response(self):
        """Test parsing valid JSON response"""
        result = self.parser.parse_sentiment_response(
            self.valid_json_response,
            self.valid_symbol,
            validate=False
        )
        
        assert isinstance(result, SentimentResult)
        assert result.symbol == self.valid_symbol
        assert result.sentiment_score == 0.7
        assert result.confidence == 0.8
        assert "EUR/USD" in result.reasoning
        assert result.sources == ["news", "social_media"]
        assert isinstance(result.timestamp, datetime)
    
    def test_parse_json_with_markdown(self):
        """Test parsing JSON wrapped in markdown"""
        markdown_response = f"```json\n{self.valid_json_response}\n```"
        
        result = self.parser.parse_sentiment_response(
            markdown_response,
            self.valid_symbol,
            validate=False
        )
        
        assert result.sentiment_score == 0.7
        assert result.confidence == 0.8
    
    def test_parse_malformed_json(self):
        """Test parsing malformed JSON"""
        malformed_json = '{"sentiment_score": 0.5, "confidence": 0.6, "reasoning": "Test'  # Missing closing
        
        result = self.parser.parse_sentiment_response(
            malformed_json,
            self.valid_symbol,
            validate=False
        )
        
        # Should return fallback result or extract what it can
        assert result.sentiment_score == 0.0 or result.sentiment_score == 0.5  # Might extract partial data
        assert result.confidence <= 0.6  # Should have low confidence
        assert result.sources in [["Error"], ["LLM Analysis"]]
    
    def test_parse_non_json_text(self):
        """Test parsing non-JSON text with extractable values"""
        text_response = """
        The sentiment score for EUR/USD is 0.6 based on recent analysis.
        My confidence in this assessment is 0.75.
        The reasoning is "EUR/USD showing positive momentum due to ECB policy".
        """
        
        result = self.parser.parse_sentiment_response(
            text_response,
            self.valid_symbol,
            validate=False
        )
        
        # Should extract values or provide reasonable defaults
        assert result.sentiment_score >= 0.0  # Should extract or default
        assert result.confidence > 0.0  # Should have some confidence
        assert "EUR/USD" in result.reasoning
    
    def test_extract_sentiment_score(self):
        """Test sentiment score extraction and validation"""
        # Valid score
        data = {"sentiment_score": 0.5}
        score = self.parser._extract_sentiment_score(data)
        assert score == 0.5
        
        # Out of range (should be clamped)
        data = {"sentiment_score": 2.0}
        score = self.parser._extract_sentiment_score(data)
        assert score == 1.0
        
        data = {"sentiment_score": -2.0}
        score = self.parser._extract_sentiment_score(data)
        assert score == -1.0
        
        # Invalid type
        data = {"sentiment_score": "invalid"}
        score = self.parser._extract_sentiment_score(data)
        assert score == 0.0
        
        # Missing
        data = {}
        score = self.parser._extract_sentiment_score(data)
        assert score == 0.0
    
    def test_extract_confidence(self):
        """Test confidence extraction and validation"""
        # Valid confidence
        data = {"confidence": 0.8}
        confidence = self.parser._extract_confidence(data, "test text")
        assert confidence == 0.8
        
        # Out of range (should be clamped)
        data = {"confidence": 1.5}
        confidence = self.parser._extract_confidence(data, "test text")
        assert confidence == 1.0
        
        # Invalid type - should infer from text
        data = {"confidence": "high"}
        text_with_high_confidence = "This is a strong and clear signal"
        confidence = self.parser._extract_confidence(data, text_with_high_confidence)
        assert confidence > 0.5
    
    def test_infer_confidence_from_text(self):
        """Test confidence inference from text"""
        # High confidence text
        high_conf_text = "This is a strong and clear signal with definite bullish momentum"
        confidence = self.parser._infer_confidence_from_text(high_conf_text)
        assert confidence >= 0.7
        
        # Low confidence text
        low_conf_text = "This is uncertain and unclear with mixed signals"
        confidence = self.parser._infer_confidence_from_text(low_conf_text)
        assert confidence <= 0.4
        
        # Medium confidence text
        medium_conf_text = "This likely indicates a probable upward trend"
        confidence = self.parser._infer_confidence_from_text(medium_conf_text)
        assert 0.4 < confidence < 0.7
    
    def test_extract_reasoning(self):
        """Test reasoning extraction and validation"""
        # Valid reasoning
        data = {"reasoning": "EUR/USD shows bullish momentum"}
        reasoning = self.parser._extract_reasoning(data, self.valid_symbol)
        assert reasoning == "EUR/USD shows bullish momentum"
        
        # Too short reasoning
        data = {"reasoning": "Short"}
        reasoning = self.parser._extract_reasoning(data, self.valid_symbol)
        assert len(reasoning) >= 10
        assert self.valid_symbol in reasoning
        
        # Too long reasoning
        long_text = "Very long reasoning " * 100
        data = {"reasoning": long_text}
        reasoning = self.parser._extract_reasoning(data, self.valid_symbol)
        assert len(reasoning) <= 1030  # Allow for "Analysis for EUR/USD: " prefix
        assert reasoning.endswith("...") or "Analysis for EUR/USD:" in reasoning
        
        # Missing symbol mention
        data = {"reasoning": "This is a good analysis without symbol"}
        reasoning = self.parser._extract_reasoning(data, self.valid_symbol)
        assert self.valid_symbol in reasoning
    
    def test_extract_sources(self):
        """Test sources extraction and validation"""
        # Valid sources list
        data = {"sources": ["news", "social_media"]}
        sources = self.parser._extract_sources(data)
        assert sources == ["news", "social_media"]
        
        # String source (should convert to list)
        data = {"sources": "news"}
        sources = self.parser._extract_sources(data)
        assert sources == ["news"]
        
        # Invalid sources (should use default)
        data = {"sources": [""]}
        sources = self.parser._extract_sources(data)
        assert sources == ["LLM Analysis"]
        
        # Missing sources
        data = {}
        sources = self.parser._extract_sources(data)
        assert sources == ["LLM Analysis"]
    
    def test_detect_hallucinations(self):
        """Test hallucination detection"""
        # Text with hallucination indicators
        hallucination_text = "As an AI, I cannot provide specific trading advice"
        assert self.parser._detect_hallucinations(hallucination_text) == True
        
        # Normal text
        normal_text = "EUR/USD shows strong bullish momentum based on ECB policy"
        assert self.parser._detect_hallucinations(normal_text) == False
        
        # Text with apology
        apology_text = "I'm sorry, but I don't have access to real-time data"
        assert self.parser._detect_hallucinations(apology_text) == True
    
    def test_hallucination_confidence_reduction(self):
        """Test confidence reduction when hallucinations detected"""
        hallucination_response = json.dumps({
            "sentiment_score": 0.7,
            "confidence": 0.9,
            "reasoning": "As an AI, I cannot provide specific advice, but EUR/USD looks good",
            "sources": ["analysis"]
        })
        
        result = self.parser.parse_sentiment_response(
            hallucination_response,
            self.valid_symbol,
            validate=False
        )
        
        # Confidence should be reduced due to hallucination
        assert result.confidence <= 0.3
    
    def test_clean_response_content(self):
        """Test response content cleaning"""
        # Markdown with JSON
        markdown_content = "```json\n{\"test\": \"value\"}\n```"
        cleaned = self.parser._clean_response_content(markdown_content)
        assert cleaned == '{"test": "value"}'
        
        # Extra whitespace
        whitespace_content = "  \n  {\"test\": \"value\"}  \n  "
        cleaned = self.parser._clean_response_content(whitespace_content)
        assert cleaned == '{"test": "value"}'
        
        # Invalid type
        with pytest.raises(DataValidationError, match="Response content must be a string"):
            self.parser._clean_response_content(123)
        
        # Empty content
        with pytest.raises(DataValidationError, match="Response content is empty"):
            self.parser._clean_response_content("   ")
    
    def test_extract_json_data(self):
        """Test JSON data extraction"""
        # Valid JSON
        json_str = '{"sentiment_score": 0.5}'
        data = self.parser._extract_json_data(json_str)
        assert data == {"sentiment_score": 0.5}
        
        # JSON within text
        text_with_json = 'Here is the analysis: {"sentiment_score": 0.5} and more text'
        data = self.parser._extract_json_data(text_with_json)
        assert "sentiment_score" in data
        
        # No valid JSON (should extract key-value pairs)
        non_json_text = "sentiment_score: 0.5, confidence: 0.8"
        data = self.parser._extract_json_data(non_json_text)
        assert "sentiment_score" in data
        assert "confidence" in data
    
    def test_extract_key_value_pairs(self):
        """Test key-value pair extraction from non-JSON text"""
        text = """
        sentiment_score: 0.6
        confidence: 0.75
        reasoning: "EUR/USD shows positive momentum"
        """
        
        data = self.parser._extract_key_value_pairs(text)
        
        assert data["sentiment_score"] == 0.6
        assert data["confidence"] == 0.75
        assert "EUR/USD" in data["reasoning"]
        assert data["sources"] == ["LLM Analysis"]
    
    def test_validate_response_format(self):
        """Test response format validation"""
        # Valid response
        validation = self.parser.validate_response_format(self.valid_json_response)
        assert validation["is_valid"] == True
        assert len(validation["errors"]) == 0
        assert "sentiment_score" in validation["extracted_fields"]
        
        # Invalid response
        invalid_response = '{"invalid": "data"}'
        validation = self.parser.validate_response_format(invalid_response)
        assert validation["is_valid"] == False
        assert len(validation["errors"]) > 0
    
    def test_extract_additional_fields(self):
        """Test extraction of additional fields"""
        enhanced_response = json.dumps({
            "sentiment_score": 0.7,
            "confidence": 0.8,
            "reasoning": "EUR/USD analysis",
            "sources": ["news"],
            "key_factors": ["ECB policy", "USD strength"],
            "market_impact": "Short-term bullish"
        })
        
        additional = self.parser.extract_additional_fields(enhanced_response)
        
        assert "key_factors" in additional
        assert "market_impact" in additional
        assert additional["key_factors"] == ["ECB policy", "USD strength"]
        assert additional["market_impact"] == "Short-term bullish"
    
    def test_create_fallback_result(self):
        """Test fallback result creation"""
        error_msg = "Test error"
        result = self.parser._create_fallback_result(self.valid_symbol, error_msg)
        
        assert isinstance(result, SentimentResult)
        assert result.symbol == self.valid_symbol
        assert result.sentiment_score == 0.0
        assert result.confidence == 0.1
        assert error_msg in result.reasoning
        assert result.sources == ["Error"]
    
    def test_parse_with_validation(self):
        """Test parsing with validation enabled"""
        result = self.parser.parse_sentiment_response(
            self.valid_json_response,
            self.valid_symbol,
            validate=True
        )
        
        # Should still work with validation
        assert isinstance(result, SentimentResult)
        assert result.symbol == self.valid_symbol
    
    def test_edge_cases(self):
        """Test various edge cases"""
        # Empty JSON object
        empty_json = "{}"
        result = self.parser.parse_sentiment_response(empty_json, self.valid_symbol, validate=False)
        assert result.sentiment_score == 0.0
        assert result.confidence >= 0.0
        
        # JSON with null values
        null_json = '{"sentiment_score": null, "confidence": null, "reasoning": null}'
        result = self.parser.parse_sentiment_response(null_json, self.valid_symbol, validate=False)
        assert result.sentiment_score == 0.0
        
        # Very large numbers
        large_numbers_json = '{"sentiment_score": 999, "confidence": 999}'
        result = self.parser.parse_sentiment_response(large_numbers_json, self.valid_symbol, validate=False)
        assert -1.0 <= result.sentiment_score <= 1.0
        assert 0.0 <= result.confidence <= 1.0


if __name__ == "__main__":
    pytest.main([__file__])