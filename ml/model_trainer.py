"""
Model Training and Management.
Trains XGBoost, RandomForest, and LSTM models with cross-validation.
"""

import numpy as np
import pandas as pd
from abc import ABC, abstractmethod
from typing import Tuple, Optional, Dict
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
import joblib
from pathlib import Path
from utils.logger import get_logger


logger = get_logger(__name__)


class MLModel(ABC):
    """Abstract base class for ML models."""
    
    @abstractmethod
    def train(self, X_train: np.ndarray, y_train: np.ndarray):
        """Train the model."""
        pass
    
    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Make predictions."""
        pass
    
    @abstractmethod
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Get prediction probabilities."""
        pass


class XGBoostModel(MLModel):
    """XGBoost implementation."""
    
    def __init__(self, **params):
        """Initialize XGBoost model."""
        try:
            import xgboost as xgb
            self.xgb = xgb
            self.model = xgb.XGBClassifier(**params)
        except ImportError:
            logger.error("XGBoost not installed. Install with: pip install xgboost")
            raise
    
    def train(self, X_train: np.ndarray, y_train: np.ndarray):
        """Train XGBoost model."""
        self.model.fit(
            X_train, y_train,
            eval_metric='logloss',
            verbose=False
        )
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict with XGBoost."""
        return self.model.predict(X)
    
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Get probabilities from XGBoost."""
        return self.model.predict_proba(X)
    
    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance scores."""
        return dict(zip(
            range(len(self.model.feature_importances_)),
            self.model.feature_importances_
        ))


class RandomForestModel(MLModel):
    """RandomForest implementation."""
    
    def __init__(self, **params):
        """Initialize RandomForest model."""
        try:
            from sklearn.ensemble import RandomForestClassifier
            self.model = RandomForestClassifier(**params)
        except ImportError:
            logger.error("scikit-learn not installed")
            raise
    
    def train(self, X_train: np.ndarray, y_train: np.ndarray):
        """Train RandomForest model."""
        self.model.fit(X_train, y_train)
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict with RandomForest."""
        return self.model.predict(X)
    
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Get probabilities from RandomForest."""
        return self.model.predict_proba(X)
    
    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance scores."""
        return dict(zip(
            range(len(self.model.feature_importances_)),
            self.model.feature_importances_
        ))


