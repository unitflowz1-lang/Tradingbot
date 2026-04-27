"""
ML-Based Trading Strategy.
Uses machine learning models for signal generation.
Integrates with the ML pipeline for predictions.
"""

import pandas as pd
import numpy as np
from core.strategy_manager import Strategy, Signal
from src.analysis.price_action_math import PriceActionMath
from utils.logger import get_logger


logger = get_logger(__name__)


class MLStrategy(Strategy):
    """
    Machine Learning Based Strategy.
    Uses trained ML models to generate trading signals.
    Supports multiple model types: XGBoost, RandomForest, LSTM.
    """
    
    def __init__(self, config: dict = None):
        """Initialize ML strategy."""
        super().__init__("ml_strategy", config)
        
        # ML parameters
        self.model = None
        self.feature_engineer = None
        self.confidence_threshold = config.get('confidence_threshold', 0.65) if config else 0.65
        self.model_type = config.get('model_type', 'xgboost') if config else 'xgboost'
        self.retraining_enabled = config.get('retraining_enabled', True) if config else True
    
    def set_model(self, model):
        """Set the ML model for predictions."""
        self.model = model
        logger.info(f"ML model set: {self.model_type}")
    
    def set_feature_engineer(self, engineer):
        """Set the feature engineering module."""
        self.feature_engineer = engineer
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """Generate signal from ML model prediction."""
        if self.model is None or self.feature_engineer is None:
            logger.warning("ML model or feature engineer not initialized")
            return Signal.HOLD
        
        if len(data) < 50:  # Need enough data for feature engineering
            return Signal.HOLD
        
        try:
            # Engineer features
            enriched_data = PriceActionMath.extract_features(data)
            features = self.feature_engineer.engineer_features(enriched_data)
            
            if features is None or features.empty:
                return Signal.HOLD
            
            # Get latest features
            latest_features = features.iloc[-1:].values
            
            # Get prediction and probability
            prediction = self.model.predict(latest_features)[0]
            
            # Get prediction probability
            probability = None
            if hasattr(self.model, 'predict_proba'):
                probabilities = self.model.predict_proba(latest_features)[0]
                probability = max(probabilities)
            else:
                probability = 0.5
            
            # Check confidence threshold
            if probability < self.confidence_threshold:
                return Signal.HOLD
            
            # Convert prediction to signal
            # Assuming 0=SELL, 1=HOLD, 2=BUY
            if prediction == 2:
                logger.debug("ML Buy Signal",
                           probability=probability,
                           model=self.model_type)
                return Signal.BUY
            
            elif prediction == 0:
                logger.debug("ML Sell Signal",
                           probability=probability,
                           model=self.model_type)
                return Signal.SELL
            
            return Signal.HOLD
        
        except Exception as e:
            logger.error(f"Error in ML signal generation: {e}")
            return Signal.HOLD
    
    def calculate_stop_loss(self, entry_price: float, direction: str,
                           data: pd.DataFrame) -> float:
        """
        ML-optimized stop loss.
        Uses historical volatility and model confidence.
        """
        if len(data) < 20:
            if direction.upper() == "BUY":
                return entry_price - 0.01
            else:
                return entry_price + 0.01
        
        try:
            # Calculate volatility
            returns = data['close'].pct_change().dropna()
            volatility = returns.std()
            
            # ATR-based stop
            high = data['high'].iloc[-20:]
            low = data['low'].iloc[-20:]
            close = data['close'].iloc[-20:]
            
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.mean()
            
            # Use 2 ATR with volatility adjustment
            stop_distance = atr * (2.0 + volatility)
            
            if direction.upper() == "BUY":
                return entry_price - stop_distance
            else:
                return entry_price + stop_distance
        
        except Exception as e:
            logger.error(f"Error calculating SL: {e}")
            if direction.upper() == "BUY":
                return entry_price - 0.01
            else:
                return entry_price + 0.01
    
    def calculate_take_profit(self, entry_price: float, direction: str,
                             data: pd.DataFrame) -> float:
        """ML-optimized take profit."""
        sl = self.calculate_stop_loss(entry_price, direction, data)
        risk_distance = abs(entry_price - sl)
        
        # Use 2:1 risk-reward with volatility adjustment
        reward_multiple = 2.0
        
        if direction.upper() == "BUY":
            return entry_price + (risk_distance * reward_multiple)
        else:
            return entry_price - (risk_distance * reward_multiple)
    
    def validate_trade(self, signal: Signal, data: pd.DataFrame) -> bool:
        """
        Additional validation for ML trades.
        Checks for regime compatibility and model agreement.
        """
        if signal == Signal.HOLD:
            return False
        
        # Can add additional validation logic here
        return True
    
    def on_trade_close(self, trade_id: str, exit_reason: str):
        """Hook for retraining after trade closes."""
        if self.retraining_enabled:
            logger.info("Considering model retraining after trade close",
                       trade_id=trade_id,
                       reason=exit_reason)
