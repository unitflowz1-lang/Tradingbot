"""LLM client for sentiment analysis with multiple provider support"""

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Type
from dataclasses import dataclass
from enum import Enum
import aiohttp
from src.config import LLMConfig
from src.exceptions import LLMAPIError
from src.logging_config import get_logger

logger = get_logger(__name__)


class LLMProvider(Enum):
    """Supported LLM providers"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    GOOGLE = "google"


@dataclass
class LLMRequest:
    """LLM API request structure"""
    prompt: str
    max_tokens: int
    temperature: float
    model: str
    timeout: int


@dataclass
class LLMResponse:
    """LLM API response structure"""
    content: str
    provider: str
    model: str
    tokens_used: int
    response_time: float
    timestamp: float


class RetryStrategy:
    """Exponential backoff retry strategy"""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt with exponential backoff"""
        delay = self.base_delay * (2 ** attempt)
        return min(delay, self.max_delay)
    
    async def execute_with_retry(self, func, *args, **kwargs):
        """Execute function with retry logic"""
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                
                if attempt == self.max_retries:
                    break
                
                delay = self.get_delay(attempt)
                logger.warning(
                    f"Attempt {attempt + 1} failed: {str(e)}. "
                    f"Retrying in {delay}s"
                )
                await asyncio.sleep(delay)
        
        raise last_exception


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    def __init__(self, config: LLMConfig):
        self.config = config
        self.retry_strategy = RetryStrategy()
    
    @abstractmethod
    async def make_request(self, request: LLMRequest) -> LLMResponse:
        """Make API request to LLM provider"""
        pass
    
    @abstractmethod
    def validate_config(self) -> List[str]:
        """Validate provider configuration"""
        pass


