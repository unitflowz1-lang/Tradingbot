"""
ML Prediction Pipeline.
Coordinates feature engineering, model loading, and predictions.
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple
from utils.logger import get_logger
from ml.feature_engineering import FeatureEngineer, FeatureSelector
from ml.model_trainer import ModelTrainer


logger = get_logger(__name__)


class MLPredictor:
    """
    Complete ML prediction pipeline.
    Orchestrates feature engineering, model loading, and prediction.
    """
    
    def __init__(self, model_type: str = "xgboost", model_path: Optional[str] = None):
        """
        Initialize MLPredictor.
        
        Args:
            model_type: Type of model (xgboost, random_forest)
            model_path: Path to pretrained model
        """
        self.model_type = model_type
        self.feature_engineer = FeatureEngineer()
        self.feature_selector = FeatureSelector()
        self.model_trainer = ModelTrainer(model_type=model_type)
        
        # Load pretrained model if provided
        if model_path:
            self.model_trainer.load_model(model_path)
    
    def predict_signal(self, data: pd.DataFrame) -> Tuple[Optional[str], Optional[float]]:
        """
        Generate trading signal from price data.
        
        Args:
            data: OHLCV DataFrame
        
        Returns:
            Tuple of (signal, probability)
            signal: 'BUY', 'SELL', or 'HOLD'
            probability: Confidence score (0.0-1.0)
        """
        try:
            # Engineer features
            features = self.feature_engineer.engineer_features(data)
            
            if features is None or features.empty:
                return 'HOLD', 0.5
            
            # Select relevant features
            features_selected = self.feature_selector.select_features(features)
            
            if features_selected.empty:
                return 'HOLD', 0.5
            
            # Get latest features
            latest_features = features_selected.iloc[-1:].values
            
            # Make prediction
            predictions, probabilities = self.model_trainer.predict(features_selected.iloc[-1:])
            
            if predictions is None:
                return 'HOLD', 0.5
            
            prediction = predictions[0]
            probability = np.max(probabilities[0]) if probabilities is not None else 0.5
            
            # Map prediction to signal
            signal_map = {0: 'SELL', 1: 'HOLD', 2: 'BUY'}
            signal = signal_map.get(prediction, 'HOLD')
            
            return signal, probability
        
        except Exception as e:
            logger.error(f"Error in signal prediction: {e}")
            return 'HOLD', 0.5
    
    def batch_predict(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Make predictions for all data points.
        
        Args:
            data: OHLCV DataFrame
        
        Returns:
            DataFrame with predictions and probabilities
        """
        results = []
        
        for i in range(len(data)):
            current_data = data.iloc[:i+1]
            signal, prob = self.predict_signal(current_data)
            
            results.append({
                'timestamp': data.index[i] if hasattr(data.index, '__getitem__') else i,
                'signal': signal,
                'probability': prob
            })
        
        return pd.DataFrame(results)
    
    def train_and_save(self, training_data: pd.DataFrame, target_data: pd.Series,
                      model_name: str = "latest"):
        """
        Train model on provided data and save.
        
        Args:
            training_data: Historical price data
            target_data: Target labels (BUY=2, HOLD=1, SELL=0)
            model_name: Name to save model as
        """
        try:
            # Engineer features
            features = self.feature_engineer.engineer_features(training_data)
            
            if features is None or features.empty:
                logger.error("Could not engineer features for training")
                return False
            
            # Select features
            features_selected = self.feature_selector.select_features(features)
            
            # Train model
            metrics = self.model_trainer.train_model(features_selected, target_data)
            
            # Save model
            self.model_trainer.save_model(model_name)
            
            logger.info(f"Model trained and saved. Metrics: {metrics}")
            return True
        
        except Exception as e:
            logger.error(f"Error training model: {e}")
            return False


class OnlineLearning:
    """
    Online learning for continuous model improvement.
    Retrains model with new data periodically.
    """
    
    def __init__(self, predictor: MLPredictor, retrain_frequency: int = 100):
        """
        Initialize OnlineLearning.
        
        Args:
            predictor: MLPredictor instance
            retrain_frequency: Train every N new samples
        """
        self.predictor = predictor
        self.retrain_frequency = retrain_frequency
        self.sample_buffer = []
        self.label_buffer = []
    
    def record_trade_outcome(self, data: pd.DataFrame, actual_direction: str):
        """
        Record trade outcome for online learning.
        
        Args:
            data: Price data for the trade
            actual_direction: Actual price movement (UP, DOWN)
        """
        # Engineer features
        features = self.predictor.feature_engineer.engineer_features(data)
        
        if features is not None:
            # Store features
            self.sample_buffer.append(features.iloc[-1].values)
            
            # Convert direction to label
            label_map = {'UP': 2, 'DOWN': 0, 'NONE': 1}
            label = label_map.get(actual_direction, 1)
            self.label_buffer.append(label)
        
        # Retrain if buffer is full
        if len(self.sample_buffer) >= self.retrain_frequency:
            self._retrain_model()
    
    def _retrain_model(self):
        """Retrain model with buffered data."""
        try:
            if not self.sample_buffer:
                return
            
            X = pd.DataFrame(self.sample_buffer)
            y = pd.Series(self.label_buffer)
            
            # Train incremental
            self.predictor.model_trainer.continue_training(X, y)
            
            # Save updated model
            self.predictor.model_trainer.save_model("latest")
            
            # Clear buffers
            self.sample_buffer = []
            self.label_buffer = []
            
            logger.info("Model retrained with new data")
        
        except Exception as e:
            logger.error(f"Error in online retraining: {e}")
