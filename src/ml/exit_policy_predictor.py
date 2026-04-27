"""
Exit Policy Intelligence & Confidence-Gated Learning System
Predicts optimal ExitPolicy based on market state features using historical data.
"""

import json
import os
import logging
import numpy as np
import pickle
from typing import Dict, Any, Tuple, Optional, List
from datetime import datetime
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from dataclasses import asdict

from src.models import ExitPolicy

# Configure logging
logger = logging.getLogger(__name__)

class ExitPolicyPredictor:
    """
    Predicts the optimal ExitPolicy for a given market state.
    Uses historical exit data to learn which policy yields the highest expectancy.
    """
    
    MODEL_FILE = "exit_policy_model.pkl"
    HISTORY_FILE = "exit_history.json"
    
    def __init__(self, data_dir: str = "."):
        self.data_dir = data_dir
        self.model_path = os.path.join(data_dir, self.MODEL_FILE)
        self.history_path = os.path.join(data_dir, self.HISTORY_FILE)
        
        self.model = None
        self.scaler = StandardScaler()
        self.is_trained = False
        self.min_training_samples = 20
        self.confidence_threshold = 0.65  # Configurable threshold
        
        # Policy Mapping
        self.policies = [
            ExitPolicy.STANDARD, 
            ExitPolicy.SCALP, 
            ExitPolicy.TREND_FOLLOW, 
            ExitPolicy.MEAN_REVERT
        ]
        self.policy_map = {p.value: i for i, p in enumerate(self.policies)}
        self.reverse_policy_map = {i: p for i, p in enumerate(self.policies)}
        
        # Metrics
        self.metrics = {
            'total_predictions': 0,
            'high_confidence_predictions': 0,
            'avg_confidence': 0.0,
            'avg_regret': 0.0
        }
        
        self.load_model()

    def get_features(self, market_data: Any, technical_signals: List[Any], confidence: float) -> np.ndarray:
        """
        Extract features from market state for prediction.
        Features: [Volatility(ATR), TrendStrength(ADX), Spread, Confidence, RSI]
        """
        # Placeholder feature extraction - adaptable to actual data availability
        # Assuming technical_signals contains indicators or we calculate them here?
        # For now, let's use what we can passed in or default to 0
        
        # Extract features (adjust based on available data structures)
        try:
            # Try to get ATR/ADX/RSI from technical signals if available
            atr = 0.0
            adx = 0.0
            rsi = 50.0
            spread = 0.0001 # Default
            
            # Simple feature vector: [volatility_proxy, trend_strength, spread, confidence]
            # If actual values unavailable, use reasonable defaults or passed kwargs
            # This requires coordination with SignalCombiner to pass rich data
            
            # Use passed values if available in dict
            if isinstance(market_data, dict):
                atr = market_data.get('atr', 0.0)
                adx = market_data.get('adx', 0.0)
                rsi = market_data.get('rsi', 50.0)
                spread = market_data.get('spread', 0.0001)
                
            features = np.array([atr, adx, rsi, spread, confidence]).reshape(1, -1)
            return features
            
        except Exception as e:
            logger.error(f"Error extracting features: {e}")
            return np.zeros((1, 5))

    def predict(self, feature_vector: np.ndarray) -> Tuple[ExitPolicy, float]:
        """
        Predict optimal policy and confidence.
        Returns (PredictedPolicy, ConfidenceScore)
        """
        if not self.is_trained or self.model is None:
            return ExitPolicy.STANDARD, 0.0
            
        try:
            # Scale features
            scaled_features = self.scaler.transform(feature_vector)
            
            # Predict probabilities
            probs = self.model.predict_proba(scaled_features)[0]
            
            # Get best policy
            best_idx = np.argmax(probs)
            confidence = probs[best_idx]
            predicted_policy = self.reverse_policy_map.get(best_idx, ExitPolicy.STANDARD)
            
            # Update diagnostic metrics
            self.metrics['total_predictions'] += 1
            if confidence >= self.confidence_threshold:
                self.metrics['high_confidence_predictions'] += 1
            
            # Running average of confidence
            n = self.metrics['total_predictions']
            self.metrics['avg_confidence'] = ((self.metrics['avg_confidence'] * (n-1)) + confidence) / n
            
            return predicted_policy, confidence
            
        except Exception as e:
            logger.error(f"Error making prediction: {e}")
            return ExitPolicy.STANDARD, 0.0

    def train(self) -> bool:
        """
        Train the model using historical exit data.
        Returns True if training successful.
        """
        if not os.path.exists(self.history_path):
            logger.warning("No exit history found for training.")
            return False
            
        try:
            with open(self.history_path, 'r') as f:
                history = json.load(f)
                
            if len(history) < self.min_training_samples:
                logger.info(f"Insufficient history for training ({len(history)}/{self.min_training_samples})")
                return False
                
            X = []
            y = []
            
            # Prepare dataset
            for record in history:
                # Skip administrative exits or those without feature snapshots
                if record.get('exit_reason', '') not in ['tp_hit', 'sl_hit', 'trailing_stop_hit', 'partial_tp']:
                    continue
                    
                # Reconstruct Features
                # Features are now stored in entry_features by PositionManager
                features = record.get('entry_features', [])
                if not features or len(features) != 5:
                    continue
                    
                X.append(features)
                
                # Determine "Best Policy" label for this trade (Counterfactual Analysis)
                best_policy = self._determine_optimal_policy(record)
                y.append(self.policy_map.get(best_policy.value, 0))
                
            if len(X) < self.min_training_samples:
                return False
                
            X = np.array(X)
            y = np.array(y)
            
            # Fit scaler
            self.scaler.fit(X)
            X_scaled = self.scaler.transform(X)
            
            # Train model
            self.model = GradientBoostingClassifier(n_estimators=100, learning_rate=0.1, max_depth=3)
            self.model.fit(X_scaled, y)
            
            self.is_trained = True
            self.save_model()
            logger.info(f"ExitPolicyPredictor trained on {len(X)} records")
            return True
            
        except Exception as e:
            logger.error(f"Training failed: {e}")
            return False

    def _calculate_policy_outcomes(self, record: Dict) -> Dict[ExitPolicy, float]:
        """
        Calculate realized R-multiples for each policy type based on trade outcome.
        Uses MFE/MAE to simulate alternative outcomes.
        """
        # Get trade metrics
        mfe = record.get('mfe', 0.0)
        mae = record.get('mae', 0.0)
        realized_r = record.get('r_multiple', 0.0)
        
        # Base outcome map
        outcomes = {p: 0.0 for p in self.policies}
        outcomes[ExitPolicy.STANDARD] = realized_r

        # SCALP Simulation (Target: ~1R, tight stop)
        # Success if MFE > 1.5 * Risk or significant rapid gain
        # Failure if MAE specific scalping stop (tighter than standard)
        if mfe > abs(mae) * 2.0: 
             outcomes[ExitPolicy.SCALP] = 1.0 # Capped at 1R for scalp
        elif abs(mae) > mfe:
             outcomes[ExitPolicy.SCALP] = -0.5 # Tighter stop loss assumed
             
        # TREND Simulation (Target: >3R, loose stop)
        # Success if MFE was huge
        if mfe > abs(mae) * 4.0:
            outcomes[ExitPolicy.TREND_FOLLOW] = 3.5 # Capture large trend
        elif mfe > abs(mae) * 2.5:
            outcomes[ExitPolicy.TREND_FOLLOW] = 1.5 # Moderate trend
        else:
            outcomes[ExitPolicy.TREND_FOLLOW] = -1.0 # Stopped out trying to hold
            
        # MEAN REVERT Simulation (Target: ~1.5R)
        if mfe > abs(mae) * 2.5:
            outcomes[ExitPolicy.MEAN_REVERT] = 1.8
        elif mfe > abs(mae) * 1.2:
            outcomes[ExitPolicy.MEAN_REVERT] = 0.5 # Scratch/Small win
        else:
            outcomes[ExitPolicy.MEAN_REVERT] = -0.8

        return outcomes

    def _determine_optimal_policy(self, record: Dict) -> ExitPolicy:
        """
        Determine which policy would have yielded the best R-multiple.
        """
        outcomes = self._calculate_policy_outcomes(record)
        
        # Handle case where keys might be strings if loaded from JSON without enum conversion
        # Ensure we return ExitPolicy enum
        best_policy_key = max(outcomes, key=outcomes.get)
        
        if isinstance(best_policy_key, ExitPolicy):
            return best_policy_key
        
        # Fallback if somehow keys are strings (unlikely given _calculate logic but safe)
        try:
            return ExitPolicy(best_policy_key)
        except:
            return ExitPolicy.STANDARD

    def calculate_regret(self, record: Dict) -> float:
        """
        Calculate regret: (Best Potential R - Realized R)
        """
        outcomes = self._calculate_policy_outcomes(record)
        realized_r = record.get('r_multiple', 0.0)
        
        best_potential_r = max(outcomes.values())
        regret = max(0.0, best_potential_r - realized_r)
        
        # Update metric
        n = self.metrics['total_predictions'] if self.metrics['total_predictions'] > 0 else 1
        self.metrics['avg_regret'] = ((self.metrics['avg_regret'] * (n-1)) + regret) / n
        
        return regret

    def save_model(self):
        """Persist model and scaling"""
        if self.model is None: return
        try:
            with open(self.model_path, 'wb') as f:
                pickle.dump({
                    'model': self.model,
                    'scaler': self.scaler,
                    'metrics': self.metrics
                }, f)
        except Exception as e:
            logger.error(f"Failed to save model: {e}")

    def load_model(self):
        """Load model from disk"""
        if not os.path.exists(self.model_path):
            return
        try:
            with open(self.model_path, 'rb') as f:
                data = pickle.load(f)
                self.model = data.get('model')
                self.scaler = data.get('scaler')
                self.metrics = data.get('metrics', self.metrics)
                self.is_trained = True
                logger.info("Loaded ExitPolicyPredictor model")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")

