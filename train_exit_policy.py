"""
Script to train the Exit Policy Predictor using historical exit data.
"""
import logging
import sys
import os

# Add src to path
sys.path.append(os.getcwd())

from src.ml.exit_policy_predictor import ExitPolicyPredictor
from src.logging_config import setup_logging

def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    
    logger.info("Starting Exit Policy Predictor training...")
    
    predictor = ExitPolicyPredictor()
    
    if not os.path.exists(predictor.history_path):
        logger.error(f"History file not found at {predictor.history_path}")
        logger.info("Cannot train without exit history.")
        return
        
    logger.info(f"Loading history from {predictor.history_path}...")
    success = predictor.train()
    
    if success:
        logger.info("Training successful!")
        logger.info(f"Model saved to {predictor.model_path}")
        
        # Display some metrics if available
        logger.info("Model Metrics:")
        logger.info(f"  Total Predictions: {predictor.metrics['total_predictions']}")
        logger.info(f"  Avg Confidence: {predictor.metrics['avg_confidence']:.2f}")
        logger.info(f"  Avg Regret: {predictor.metrics['avg_regret']:.2f}")
        
    else:
        logger.error("Training failed. Check logs for details (likely insufficient data).")

if __name__ == "__main__":
    main()
