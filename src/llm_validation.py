"""LLM response validation utilities for the AI Forex Trading Bot"""

import json
import re
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from src.exceptions import LLMAPIError, DataValidationError
from src.validation import ValidationRules


class LLMResponseValidator:
    """Validator for LLM API responses to handle hallucinations and invalid outputs"""
    
    def __init__(self):
        self.required_sentiment_fields = {
            'sentiment_score', 'confidence', 'reasoning', 'sources'
        }
        self.sentiment_score_range = (-1.0, 1.0)
        self.confidence_range = (0.0, 1.0)
    
    def validate_sentiment_response(self, response: Union[str, Dict[str, Any]], symbol: str) -> Dict[str, Any]:
        """Validate and parse LLM sentiment analysis response"""
        try:
            # Parse JSON if response is string
            if isinstance(response, str):
                parsed_response = self._parse_json_response(response)
            else:
                parsed_response = response
            
            # Validate required fields
            self._validate_required_fields(parsed_response, self.required_sentiment_fields)
            
            # Validate sentiment score
            sentiment_score = parsed_response['sentiment_score']
            self._validate_numeric_range(
                sentiment_score, 
                self.sentiment_score_range, 
                "sentiment_score"
            )
            
            # Validate confidence
            confidence = parsed_response['confidence']
            self._validate_numeric_range(
                confidence, 
                self.confidence_range, 
                "confidence"
            )
            
            # Validate reasoning
            reasoning = parsed_response['reasoning']
            self._validate_reasoning(reasoning, symbol)
            
            # Validate sources
            sources = parsed_response.get('sources', [])
            self._validate_sources(sources)
            
            # Check for hallucination indicators
            self._check_hallucination_indicators(parsed_response, symbol)
            
            return {
                'sentiment_score': float(sentiment_score),
                'confidence': float(confidence),
                'reasoning': str(reasoning).strip(),
                'sources': sources if sources else ['LLM Analysis'],
                'is_valid': True,
                'validation_errors': []
            }
            
        except Exception as e:
            return {
                'sentiment_score': 0.0,
                'confidence': 0.0,
                'reasoning': f"Validation failed: {str(e)}",
                'sources': ['Error'],
                'is_valid': False,
                'validation_errors': [str(e)]
            }
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON response with error handling"""
        try:
            # Clean response - remove markdown code blocks if present
            cleaned_response = self._clean_response_text(response)
            return json.loads(cleaned_response)
        except json.JSONDecodeError as e:
            # Try to extract JSON from text
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            
            raise LLMAPIError(
                f"Invalid JSON response: {str(e)}",
                error_code="INVALID_JSON",
                context={"response": response[:500]}
            )
    
    def _clean_response_text(self, text: str) -> str:
        """Clean response text by removing markdown and extra formatting"""
        # Remove markdown code blocks
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        
        # Remove extra whitespace
        text = text.strip()
        
        return text
    
    def _validate_required_fields(self, response: Dict[str, Any], required_fields: set) -> None:
        """Validate that all required fields are present"""
        missing_fields = required_fields - set(response.keys())
        if missing_fields:
            raise DataValidationError(
                f"Missing required fields: {missing_fields}",
                error_code="MISSING_FIELDS",
                context={"missing_fields": list(missing_fields)}
            )
    
    def _validate_numeric_range(self, value: Any, range_tuple: tuple, field_name: str) -> None:
        """Validate numeric value is within specified range"""
        try:
            numeric_value = float(value)
        except (ValueError, TypeError):
            raise DataValidationError(
                f"{field_name} must be numeric: {value}",
                error_code="NON_NUMERIC_VALUE",
                context={"field": field_name, "value": value}
            )
        
        min_val, max_val = range_tuple
        if not (min_val <= numeric_value <= max_val):
            raise DataValidationError(
                f"{field_name} must be between {min_val} and {max_val}: {numeric_value}",
                error_code="VALUE_OUT_OF_RANGE",
                context={
                    "field": field_name,
                    "value": numeric_value,
                    "min": min_val,
                    "max": max_val
                }
            )
    
    def _validate_reasoning(self, reasoning: Any, symbol: str) -> None:
        """Validate reasoning text for quality and relevance"""
        if not isinstance(reasoning, str):
            raise DataValidationError(
                "Reasoning must be a string",
                error_code="INVALID_REASONING_TYPE",
                context={"reasoning_type": type(reasoning)}
            )
        
        reasoning = reasoning.strip()
        
        # Check minimum length
        if len(reasoning) < 10:
            raise DataValidationError(
                "Reasoning too short (minimum 10 characters)",
                error_code="REASONING_TOO_SHORT",
                context={"reasoning": reasoning, "length": len(reasoning)}
            )
        
        # Check maximum length
        if len(reasoning) > 1000:
            raise DataValidationError(
                "Reasoning too long (maximum 1000 characters)",
                error_code="REASONING_TOO_LONG",
                context={"reasoning": reasoning[:100] + "...", "length": len(reasoning)}
            )
        
        # Check for symbol relevance
        base_currency, quote_currency = symbol.split('/')
        currencies = [base_currency, quote_currency, symbol]
        
        reasoning_upper = reasoning.upper()
        if not any(currency in reasoning_upper for currency in currencies):
            raise DataValidationError(
                f"Reasoning does not mention the currency pair {symbol}",
                error_code="IRRELEVANT_REASONING",
                context={"reasoning": reasoning, "symbol": symbol}
            )
    
    def _validate_sources(self, sources: Any) -> None:
        """Validate sources list"""
        if not isinstance(sources, list):
            raise DataValidationError(
                "Sources must be a list",
                error_code="INVALID_SOURCES_TYPE",
                context={"sources_type": type(sources)}
            )
        
        if len(sources) == 0:
            # Allow empty sources, will be filled with default
            return
        
        for i, source in enumerate(sources):
            if not isinstance(source, str) or not source.strip():
                raise DataValidationError(
                    f"Source at index {i} must be a non-empty string",
                    error_code="INVALID_SOURCE",
                    context={"source_index": i, "source": source}
                )
    
    def _check_hallucination_indicators(self, response: Dict[str, Any], symbol: str) -> None:
        """Check for common LLM hallucination indicators"""
        reasoning = response.get('reasoning', '').lower()
        
        # Check for nonsensical phrases
        hallucination_phrases = [
            'as an ai', 'i cannot', 'i don\'t have access',
            'i\'m not able to', 'i cannot provide',
            'sorry, but i', 'i apologize', 'i\'m sorry'
        ]
        
        for phrase in hallucination_phrases:
            if phrase in reasoning:
                raise DataValidationError(
                    f"Response contains hallucination indicator: '{phrase}'",
                    error_code="HALLUCINATION_DETECTED",
                    context={"phrase": phrase, "reasoning": reasoning[:200]}
                )
        
        # Check for contradictory sentiment and reasoning
        sentiment_score = response.get('sentiment_score', 0)
        
        positive_words = ['bullish', 'positive', 'optimistic', 'strong', 'growth', 'rise', 'increase']
        negative_words = ['bearish', 'negative', 'pessimistic', 'weak', 'decline', 'fall', 'decrease']
        
        positive_count = sum(1 for word in positive_words if word in reasoning)
        negative_count = sum(1 for word in negative_words if word in reasoning)
        
        # Check for contradiction
        if sentiment_score > 0.3 and negative_count > positive_count:
            raise DataValidationError(
                "Positive sentiment score contradicts negative reasoning",
                error_code="CONTRADICTORY_SENTIMENT",
                context={
                    "sentiment_score": sentiment_score,
                    "positive_words": positive_count,
                    "negative_words": negative_count
                }
            )
        
        if sentiment_score < -0.3 and positive_count > negative_count:
            raise DataValidationError(
                "Negative sentiment score contradicts positive reasoning",
                error_code="CONTRADICTORY_SENTIMENT",
                context={
                    "sentiment_score": sentiment_score,
                    "positive_words": positive_count,
                    "negative_words": negative_count
                }
            )


class LLMPromptValidator:
    """Validator for LLM prompts to ensure quality input"""
    
    def __init__(self):
        self.max_prompt_length = 4000
        self.min_context_length = 50
    
    def validate_sentiment_prompt(self, text_data: List[str], symbol: str) -> Dict[str, Any]:
        """Validate sentiment analysis prompt data"""
        validation_result = {
            'is_valid': True,
            'warnings': [],
            'errors': []
        }
        
        try:
            # Validate symbol
            if not ValidationRules.validate_forex_symbol(symbol):
                validation_result['errors'].append(f"Invalid forex symbol: {symbol}")
                validation_result['is_valid'] = False
            
            # Validate text data
            if not isinstance(text_data, list) or len(text_data) == 0:
                validation_result['errors'].append("Text data must be a non-empty list")
                validation_result['is_valid'] = False
                return validation_result
            
            # Validate each text item
            total_length = 0
            valid_items = 0
            
            for i, text in enumerate(text_data):
                if not isinstance(text, str):
                    validation_result['warnings'].append(f"Item {i} is not a string")
                    continue
                
                text = text.strip()
                if len(text) < 10:
                    validation_result['warnings'].append(f"Item {i} is too short (< 10 chars)")
                    continue
                
                total_length += len(text)
                valid_items += 1
            
            # Check if we have enough valid content
            if valid_items == 0:
                validation_result['errors'].append("No valid text items found")
                validation_result['is_valid'] = False
            elif valid_items < len(text_data) / 2:
                validation_result['warnings'].append("More than half of text items are invalid")
            
            # Check total length
            if total_length > self.max_prompt_length:
                validation_result['warnings'].append(
                    f"Total text length ({total_length}) exceeds recommended maximum ({self.max_prompt_length})"
                )
            elif total_length < self.min_context_length:
                validation_result['warnings'].append(
                    f"Total text length ({total_length}) is below minimum recommended ({self.min_context_length})"
                )
            
            # Check for symbol relevance in text
            base_currency, quote_currency = symbol.split('/')
            currencies = [base_currency, quote_currency, symbol]
            
            relevant_items = 0
            for text in text_data:
                if isinstance(text, str):
                    text_upper = text.upper()
                    if any(currency in text_upper for currency in currencies):
                        relevant_items += 1
            
            if relevant_items == 0:
                validation_result['warnings'].append(
                    f"No text items mention the currency pair {symbol}"
                )
            elif relevant_items < valid_items * 0.3:
                validation_result['warnings'].append(
                    f"Less than 30% of text items are relevant to {symbol}"
                )
            
        except Exception as e:
            validation_result['errors'].append(f"Validation error: {str(e)}")
            validation_result['is_valid'] = False
        
        return validation_result
    
    def create_sentiment_prompt(self, text_data: List[str], symbol: str) -> str:
        """Create a well-structured sentiment analysis prompt"""
        # Validate input first
        validation = self.validate_sentiment_prompt(text_data, symbol)
        if not validation['is_valid']:
            raise DataValidationError(
                f"Invalid prompt data: {validation['errors']}",
                error_code="INVALID_PROMPT_DATA",
                context=validation
            )
        
        # Filter and clean text data
        clean_texts = []
        for text in text_data:
            if isinstance(text, str) and len(text.strip()) >= 10:
                clean_texts.append(text.strip())
        
        # Limit total length
        combined_text = ""
        for text in clean_texts:
            if len(combined_text) + len(text) > self.max_prompt_length - 500:  # Reserve space for prompt
                break
            combined_text += text + "\n\n"
        
        # Create structured prompt
        prompt = f"""Analyze the sentiment for the {symbol} currency pair based on the following text data.

Currency Pair: {symbol}
Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Text Data:
{combined_text.strip()}

Please provide your analysis in the following JSON format:
{{
    "sentiment_score": <float between -1.0 and 1.0>,
    "confidence": <float between 0.0 and 1.0>,
    "reasoning": "<detailed explanation mentioning {symbol} specifically>",
    "sources": ["<list of source types>"]
}}

Requirements:
- sentiment_score: -1.0 (very bearish) to 1.0 (very bullish)
- confidence: 0.0 (no confidence) to 1.0 (very confident)
- reasoning: Must be 10-1000 characters and mention {symbol}
- sources: List of source types (e.g., ["news", "social_media"])

Focus specifically on {symbol} and provide concrete reasoning based on the text data provided."""
        
        return prompt


def validate_llm_response_format(response: Any, expected_format: str = "sentiment") -> bool:
    """Quick validation of LLM response format"""
    try:
        if expected_format == "sentiment":
            validator = LLMResponseValidator()
            result = validator.validate_sentiment_response(response, "EUR/USD")  # Use dummy symbol for format check
            return result['is_valid']
        
        return False
    except Exception:
        return False