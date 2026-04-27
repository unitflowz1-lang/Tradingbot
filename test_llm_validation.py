"""Test script for LLM validation functionality"""

import sys
import os
import json

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.llm_validation import LLMResponseValidator, LLMPromptValidator
from src.exceptions import LLMAPIError, DataValidationError


def test_llm_response_validation():
    """Test LLM response validation"""
    print("Testing LLM response validation...")
    
    validator = LLMResponseValidator()
    
    # Test valid response
    valid_response = {
        "sentiment_score": 0.75,
        "confidence": 0.85,
        "reasoning": "EUR/USD shows strong bullish momentum due to positive ECB policy outlook and strong eurozone economic data",
        "sources": ["Reuters", "Bloomberg"]
    }
    
    result = validator.validate_sentiment_response(valid_response, "EUR/USD")
    print(f"✓ Valid response validation: {result['is_valid']}")
    
    # Test JSON string response
    json_response = json.dumps(valid_response)
    result = validator.validate_sentiment_response(json_response, "EUR/USD")
    print(f"✓ JSON string response validation: {result['is_valid']}")
    
    # Test response with markdown
    markdown_response = f"```json\n{json_response}\n```"
    result = validator.validate_sentiment_response(markdown_response, "EUR/USD")
    print(f"✓ Markdown response validation: {result['is_valid']}")
    
    # Test invalid sentiment score
    invalid_response = valid_response.copy()
    invalid_response["sentiment_score"] = 1.5  # Out of range
    result = validator.validate_sentiment_response(invalid_response, "EUR/USD")
    print(f"✓ Invalid sentiment score caught: {not result['is_valid']}")
    
    # Test missing fields
    incomplete_response = {"sentiment_score": 0.5}
    result = validator.validate_sentiment_response(incomplete_response, "EUR/USD")
    print(f"✓ Missing fields caught: {not result['is_valid']}")
    
    # Test hallucination detection
    hallucination_response = valid_response.copy()
    hallucination_response["reasoning"] = "As an AI, I cannot provide specific trading advice for EUR/USD"
    result = validator.validate_sentiment_response(hallucination_response, "EUR/USD")
    print(f"✓ Hallucination detected: {not result['is_valid']}")
    
    # Test contradictory sentiment
    contradictory_response = valid_response.copy()
    contradictory_response["sentiment_score"] = 0.8  # Positive
    contradictory_response["reasoning"] = "EUR/USD is bearish and declining due to negative economic outlook"
    result = validator.validate_sentiment_response(contradictory_response, "EUR/USD")
    print(f"✓ Contradictory sentiment caught: {not result['is_valid']}")
    
    # Test irrelevant reasoning
    irrelevant_response = valid_response.copy()
    irrelevant_response["reasoning"] = "The weather is nice today and stocks are performing well"
    result = validator.validate_sentiment_response(irrelevant_response, "EUR/USD")
    print(f"✓ Irrelevant reasoning caught: {not result['is_valid']}")


def test_llm_prompt_validation():
    """Test LLM prompt validation"""
    print("\nTesting LLM prompt validation...")
    
    validator = LLMPromptValidator()
    
    # Test valid prompt data
    valid_text_data = [
        "EUR/USD rises on positive ECB policy outlook",
        "European Central Bank signals dovish stance, EUR strengthens",
        "USD weakens against EUR amid Fed uncertainty"
    ]
    
    validation = validator.validate_sentiment_prompt(valid_text_data, "EUR/USD")
    print(f"✓ Valid prompt data: {validation['is_valid']}")
    
    # Test invalid symbol
    validation = validator.validate_sentiment_prompt(valid_text_data, "INVALID")
    print(f"✓ Invalid symbol caught: {not validation['is_valid']}")
    
    # Test empty text data
    validation = validator.validate_sentiment_prompt([], "EUR/USD")
    print(f"✓ Empty text data caught: {not validation['is_valid']}")
    
    # Test irrelevant text data
    irrelevant_data = [
        "The weather is nice today",
        "Stock market is performing well",
        "Technology sector shows growth"
    ]
    validation = validator.validate_sentiment_prompt(irrelevant_data, "EUR/USD")
    print(f"✓ Irrelevant text warning: {len(validation['warnings']) > 0}")
    
    # Test prompt creation
    try:
        prompt = validator.create_sentiment_prompt(valid_text_data, "EUR/USD")
        print(f"✓ Prompt created successfully (length: {len(prompt)})")
        
        # Check if prompt contains required elements
        required_elements = ["EUR/USD", "sentiment_score", "confidence", "reasoning", "sources"]
        all_present = all(element in prompt for element in required_elements)
        print(f"✓ Prompt contains all required elements: {all_present}")
        
    except Exception as e:
        print(f"❌ Prompt creation failed: {str(e)}")


