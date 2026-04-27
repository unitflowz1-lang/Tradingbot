"""Abstract base classes and interfaces for the AI Forex Trading Bot"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from src.models import (
    MarketData, SentimentResult, TechnicalSignal, TradingSignal,
    Order, Position, Portfolio, RiskAssessment, ExecutionResult,
    OrderStatus
)


class DataCollector(ABC):
    """Abstract base class for data collection"""
    
    @abstractmethod
    async def collect_data(self, symbols: List[str], timeframe: str) -> Dict[str, Any]:
        """Collect data for given symbols and timeframe"""
        pass
    
    @abstractmethod
    async def validate_data(self, data: Dict[str, Any]) -> bool:
        """Validate collected data"""
        pass


class SentimentAnalyzer(ABC):
    """Abstract base class for sentiment analysis"""
    
    @abstractmethod
    async def analyze_sentiment(self, text_data: List[str], symbol: str) -> SentimentResult:
        """Analyze sentiment from text data"""
        pass
    
    @abstractmethod
    def validate_response(self, response: Dict[str, Any]) -> bool:
        """Validate LLM response"""
        pass


class TechnicalAnalyzer(ABC):
    """Abstract base class for technical analysis"""
    
    @abstractmethod
    def calculate_indicators(self, market_data: MarketData) -> Dict[str, float]:
        """Calculate technical indicators"""
        pass
    
    @abstractmethod
    def generate_signals(self, indicators: Dict[str, float]) -> List[TechnicalSignal]:
        """Generate technical signals from indicators"""
        pass


class SignalGenerator(ABC):
    """Abstract base class for signal generation"""
    
    @abstractmethod
    def generate_signal(self, sentiment: SentimentResult, technical: List[TechnicalSignal]) -> TradingSignal:
        """Generate trading signal from sentiment and technical analysis"""
        pass
    
    @abstractmethod
    def calculate_confidence(self, signal: TradingSignal) -> float:
        """Calculate signal confidence"""
        pass


class RiskManager(ABC):
    """Abstract base class for risk management"""
    
    @abstractmethod
    def validate_trade(self, signal: TradingSignal, portfolio: Portfolio) -> RiskAssessment:
        """Validate trade against risk parameters"""
        pass
    
    @abstractmethod
    def calculate_position_size(self, signal: TradingSignal, account_balance: float) -> float:
        """Calculate appropriate position size"""
        pass


class TradeExecutor(ABC):
    """Abstract base class for trade execution"""
    
    @abstractmethod
    async def execute_trade(self, order: Order) -> ExecutionResult:
        """Execute trade order"""
        pass
    
    @abstractmethod
    async def modify_order(self, order_id: str, modifications: Dict[str, Any]) -> bool:
        """Modify existing order"""
        pass
    
    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order"""
        pass


class BrokerInterface(ABC):
    """Abstract base class for broker API integration"""
    
    @abstractmethod
    async def connect(self) -> bool:
        """Connect to broker API"""
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """Disconnect from broker API"""
        pass
    
    @abstractmethod
    async def get_account_info(self) -> Portfolio:
        """Get account information"""
        pass
    
    @abstractmethod
    async def get_market_data(self, symbol: str) -> MarketData:
        """Get real-time market data"""
        pass
    
    @abstractmethod
    async def get_order_status(self, order_id: str) -> Optional[OrderStatus]:
        """Get current status of an order"""
        pass


class PerformanceMonitor(ABC):
    """Abstract base class for performance monitoring"""
    
    @abstractmethod
    def track_trade(self, order: Order, result: ExecutionResult) -> None:
        """Track trade execution"""
        pass
    
    @abstractmethod
    def calculate_metrics(self) -> Dict[str, float]:
        """Calculate performance metrics"""
        pass
    
    @abstractmethod
    def generate_report(self) -> Dict[str, Any]:
        """Generate performance report"""
        pass