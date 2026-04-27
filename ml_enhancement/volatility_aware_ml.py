"""
ML Model Enhancement for Extreme Market Conditions
═══════════════════════════════════════════════════════════════
Trains separate ML models specifically for high-volatility and 
downtrend scenarios to improve signal accuracy under stress.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, List, Tuple
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
import joblib
from pathlib import Path
import json


@dataclass
class ModelPerformance:
    """Track model performance metrics."""
    model_name: str
    scenario: str
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    buy_accuracy: float
    sell_accuracy: float
    hold_accuracy: float
    confidence_threshold: float = 0.65


class VolatilityAwareMLTrainer:
    """
    Train ML models that are aware of different market regimes.
    Separate models for normal, high-volatility, and downtrend conditions.
    """

    def __init__(self, seed: int = 42):
        np.random.seed(seed)
        self.seed = seed
        self.models = {}
        self.scalers = {}
        self.performance_metrics = []

    def create_synthetic_training_data(
        self,
        scenario: str = 'normal',
        num_samples: int = 1000,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Create synthetic training data for different market conditions.
        
        Args:
            scenario: 'normal', 'high_volatility', 'downtrend'
            num_samples: Number of training samples
            
        Returns:
            X features, y labels
        """
        features = []
        labels = []
        
        for _ in range(num_samples):
            # Generate synthetic market data
            if scenario == 'high_volatility':
                # High volatility: wild swings, noisy signals
                rsi = np.random.uniform(20, 80)
                macd = np.random.normal(0, 2.0)
                bb_position = np.random.uniform(0, 1)
                atr = np.random.uniform(40, 150)  # High ATR
                volatility = np.random.uniform(60, 150)
                momentum = np.random.normal(0, 3.0)
                
                # In high volatility: reversals more likely
                if rsi < 30 and volatile_bounce():
                    label = 1  # BUY (reversal)
                elif rsi > 70 and volatile_bounce():
                    label = -1  # SELL (reversal)
                else:
                    label = 0  # HOLD
                    
            elif scenario == 'downtrend':
                # Downtrend: trends are strong, reversals rare
                rsi = np.random.uniform(15, 60)  # Biased low
                macd = np.random.normal(-1.0, 1.5)  # Biased negative
                bb_position = np.random.uniform(0, 0.7)  # Biased low
                atr = np.random.uniform(20, 80)
                volatility = np.random.uniform(20, 60)
                momentum = np.random.normal(-1.0, 1.5)  # Biased negative
                
                # In downtrend: shorts more profitable
                if momentum < -0.5 or rsi < 40:
                    label = -1  # SELL (follow trend)
                elif rsi > 65 and macd > 0:
                    label = 1  # BUY (possible bounce)
                else:
                    label = 0  # HOLD
                    
            else:  # 'normal'
                # Normal conditions: balanced signals
                rsi = np.random.uniform(30, 70)
                macd = np.random.normal(0, 1.0)
                bb_position = np.random.uniform(0, 1)
                atr = np.random.uniform(15, 50)
                volatility = np.random.uniform(15, 40)
                momentum = np.random.normal(0, 1.0)
            
            # Additional features
            volume_profile = np.random.uniform(0, 1)
            price_position = np.random.uniform(0, 1)
            trend_strength = np.abs(momentum)
            
            # Feature vector
            feature_vector = [
                rsi, macd, bb_position, atr, volatility, momentum,
                volume_profile, price_position, trend_strength
            ]
            
            features.append(feature_vector)
            labels.append(label)
        
        X = np.array(features)
        y = np.array(labels)
        
        return X, y

    def train_regime_models(self):
        """Train separate models for different market regimes."""
        
        print("\n" + "=" * 70)
        print("TRAINING REGIME-SPECIFIC ML MODELS")
        print("=" * 70)
        
        scenarios = ['normal', 'high_volatility', 'downtrend']
        
        for scenario in scenarios:
            print(f"\n📊 Training model for {scenario.upper()} regime...")
            
            # Generate training data
            X_train, y_train = self.create_synthetic_training_data(
                scenario=scenario,
                num_samples=2000
            )
            
            # Normalize features
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X_train)
            
            # Train ensemble model
            # Use GradientBoosting for better handling of non-linear patterns
            model = GradientBoostingClassifier(
                n_estimators=200,  # More trees for robustness
                learning_rate=0.01,  # Lower learning rate
                max_depth=8,
                min_samples_split=5,
                min_samples_leaf=2,
                subsample=0.8,
                random_state=self.seed
            )
            
            model.fit(X_scaled, y_train)
            
            # Evaluate
            train_score = model.score(X_scaled, y_train)
            
            # Detailed accuracy per class
            predictions = model.predict(X_scaled)
            buy_accuracy = np.mean(predictions[y_train == 1] == 1) if np.sum(y_train == 1) > 0 else 0
            sell_accuracy = np.mean(predictions[y_train == -1] == -1) if np.sum(y_train == -1) > 0 else 0
            hold_accuracy = np.mean(predictions[y_train == 0] == 0) if np.sum(y_train == 0) > 0 else 0
            
            # Store model and scaler
            self.models[scenario] = model
            self.scalers[scenario] = scaler
            
            # Log performance
            perf = ModelPerformance(
                model_name=f'GradientBoosting_{scenario}',
                scenario=scenario,
                accuracy=train_score,
                precision=0.0,  # Placeholder
                recall=0.0,  # Placeholder
                f1_score=0.0,  # Placeholder
                buy_accuracy=buy_accuracy,
                sell_accuracy=sell_accuracy,
                hold_accuracy=hold_accuracy,
            )
            self.performance_metrics.append(perf)
            
            print(f"  ✓ Model trained: {scenario}")
            print(f"    Accuracy: {train_score:.1%}")
            print(f"    Buy Accuracy: {buy_accuracy:.1%}")
            print(f"    Sell Accuracy: {sell_accuracy:.1%}")
            print(f"    Hold Accuracy: {hold_accuracy:.1%}")

    def predict_signal(
        self,
        features: np.ndarray,
        volatility_regime: str,
        confidence_threshold: float = 0.60,
    ) -> Tuple[int, float]:
        """
        Predict signal using regime-appropriate model.
        
        Args:
            features: Feature vector
            volatility_regime: Current market regime
            confidence_threshold: Minimum confidence for trade signal
            
        Returns:
            (signal: -1/0/1, confidence: 0-1)
        """
        if volatility_regime not in self.models:
            volatility_regime = 'normal'
        
        model = self.models[volatility_regime]
        scaler = self.scalers[volatility_regime]
        
        # Preprocess features
        X = np.array(features).reshape(1, -1)
        X_scaled = scaler.transform(X)
        
        # Get prediction
        prediction = model.predict(X_scaled)[0]
        
        # Get confidence (probability of predicted class)
        probabilities = model.predict_proba(X_scaled)[0]
        
        # Map to class indices (-1, 0, 1) → (0, 1, 2)
        class_to_idx = {-1: 0, 0: 1, 1: 2}
        pred_idx = class_to_idx.get(prediction, 1)
        confidence = probabilities[pred_idx]
        
        # Apply confidence threshold
        if confidence < confidence_threshold:
            return 0, confidence  # Return HOLD if low confidence
        
        return int(prediction), confidence

    def save_models(self, output_dir: str = 'ml_models'):
        """Save trained models to disk."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        for scenario, model in self.models.items():
            model_path = output_path / f"model_{scenario}.joblib"
            scaler_path = output_path / f"scaler_{scenario}.joblib"
            
            joblib.dump(model, model_path)
            joblib.dump(self.scalers[scenario], scaler_path)
        
        print(f"\n✅ Models saved to {output_dir}")

    def export_performance_report(self, output_path: str = 'ml_models/performance.json'):
        """Export model performance metrics."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        report = {
            'timestamp': str(pd.Timestamp.now()),
            'models_trained': list(self.models.keys()),
            'performance_metrics': [
                {
                    'model': m.model_name,
                    'scenario': m.scenario,
                    'accuracy': float(m.accuracy),
                    'buy_accuracy': float(m.buy_accuracy),
                    'sell_accuracy': float(m.sell_accuracy),
                    'hold_accuracy': float(m.hold_accuracy),
                }
                for m in self.performance_metrics
            ]
        }
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"✅ Performance report saved to {output_path}")


def volatile_bounce() -> bool:
    """Helper function for synthetic data generation."""
    return np.random.random() < 0.3


if __name__ == "__main__":
    # Train models
    trainer = VolatilityAwareMLTrainer()
    trainer.train_regime_models()
    trainer.save_models('ml_models_improved')
    trainer.export_performance_report('ml_models_improved/performance.json')
    
    print("\n" + "=" * 70)
    print("✅ REGIME-SPECIFIC ML MODELS TRAINED AND SAVED")
    print("=" * 70)
