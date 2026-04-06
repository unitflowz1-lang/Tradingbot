"""Response parsing and validation for LLM sentiment analysis"""

import json
import re
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timezone
from src.models import SentimentResult
from src.exceptions import LLMAPIError, DataValidationError
from src.llm_validation import LLMResponseValidator
from src.logging_config import get_logger

logger = get_logger(__name__)


class ResponseParser:
    """Parser for LLM sentiment analysis responses"""
    
    def __init__(self):
        self.validator = LLMResponseValidator()
        self.hallucination_patterns = [
            r"as an ai",
            r"i cannot",
            r"i don't have access",
            r"i'm not able to",
            r"i cannot provide",
            r"sorry, but i",
            r"i apologize",
            r"i'm sorry",
            r"i don't know",
            r"i'm not sure"
        ]
        self.confidence_keywords = {
            "high": ["strong", "clear", "obvious", "definite", "certain", "confident"],
            "medium": ["likely", "probable", "suggests", "indicates", "appears"],
            "low": ["uncertain", "unclear", "mixed", "conflicting", "ambiguous"]
        }
    
    def parse_sentiment_response(
        self, 
        response_content: str, 
        symbol: str,
        validate: bool = True
    ) -> SentimentResult:
        """Parse LLM response into SentimentResult"""
        
        try:
            # Clean and extract JSON
            cleaned_response = self._clean_response_content(response_content)
            parsed_data = self._extract_json_data(cleaned_response)
            
            # Validate if requested
            if validate:
                validation_result = self.validator.validate_sentiment_response(parsed_data, symbol)
                if not validation_result['is_valid']:
                    logger.warning(f"Response validation failed: {validation_result['validation_errors']}")
                    # Use validated/corrected data
                    parsed_data = validation_result
            
            # Extract and validate individual fields
            sentiment_score = self._extract_sentiment_score(parsed_data)
            confidence = self._extract_confidence(parsed_data, cleaned_response)
            reasoning = self._extract_reasoning(parsed_data, symbol)
            sources = self._extract_sources(parsed_data)
            
            # Check for hallucinations
            if self._detect_hallucinations(reasoning):
                logger.warning(f"Potential hallucination detected in response for {symbol}")
                confidence = min(confidence, 0.3)  # Reduce confidence
            
            # Create SentimentResult
            result = SentimentResult(
                symbol=symbol,
                sentiment_score=sentiment_score,
                confidence=confidence,
                reasoning=reasoning,
                sources=sources,
                timestamp=datetime.now(timezone.utc)
            )
            
            logger.info(f"Parsed sentiment for {symbol}: score={sentiment_score:.3f}, confidence={confidence:.3f}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to parse sentiment response for {symbol}: {str(e)}")
            # Return neutral sentiment with low confidence as fallback
            return self._create_fallback_result(symbol, str(e))
    
    def _clean_response_content(self, content: str) -> str:
        """Clean response content"""
        if not isinstance(content, str):
            raise DataValidationError(
                "Response content must be a string",
                error_code="INVALID_CONTENT_TYPE",
                context={"content_type": type(content)}
            )
        
        # Remove markdown code blocks
        content = re.sub(r'```json\s*', '', content, flags=re.IGNORECASE)
        content = re.sub(r'```\s*', '', content)
        
        # Remove extra whitespace
        content = content.strip()
        
        if not content:
            raise DataValidationError(
                "Response content is empty after cleaning",
                error_code="EMPTY_CONTENT",
                context={"original_length": len(content)}
            )
        
        return content
    
    def _extract_json_data(self, content: str) -> Dict[str, Any]:
        """Extract JSON data from response content"""
        try:
            # Try direct JSON parsing first
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to find JSON within the text
            json_patterns = [
                r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}',  # Simple nested JSON
                r'\{.*?\}',  # Any content between braces
            ]
            
            for pattern in json_patterns:
                matches = re.findall(pattern, content, re.DOTALL)
                for match in matches:
                    try:
                        return json.loads(match)
                    except json.JSONDecodeError:
                        continue
            
            # If no valid JSON found, try to extract key-value pairs
            return self._extract_key_value_pairs(content)
    
    def _extract_key_value_pairs(self, content: str) -> Dict[str, Any]:
        """Extract key-value pairs from non-JSON text"""
        result = {}
        
        # Patterns for different formats
        patterns = {
            'sentiment_score': [
                r'sentiment[_\s]*score[:\s]*(-?\d+\.?\d*)',
                r'score[:\s]*(-?\d+\.?\d*)',
                r'sentiment[:\s]*(-?\d+\.?\d*)'
            ],
            'confidence': [
                r'confidence[:\s]*(\d+\.?\d*)',
                r'certainty[:\s]*(\d+\.?\d*)'
            ],
            'reasoning': [
                r'reasoning[:\s]*["\']([^"\']+)["\']',
                r'explanation[:\s]*["\']([^"\']+)["\']',
                r'analysis[:\s]*["\']([^"\']+)["\']'
            ]
        }
        
        for key, key_patterns in patterns.items():
            for pattern in key_patterns:
                match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
                if match:
                    value = match.group(1).strip()
                    if key in ['sentiment_score', 'confidence']:
                        try:
                            result[key] = float(value)
                        except ValueError:
                            continue
                    else:
                        result[key] = value
                    break
        
        # Set defaults for missing values
        if 'sentiment_score' not in result:
            result['sentiment_score'] = 0.0
        if 'confidence' not in result:
            result['confidence'] = 0.1  # Low confidence for extracted data
        if 'reasoning' not in result:
            result['reasoning'] = "Unable to extract clear reasoning from response"
        
        result['sources'] = ['LLM Analysis']
        
        return result
    
    def _extract_sentiment_score(self, data: Dict[str, Any]) -> float:
        """Extract and validate sentiment score"""
        score = data.get('sentiment_score', 0.0)
        
        try:
            score = float(score)
        except (ValueError, TypeError):
            logger.warning(f"Invalid sentiment score: {score}, using 0.0")
            return 0.0
        
        # Clamp to valid range
        score = max(-1.0, min(1.0, score))
        
        return score
    
    def _extract_confidence(self, data: Dict[str, Any], full_text: str) -> float:
        """Extract and validate confidence score"""
        confidence = data.get('confidence', 0.5)
        
        try:
            confidence = float(confidence)
        except (ValueError, TypeError):
            # Try to infer confidence from text
            confidence = self._infer_confidence_from_text(full_text)
        
        # Clamp to valid range
        confidence = max(0.0, min(1.0, confidence))
        
        return confidence
    
    def _infer_confidence_from_text(self, text: str) -> float:
        """Infer confidence level from text content"""
        text_lower = text.lower()
        
        # Count confidence indicators
        high_count = sum(1 for keyword in self.confidence_keywords["high"] if keyword in text_lower)
        medium_count = sum(1 for keyword in self.confidence_keywords["medium"] if keyword in text_lower)
        low_count = sum(1 for keyword in self.confidence_keywords["low"] if keyword in text_lower)
        
        # Calculate confidence based on keyword presence
        if high_count > low_count and high_count > medium_count:
            return 0.8
        elif low_count > high_count and low_count > medium_count:
            return 0.3
        elif medium_count > 0:
            return 0.6
        else:
            return 0.5  # Default medium confidence
    
    def _extract_reasoning(self, data: Dict[str, Any], symbol: str) -> str:
        """Extract and validate reasoning"""
        reasoning = data.get('reasoning', '')
        
        if not isinstance(reasoning, str):
            reasoning = str(reasoning)
        
        reasoning = reasoning.strip()
        
        # Validate minimum length
        if len(reasoning) < 10:
            reasoning = f"Limited analysis available for {symbol} based on provided data."
        
        # Validate maximum length
        if len(reasoning) > 1000:
            reasoning = reasoning[:997] + "..."
        
        # Ensure symbol is mentioned
        if symbol.upper() not in reasoning.upper():
            prefix = f"Analysis for {symbol}: "
            # Check if adding prefix would exceed length limit
            if len(prefix + reasoning) > 1000:
                # Truncate reasoning to make room for prefix
                max_reasoning_length = 1000 - len(prefix) - 3  # 3 for "..."
                reasoning = reasoning[:max_reasoning_length] + "..."
            reasoning = prefix + reasoning
        
        return reasoning
    
    def _extract_sources(self, data: Dict[str, Any]) -> List[str]:
        """Extract and validate sources"""
        sources = data.get('sources', ['LLM Analysis'])
        
        if not isinstance(sources, list):
            if isinstance(sources, str):
                sources = [sources]
            else:
                sources = ['LLM Analysis']
        
        # Filter valid sources
        valid_sources = []
        for source in sources:
            if isinstance(source, str) and source.strip():
                valid_sources.append(source.strip())
        
        if not valid_sources:
            valid_sources = ['LLM Analysis']
        
        return valid_sources
    
    def _detect_hallucinations(self, text: str) -> bool:
        """Detect potential hallucinations in response"""
        text_lower = text.lower()
        
        for pattern in self.hallucination_patterns:
            if re.search(pattern, text_lower):
                return True
        
        return False
    
    def _create_fallback_result(self, symbol: str, error_msg: str) -> SentimentResult:
        """Create fallback sentiment result for parsing failures"""
        return SentimentResult(
            symbol=symbol,
            sentiment_score=0.0,
            confidence=0.1,
            reasoning=f"Failed to parse LLM response: {error_msg}. Returning neutral sentiment.",
            sources=['Error'],
            timestamp=datetime.now(timezone.utc)
        )
    
    def validate_response_format(self, response_content: str) -> Dict[str, Any]:
        """Validate response format and return validation info"""
        validation_info = {
            'is_valid': True,
            'errors': [],
            'warnings': [],
            'extracted_fields': []
        }
        
        try:
            cleaned_content = self._clean_response_content(response_content)
            parsed_data = self._extract_json_data(cleaned_content)
            
            # Check required fields
            required_fields = ['sentiment_score', 'confidence', 'reasoning']
            for field in required_fields:
                if field in parsed_data:
                    validation_info['extracted_fields'].append(field)
                else:
                    validation_info['errors'].append(f"Missing required field: {field}")
                    validation_info['is_valid'] = False
            
            # Validate field types and ranges
            if 'sentiment_score' in parsed_data:
                try:
                    score = float(parsed_data['sentiment_score'])
                    if not -1.0 <= score <= 1.0:
                        validation_info['warnings'].append(f"Sentiment score out of range: {score}")
                except (ValueError, TypeError):
                    validation_info['errors'].append("Sentiment score is not numeric")
                    validation_info['is_valid'] = False
            
            if 'confidence' in parsed_data:
                try:
                    conf = float(parsed_data['confidence'])
                    if not 0.0 <= conf <= 1.0:
                        validation_info['warnings'].append(f"Confidence out of range: {conf}")
                except (ValueError, TypeError):
                    validation_info['errors'].append("Confidence is not numeric")
                    validation_info['is_valid'] = False
            
            # Check for hallucination indicators
            if 'reasoning' in parsed_data:
                reasoning = str(parsed_data['reasoning'])
                if self._detect_hallucinations(reasoning):
                    validation_info['warnings'].append("Potential hallucination detected in reasoning")
        
        except Exception as e:
            validation_info['is_valid'] = False
            validation_info['errors'].append(f"Parsing error: {str(e)}")
        
        return validation_info
    
    def extract_additional_fields(self, response_content: str) -> Dict[str, Any]:
        """Extract additional fields that might be present in enhanced responses"""
        additional_fields = {}
        
        try:
            cleaned_content = self._clean_response_content(response_content)
            parsed_data = self._extract_json_data(cleaned_content)
            
            # Extract optional fields
            optional_fields = [
                'key_factors', 'market_impact', 'news_impact', 
                'key_events', 'risk_factors', 'time_horizon'
            ]
            
            for field in optional_fields:
                if field in parsed_data:
                    additional_fields[field] = parsed_data[field]
        
        except Exception as e:
            logger.warning(f"Failed to extract additional fields: {str(e)}")
        
        return additional_fields