class OpenAIProvider(BaseLLMProvider):
    """OpenAI API provider implementation"""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.base_url = "https://api.openai.com/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
    
    async def make_request(self, request: LLMRequest) -> LLMResponse:
        """Make request to OpenAI API"""
        start_time = time.time()
        
        payload = {
            "model": request.model,
            "messages": [
                {"role": "user", "content": request.prompt}
            ],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature
        }
        
        async def _make_api_call():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=request.timeout)) as session:
                async with session.post(self.base_url, headers=self.headers, json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        error_msg = (
                            f"OpenAI API error: {response.status} - "
                            f"{error_text}"
                        )
                        context = {
                            "status_code": response.status,
                            "response": error_text,
                            "model": request.model,
                        }
                        raise LLMAPIError(
                            error_msg,
                            "OPENAI_API_ERROR",
                            context,
                        )
                    
                    data = await response.json()
                    
                    if "choices" not in data or len(data["choices"]) == 0:
                        raise LLMAPIError(
                            "No choices in OpenAI response",
                            error_code="NO_CHOICES",
                            context={"response": data}
                        )
                    
                    content = data["choices"][0]["message"]["content"]
                    tokens_used = data.get("usage", {}).get("total_tokens", 0)
                    
                    return LLMResponse(
                        content=content,
                        provider="openai",
                        model=request.model,
                        tokens_used=tokens_used,
                        response_time=time.time() - start_time,
                        timestamp=time.time()
                    )
        
        return await self.retry_strategy.execute_with_retry(_make_api_call)
    
    def validate_config(self) -> List[str]:
        """Validate OpenAI configuration"""
        errors = []
        
        if not self.config.api_key:
            errors.append("OpenAI API key is required")
        
        if not self.config.model:
            errors.append("OpenAI model is required")
        
        valid_models = ["gpt-3.5-turbo", "gpt-4", "gpt-4-turbo-preview"]
        if self.config.model not in valid_models:
            errors.append(
                f"Invalid OpenAI model: {self.config.model}. "
                f"Valid models: {valid_models}"
            )
        
        if not 1 <= self.config.max_tokens <= 4000:
            errors.append("max_tokens must be between 1 and 4000")
        
        if not 0.0 <= self.config.temperature <= 2.0:
            errors.append("temperature must be between 0.0 and 2.0")
        
        return errors


class GeminiProvider(BaseLLMProvider):
    """Google Gemini API provider implementation"""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.base_url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{config.model}:generateContent"
        )
        self.headers = {
            "x-goog-api-key": config.api_key,
            "Content-Type": "application/json",
        }

    async def make_request(self, request: LLMRequest) -> LLMResponse:
        """Make request to Gemini API"""
        start_time = time.time()

        payload = {
            "contents": [{"parts": [{"text": request.prompt}]}],
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
            },
        }
        
        async def _make_api_call():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=request.timeout)) as session:
                async with session.post(self.base_url, headers=self.headers, json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        error_msg = (
                            f"Gemini API error: {response.status} - "
                            f"{error_text}"
                        )
                        context = {
                            "status_code": response.status,
                            "response": error_text,
                            "model": request.model,
                        }
                        raise LLMAPIError(
                            error_msg,
                            "GEMINI_API_ERROR",
                            context,
                        )
                    
                    data = await response.json()
                    
                    if "candidates" not in data or len(data["candidates"]) == 0:
                        raise LLMAPIError(
                            "No candidates in Gemini response",
                            error_code="NO_CANDIDATES",
                            context={"response": data}
                        )
                    
                    content = data["candidates"][0]["content"]["parts"][0]["text"]
                    tokens_used = data.get("usageMetadata", {}).get(
                        "totalTokenCount", 0
                    )
                    
                    return LLMResponse(
                        content=content,
                        provider="gemini",
                        model=request.model,
                        tokens_used=tokens_used,
                        response_time=time.time() - start_time,
                        timestamp=time.time()
                    )
        
        return await self.retry_strategy.execute_with_retry(_make_api_call)

    def validate_config(self) -> List[str]:
        """Validate Gemini configuration"""
        errors = []
        
        if not self.config.api_key:
            errors.append("Gemini API key is required")
        
        if not self.config.model:
            errors.append("Gemini model is required")
        
        valid_models = [
            "gemini-pro",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "gemini-2.5-pro",
        ]
        if self.config.model not in valid_models:
            errors.append(
                f"Invalid Gemini model: {self.config.model}. "
                f"Valid models: {valid_models}"
            )
        
        if not 1 <= self.config.max_tokens <= 8192:
            errors.append("max_tokens must be 1-8192")
            
        if not 0.0 <= self.config.temperature <= 1.0:
            errors.append("temperature must be between 0.0 and 1.0")
            
        return errors


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude API provider implementation"""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.base_url = "https://api.anthropic.com/v1/messages"
        self.headers = {
            "x-api-key": config.api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
    
    async def make_request(self, request: LLMRequest) -> LLMResponse:
        """Make request to Anthropic API"""
        start_time = time.time()
        
        payload = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [
                {"role": "user", "content": request.prompt}
            ]
        }
        
        async def _make_api_call():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=request.timeout)) as session:
                async with session.post(self.base_url, headers=self.headers, json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        error_msg = (
                            f"Anthropic API error: {response.status} - "
                            f"{error_text}"
                        )
                        context = {
                            "status_code": response.status,
                            "response": error_text,
                            "model": request.model,
                        }
                        raise LLMAPIError(
                            error_msg,
                            "ANTHROPIC_API_ERROR",
                            context,
                        )
                    
                    data = await response.json()
                    
                    if "content" not in data or len(data["content"]) == 0:
                        raise LLMAPIError(
                            "No content in Anthropic response",
                            error_code="NO_CONTENT",
                            context={"response": data}
                        )
                    
                    content = data["content"][0]["text"]
                    tokens_used = data.get("usage", {}).get(
                        "input_tokens", 0
                    ) + data.get("usage", {}).get("output_tokens", 0)
                    
                    return LLMResponse(
                        content=content,
                        provider="anthropic",
                        model=request.model,
                        tokens_used=tokens_used,
                        response_time=time.time() - start_time,
                        timestamp=time.time()
                    )
        
        return await self.retry_strategy.execute_with_retry(_make_api_call)
    
    def validate_config(self) -> List[str]:
        """Validate Anthropic configuration"""
        errors = []
        
        if not self.config.api_key:
            errors.append("Anthropic API key is required")
        
        if not self.config.model:
            errors.append("Anthropic model is required")
        
        valid_models = [
            "claude-3-sonnet-20240229",
            "claude-3-opus-20240229",
            "claude-3-haiku-20240307",
        ]
        if self.config.model not in valid_models:
            errors.append(
                f"Invalid Anthropic model: {self.config.model}. "
                f"Valid models: {valid_models}"
            )
        
        if not 1 <= self.config.max_tokens <= 4000:
            errors.append("max_tokens must be between 1 and 4000")
        
        if not 0.0 <= self.config.temperature <= 1.0:
            errors.append("temperature must be between 0.0 and 1.0")
        
        return errors


class LLMClient:
    """Main LLM client with multi-provider support"""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.provider = self._create_provider()
        self._validate_configuration()
    
    def _create_provider(self) -> BaseLLMProvider:
        """Create appropriate provider based on configuration"""
        provider_map: Dict[str, Type[BaseLLMProvider]] = {
            LLMProvider.OPENAI.value: OpenAIProvider,
            LLMProvider.ANTHROPIC.value: AnthropicProvider,
            LLMProvider.GEMINI.value: GeminiProvider,
            LLMProvider.GOOGLE.value: GeminiProvider,
        }
        
        provider_class = provider_map.get(self.config.provider.lower())
        if not provider_class:
            msg = f"Unsupported LLM provider: {self.config.provider}"
            context = {
                "provider": self.config.provider,
                "supported": list(provider_map.keys()),
            }
            raise LLMAPIError(
                msg, "UNSUPPORTED_PROVIDER", context
            )
        
        return provider_class(self.config)
    
    def _validate_configuration(self) -> None:
        """Validate LLM configuration"""
        errors = self.provider.validate_config()
        
        # Additional general validations
        if self.config.timeout <= 0:
            errors.append("timeout must be positive")
        
        if errors:
            raise LLMAPIError(
                f"Invalid LLM configuration: {'; '.join(errors)}",
                error_code="INVALID_CONFIG",
                context={"errors": errors},
            )
    
    async def generate_response(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate response from LLM"""
        if not prompt or not prompt.strip():
            raise LLMAPIError(
                "Prompt cannot be empty",
                error_code="EMPTY_PROMPT",
                context={"prompt": prompt}
            )
        
        request = LLMRequest(
            prompt=prompt.strip(),
            max_tokens=kwargs.get('max_tokens', self.config.max_tokens),
            temperature=kwargs.get('temperature', self.config.temperature),
            model=kwargs.get('model', self.config.model),
            timeout=kwargs.get('timeout', self.config.timeout)
        )
        
        logger.info(
            f"Making LLM request to {self.config.provider} "
            f"with model {request.model}"
        )
        
        try:
            response = await self.provider.make_request(request)
            logger.info(
                f"LLM response received: {response.tokens_used} tokens, "
                f"{response.response_time:.2f}s"
            )
            return response
        except Exception as e:
            logger.error(f"LLM request failed: {str(e)}")
            raise
    
    async def analyze_sentiment(self, prompt: str, **kwargs) -> LLMResponse:
        """Specialized method for sentiment analysis"""
        return await self.generate_response(prompt, **kwargs)
    
    def get_provider_info(self) -> Dict[str, Any]:
        """Get information about current provider"""
        return {
            "provider": self.config.provider,
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "timeout": self.config.timeout
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on LLM provider"""
        try:
            test_prompt = "Respond with 'OK' if you can process this request."
            response = await self.generate_response(test_prompt, max_tokens=10)
            
            return {
                "status": "healthy",
                "provider": self.config.provider,
                "model": self.config.model,
                "response_time": response.response_time,
                "timestamp": response.timestamp
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "provider": self.config.provider,
                "model": self.config.model,
                "error": str(e),
                "timestamp": time.time()
            }
