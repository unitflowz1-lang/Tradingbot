"""Prompt engineering for LLM sentiment analysis"""

import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from src.validation import ValidationRules
from src.exceptions import DataValidationError
from src.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class PromptTemplate:
    """Template for LLM prompts"""
    name: str
    template: str
    required_variables: List[str]
    description: str


class PromptEngine:
    """Engine for constructing sentiment analysis prompts"""
    
    def __init__(self):
        self.templates = self._load_templates()
        self.max_text_length = 4000
        self.min_text_length = 50
    
    def _load_templates(self) -> Dict[str, PromptTemplate]:
        """Load prompt templates"""
        templates = {}
        
        # Basic sentiment analysis template
        templates["sentiment_basic"] = PromptTemplate(
            name="sentiment_basic",
            template="""Analyze the sentiment for the {symbol} currency pair based on the following text data.

Currency Pair: {symbol}
Analysis Date: {timestamp}

Text Data:
{text_data}

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

Focus specifically on {symbol} and provide concrete reasoning based on the text data provided.""",
            required_variables=["symbol", "timestamp", "text_data"],
            description="Basic sentiment analysis prompt for forex pairs"
        )
        
        # Enhanced sentiment analysis with market context
        templates["sentiment_enhanced"] = PromptTemplate(
            name="sentiment_enhanced",
            template="""You are a professional forex analyst. Analyze the sentiment for {symbol} based on the provided text data.

Currency Pair: {symbol}
Base Currency: {base_currency}
Quote Currency: {quote_currency}
Analysis Time: {timestamp}
Market Session: {market_session}

Text Data to Analyze:
{text_data}

Consider the following factors in your analysis:
1. Economic indicators and central bank policies
2. Geopolitical events affecting the currencies
3. Market sentiment and trader positioning
4. Technical analysis mentions
5. Risk-on/risk-off sentiment

Provide your analysis in this exact JSON format:
{{
    "sentiment_score": <float between -1.0 and 1.0>,
    "confidence": <float between 0.0 and 1.0>,
    "reasoning": "<detailed explanation mentioning {symbol} and key factors>",
    "sources": ["<source types>"],
    "key_factors": ["<list of 2-5 key factors influencing sentiment>"],
    "market_impact": "<expected short-term impact on {symbol}>"
}}

Be specific about {symbol} and avoid generic market commentary.""",
            required_variables=["symbol", "base_currency", "quote_currency", "timestamp", "market_session", "text_data"],
            description="Enhanced sentiment analysis with market context"
        )
        
        # News-focused sentiment analysis
        templates["sentiment_news"] = PromptTemplate(
            name="sentiment_news",
            template="""Analyze the sentiment impact of news articles on {symbol}.

Currency Pair: {symbol}
News Analysis Date: {timestamp}

News Articles:
{text_data}

Focus on:
- Central bank announcements and policy changes
- Economic data releases (GDP, inflation, employment)
- Political developments and trade relations
- Market-moving events specific to {base_currency} and {quote_currency}

Provide analysis in JSON format:
{{
    "sentiment_score": <float between -1.0 and 1.0>,
    "confidence": <float between 0.0 and 1.0>,
    "reasoning": "<explanation focusing on news impact on {symbol}>",
    "sources": ["news"],
    "news_impact": "<immediate vs long-term impact assessment>",
    "key_events": ["<list of most significant news items>"]
}}

Rate confidence based on news credibility and relevance to {symbol}.""",
            required_variables=["symbol", "base_currency", "quote_currency", "timestamp", "text_data"],
            description="News-focused sentiment analysis for forex pairs"
        )
        
        return templates
    
    def create_sentiment_prompt(
        self, 
        text_data: List[str], 
        symbol: str, 
        template_name: str = "sentiment_basic",
        **kwargs
    ) -> str:
        """Create sentiment analysis prompt"""
        
        # Validate inputs
        self._validate_prompt_inputs(text_data, symbol, template_name)
        
        # Get template
        template = self.templates.get(template_name)
        if not template:
            raise DataValidationError(
                f"Unknown template: {template_name}",
                error_code="UNKNOWN_TEMPLATE",
                context={"template_name": template_name, "available": list(self.templates.keys())}
            )
        
        # Prepare text data
        processed_text = self._process_text_data(text_data, symbol)
        
        # Prepare template variables
        variables = self._prepare_template_variables(symbol, processed_text, **kwargs)
        
        # Validate required variables
        missing_vars = set(template.required_variables) - set(variables.keys())
        if missing_vars:
            raise DataValidationError(
                f"Missing required template variables: {missing_vars}",
                error_code="MISSING_TEMPLATE_VARS",
                context={"missing": list(missing_vars), "required": template.required_variables}
            )
        
        # Format template
        try:
            prompt = template.template.format(**variables)
            logger.info(f"Created {template_name} prompt for {symbol} with {len(processed_text)} chars of text")
            return prompt
        except KeyError as e:
            raise DataValidationError(
                f"Template formatting error: {str(e)}",
                error_code="TEMPLATE_FORMAT_ERROR",
                context={"error": str(e), "variables": list(variables.keys())}
            )
    
    def _validate_prompt_inputs(self, text_data: List[str], symbol: str, template_name: str) -> None:
        """Validate prompt inputs"""
        # Validate symbol
        if not ValidationRules.validate_forex_symbol(symbol):
            raise DataValidationError(
                f"Invalid forex symbol: {symbol}",
                error_code="INVALID_SYMBOL",
                context={"symbol": symbol}
            )
        
        # Validate text data
        if not isinstance(text_data, list) or len(text_data) == 0:
            raise DataValidationError(
                "Text data must be a non-empty list",
                error_code="INVALID_TEXT_DATA",
                context={"text_data_type": type(text_data), "length": len(text_data) if isinstance(text_data, list) else 0}
            )
        
        # Validate template name
        if not isinstance(template_name, str) or not template_name.strip():
            raise DataValidationError(
                "Template name must be a non-empty string",
                error_code="INVALID_TEMPLATE_NAME",
                context={"template_name": template_name}
            )
    
    def _process_text_data(self, text_data: List[str], symbol: str) -> str:
        """Process and clean text data"""
        # Filter valid text items
        valid_texts = []
        for text in text_data:
            if isinstance(text, str) and len(text.strip()) >= 10:
                valid_texts.append(text.strip())
        
        if not valid_texts:
            raise DataValidationError(
                "No valid text items found (minimum 10 characters each)",
                error_code="NO_VALID_TEXT",
                context={"original_count": len(text_data), "valid_count": 0}
            )
        
        # Combine texts with length limit
        combined_text = ""
        for text in valid_texts:
            if len(combined_text) + len(text) + 2 > self.max_text_length:
                break
            combined_text += text + "\n\n"
        
        combined_text = combined_text.strip()
        
        # Check final length
        if len(combined_text) < self.min_text_length:
            raise DataValidationError(
                f"Combined text too short: {len(combined_text)} < {self.min_text_length}",
                error_code="TEXT_TOO_SHORT",
                context={"length": len(combined_text), "minimum": self.min_text_length}
            )
        
        return combined_text
    
    def _prepare_template_variables(self, symbol: str, text_data: str, **kwargs) -> Dict[str, str]:
        """Prepare variables for template formatting"""
        # Parse symbol
        base_currency, quote_currency = symbol.split('/')
        
        # Base variables
        variables = {
            "symbol": symbol,
            "base_currency": base_currency,
            "quote_currency": quote_currency,
            "text_data": text_data,
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
        }
        
        # Add market session info
        variables["market_session"] = self._get_market_session()
        
        # Add any additional variables from kwargs
        variables.update(kwargs)
        
        return variables
    
    def _get_market_session(self) -> str:
        """Determine current market session"""
        current_hour = datetime.now().hour
        
        # Simplified market session detection (UTC)
        if 0 <= current_hour < 8:
            return "Asian Session"
        elif 8 <= current_hour < 16:
            return "European Session"
        elif 16 <= current_hour < 24:
            return "American Session"
        else:
            return "Off-Hours"
    
    def get_available_templates(self) -> List[Dict[str, str]]:
        """Get list of available templates"""
        return [
            {
                "name": template.name,
                "description": template.description,
                "required_variables": template.required_variables
            }
            for template in self.templates.values()
        ]
    
    def validate_template_variables(self, template_name: str, variables: Dict[str, Any]) -> List[str]:
        """Validate variables for a specific template"""
        template = self.templates.get(template_name)
        if not template:
            return [f"Unknown template: {template_name}"]
        
        errors = []
        missing_vars = set(template.required_variables) - set(variables.keys())
        if missing_vars:
            errors.append(f"Missing required variables: {missing_vars}")
        
        return errors
    
    def estimate_token_count(self, prompt: str) -> int:
        """Estimate token count for prompt (rough approximation)"""
        # Rough estimation: ~4 characters per token
        return len(prompt) // 4
    
    def optimize_prompt_length(self, text_data: List[str], symbol: str, max_tokens: int = 3000) -> List[str]:
        """Optimize text data length to fit within token limits"""
        # Estimate tokens needed for template (excluding text_data)
        template_tokens = 500  # Conservative estimate for template overhead
        available_tokens = max_tokens - template_tokens
        available_chars = available_tokens * 4  # Rough conversion
        
        optimized_texts = []
        current_length = 0
        
        for text in text_data:
            if isinstance(text, str) and len(text.strip()) >= 10:
                text = text.strip()
                if current_length + len(text) + 2 <= available_chars:
                    optimized_texts.append(text)
                    current_length += len(text) + 2
                else:
                    # Try to fit partial text
                    remaining_chars = available_chars - current_length - 2
                    if remaining_chars > 50:  # Only if we can fit meaningful content
                        partial_text = text[:remaining_chars] + "..."
                        optimized_texts.append(partial_text)
                    break
        
        return optimized_texts