def test_edge_cases():
    """Test edge cases and error handling"""
    print("\nTesting edge cases...")
    
    validator = LLMResponseValidator()
    
    # Test malformed JSON
    malformed_json = '{"sentiment_score": 0.5, "confidence": 0.8'  # Missing closing brace
    result = validator.validate_sentiment_response(malformed_json, "EUR/USD")
    print(f"✓ Malformed JSON handled: {not result['is_valid']}")
    
    # Test non-JSON string
    non_json = "This is not JSON at all"
    result = validator.validate_sentiment_response(non_json, "EUR/USD")
    print(f"✓ Non-JSON string handled: {not result['is_valid']}")
    
    # Test None response
    result = validator.validate_sentiment_response(None, "EUR/USD")
    print(f"✓ None response handled: {not result['is_valid']}")
    
    # Test extremely long reasoning
    long_response = {
        "sentiment_score": 0.5,
        "confidence": 0.8,
        "reasoning": "EUR/USD " + "very " * 500 + "long reasoning",  # Very long
        "sources": ["test"]
    }
    result = validator.validate_sentiment_response(long_response, "EUR/USD")
    print(f"✓ Long reasoning handled: {not result['is_valid']}")
    
    # Test numeric strings
    string_numbers = {
        "sentiment_score": "0.75",  # String instead of number
        "confidence": "0.85",
        "reasoning": "EUR/USD shows bullish momentum",
        "sources": ["test"]
    }
    result = validator.validate_sentiment_response(string_numbers, "EUR/USD")
    print(f"✓ String numbers converted: {result['is_valid']}")


def test_real_world_scenarios():
    """Test real-world-like scenarios"""
    print("\nTesting real-world scenarios...")
    
    validator = LLMResponseValidator()
    
    # Test typical ChatGPT response format
    chatgpt_response = """```json
{
    "sentiment_score": 0.6,
    "confidence": 0.75,
    "reasoning": "EUR/USD pair shows moderate bullish sentiment based on recent ECB policy statements and improving eurozone economic indicators. However, uncertainty around US Fed policy creates some headwinds.",
    "sources": ["central_bank_statements", "economic_indicators", "news_analysis"]
}
```"""
    
    result = validator.validate_sentiment_response(chatgpt_response, "EUR/USD")
    print(f"✓ ChatGPT-style response: {result['is_valid']}")
    
    # Test response with extra fields
    extended_response = {
        "sentiment_score": 0.4,
        "confidence": 0.7,
        "reasoning": "EUR/USD faces headwinds from diverging monetary policies",
        "sources": ["Reuters"],
        "extra_field": "This should be ignored",
        "timestamp": "2024-01-01"
    }
    
    result = validator.validate_sentiment_response(extended_response, "EUR/USD")
    print(f"✓ Response with extra fields: {result['is_valid']}")
    
    # Test minimal valid response
    minimal_response = {
        "sentiment_score": 0.0,
        "confidence": 0.5,
        "reasoning": "EUR/USD neutral outlook",
        "sources": []
    }
    
    result = validator.validate_sentiment_response(minimal_response, "EUR/USD")
    print(f"✓ Minimal valid response: {result['is_valid']}")


def main():
    """Run all LLM validation tests"""
    print("=== AI Forex Trading Bot - LLM Validation Test ===\n")
    
    try:
        test_llm_response_validation()
        test_llm_prompt_validation()
        test_edge_cases()
        test_real_world_scenarios()
        
        print("\n=== All LLM validation tests completed successfully! ===")
        
    except Exception as e:
        print(f"\n❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()