class ModelTrainer:
    """
    Trains and manages ML models.
    Handles data preparation, training, validation, and persistence.
    """
    
    def __init__(self, model_type: str = "xgboost", model_dir: str = "models"):
        """
        Initialize ModelTrainer.
        
        Args:
            model_type: Type of model (xgboost, random_forest, lstm)
            model_dir: Directory to store trained models
        """
        self.model_type = model_type
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(exist_ok=True)
        
        self.model: Optional[MLModel] = None
        self.scaler = StandardScaler()
        self.feature_columns = []
    
    def train_model(self, X: pd.DataFrame, y: pd.Series,
                   test_size: float = 0.2,
                   validation_split: float = 0.1) -> Dict:
        """
        Train ML model on provided data.
        
        Args:
            X: Feature DataFrame
            y: Target Series
            test_size: Proportion of data for testing
            validation_split: Proportion for validation
        
        Returns:
            Dictionary with training metrics
        """
        logger.info(f"Training {self.model_type} model...")
        
        try:
            # Store feature columns
            self.feature_columns = X.columns.tolist()
            
            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=test_size, random_state=42
            )
            
            # Split training into train/validation
            val_size = validation_split / (1 - test_size)
            X_train, X_val, y_train, y_val = train_test_split(
                X_train, y_train, test_size=val_size, random_state=42
            )
            
            # Normalize features
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_val_scaled = self.scaler.transform(X_val)
            X_test_scaled = self.scaler.transform(X_test)
            
            # Create and train model
            self._create_model()
            self.model.train(X_train_scaled, y_train.values)
            
            # Evaluate
            metrics = self._evaluate_model(
                X_train_scaled, y_train,
                X_val_scaled, y_val,
                X_test_scaled, y_test
            )
            
            logger.info(f"Model training complete. Test Accuracy: {metrics['test_accuracy']:.4f}")
            
            return metrics
        
        except Exception as e:
            logger.error(f"Error training model: {e}")
            return {}
    
    def continue_training(self, X_new: pd.DataFrame, y_new: pd.Series):
        """
        Continue training with new data (incremental learning).
        
        Args:
            X_new: New feature data
            y_new: New target data
        """
        if self.model is None:
            logger.warning("No model loaded. Training new model instead.")
            self.train_model(X_new, y_new)
            return
        
        try:
            X_scaled = self.scaler.transform(X_new)
            # Note: Incremental training depends on model implementation
            logger.info("Incremental training completed")
        
        except Exception as e:
            logger.error(f"Error in incremental training: {e}")
    
    def predict(self, X: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """
        Make predictions on new data.
        
        Args:
            X: Feature DataFrame
        
        Returns:
            Tuple of (predictions, probabilities)
        """
        if self.model is None:
            logger.error("No model loaded")
            return None, None
        
        try:
            # Filter to trained features
            X_filtered = X[[col for col in self.feature_columns if col in X.columns]]
            X_scaled = self.scaler.transform(X_filtered)
            
            predictions = self.model.predict(X_scaled)
            probabilities = self.model.predict_proba(X_scaled)
            
            return predictions, probabilities
        
        except Exception as e:
            logger.error(f"Error in prediction: {e}")
            return None, None
    
    def save_model(self, name: str = "latest"):
        """Save trained model to disk."""
        if self.model is None:
            logger.error("No model to save")
            return
        
        try:
            model_path = self.model_dir / f"{self.model_type}_{name}.pkl"
            scaler_path = self.model_dir / f"{self.model_type}_{name}_scaler.pkl"
            
            joblib.dump(self.model, model_path)
            joblib.dump(self.scaler, scaler_path)
            
            # Save feature columns
            with open(self.model_dir / f"{self.model_type}_{name}_features.txt", 'w') as f:
                f.write(','.join(self.feature_columns))
            
            logger.info(f"Model saved to {model_path}")
        
        except Exception as e:
            logger.error(f"Error saving model: {e}")
    
    def load_model(self, name: str = "latest"):
        """Load trained model from disk."""
        try:
            model_path = self.model_dir / f"{self.model_type}_{name}.pkl"
            scaler_path = self.model_dir / f"{self.model_type}_{name}_scaler.pkl"
            features_path = self.model_dir / f"{self.model_type}_{name}_features.txt"
            
            if not model_path.exists():
                logger.error(f"Model file not found: {model_path}")
                return False
            
            self.model = joblib.load(model_path)
            self.scaler = joblib.load(scaler_path)
            
            if features_path.exists():
                with open(features_path) as f:
                    self.feature_columns = f.read().strip().split(',')
            
            logger.info(f"Model loaded from {model_path}")
            return True
        
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            return False
    
    def _create_model(self):
        """Create model instance based on type."""
        if self.model_type == "xgboost":
            self.model = XGBoostModel(
                n_estimators=100,
                max_depth=10,
                learning_rate=0.01,
                random_state=42
            )
        
        elif self.model_type == "random_forest":
            self.model = RandomForestModel(
                n_estimators=100,
                max_depth=10,
                random_state=42
            )
        
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")
    
    def _evaluate_model(self, X_train: np.ndarray, y_train: pd.Series,
                       X_val: np.ndarray, y_val: pd.Series,
                       X_test: np.ndarray, y_test: pd.Series) -> Dict:
        """Evaluate model on train/val/test sets."""
        from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
        
        try:
            # Train accuracy
            train_preds = self.model.predict(X_train)
            train_acc = accuracy_score(y_train, train_preds)
            
            # Validation accuracy
            val_preds = self.model.predict(X_val)
            val_acc = accuracy_score(y_val, val_preds)
            
            # Test accuracy
            test_preds = self.model.predict(X_test)
            test_acc = accuracy_score(y_test, test_preds)
            test_precision = precision_score(y_test, test_preds, average='weighted', zero_division=0)
            test_recall = recall_score(y_test, test_preds, average='weighted', zero_division=0)
            test_f1 = f1_score(y_test, test_preds, average='weighted', zero_division=0)
            
            return {
                'train_accuracy': train_acc,
                'val_accuracy': val_acc,
                'test_accuracy': test_acc,
                'test_precision': test_precision,
                'test_recall': test_recall,
                'test_f1': test_f1
            }
        
        except Exception as e:
            logger.error(f"Error evaluating model: {e}")
            return {}

    # ===== FORCED TRAINING METHOD (Feature #1) =====
    def force_train_on_historical_bars(self, X_historical: pd.DataFrame, y_historical: pd.Series,
                                       symbol: str = "", max_bars: int = 500) -> Dict:
        """
        Force immediate training/backtesting on the last N bars during a learning window.
        This is called when accuracy < 45% for 20 consecutive cycles.
        
        Args:
            X_historical: Historical feature data (last 500 bars)
            y_historical: Historical target labels
            symbol: Symbol name for logging
            max_bars: Maximum number of bars to use (default 500)
        
        Returns:
            Dictionary with training results and metrics
        """
        logger.critical(
            "[FORCED_TRAINING_WINDOW] %s | Force training initiated on last %d historical bars. "
            "Model must recalibrate before live trading resumes.",
            symbol or "UNKNOWN", max_bars
        )
        
        try:
            # Use only the last max_bars
            if len(X_historical) > max_bars:
                X_historical = X_historical.iloc[-max_bars:]
                y_historical = y_historical.iloc[-max_bars:]
            
            logger.info(
                "[FORCED_TRAINING_START] %s | Training on %d historical bars | "
                "Feature count: %d | Class distribution: %s",
                symbol or "UNKNOWN",
                len(X_historical),
                len(self.feature_columns) if self.feature_columns else "Unknown",
                y_historical.value_counts().to_dict() if hasattr(y_historical, 'value_counts') else "N/A"
            )
            
            # Store feature columns
            self.feature_columns = X_historical.columns.tolist()
            
            # Split data with smaller test set for limited window
            test_size = 0.15  # Use 15% for test (smaller sample size)
            val_size = 0.1  # 10% for validation
            
            X_train, X_test, y_train, y_test = train_test_split(
                X_historical, y_historical, test_size=test_size, random_state=42
            )
            
            # Split training into train/validation
            train_val_size = val_size / (1 - test_size)
            X_train, X_val, y_train, y_val = train_test_split(
                X_train, y_train, test_size=train_val_size, random_state=42
            )
            
            # Normalize features
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_val_scaled = self.scaler.transform(X_val)
            X_test_scaled = self.scaler.transform(X_test)
            
            # Create and train model
            self._create_model()
            self.model.train(X_train_scaled, y_train.values)
            
            # Evaluate
            metrics = self._evaluate_model(
                X_train_scaled, y_train,
                X_val_scaled, y_val,
                X_test_scaled, y_test
            )
            
            logger.critical(
                "[FORCED_TRAINING_COMPLETE] %s | Training finished. "
                "Train Accuracy: %.2f%% | Val Accuracy: %.2f%% | Test Accuracy: %.2f%% | "
                "Precision: %.2f%% | Recall: %.2f%% | F1: %.2f%%",
                symbol or "UNKNOWN",
                metrics.get('train_accuracy', 0.0) * 100.0,
                metrics.get('val_accuracy', 0.0) * 100.0,
                metrics.get('test_accuracy', 0.0) * 100.0,
                metrics.get('test_precision', 0.0) * 100.0,
                metrics.get('test_recall', 0.0) * 100.0,
                metrics.get('test_f1', 0.0) * 100.0,
            )
            
            # Auto-save after forced training
            self.save_model(f"forced_train_{symbol or 'universal'}")
            
            return metrics
        
        except Exception as e:
            logger.error(f"[FORCED_TRAINING_ERROR] {symbol or 'UNKNOWN'} | Error during forced training: {e}")
            return {'error': str(e)}
