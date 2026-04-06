"""
FastAPI server for RL model inference with health checks.
"""
import os
import time
import asyncio
import logging
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import uvicorn
import torch
import numpy as np

from ..health_check import check_inference_health, get_metrics, inference_requests
from ..agents.dqn_agent import DQNAgent
from ..agents.ppo_agent import PPOAgent
from ..strategies.registry import StrategyRegistry

logger = logging.getLogger(__name__)

class InferenceRequest(BaseModel):
    """Request model for inference."""
    state: List[float]
    strategy_id: Optional[str] = None
    agent_type: str = "dqn"

class InferenceResponse(BaseModel):
    """Response model for inference."""
    action: int
    confidence: float
    strategy_id: str
    processing_time_ms: float

class ModelManager:
    """Manages loaded models for inference."""
    
    def __init__(self):
        self.loaded_models: Dict[str, Any] = {}
        self.strategy_registry = StrategyRegistry()
        self.model_path = os.getenv('MODEL_PATH', '/app/models')
        
    async def load_models(self):
        """Load available models at startup."""
        try:
            strategies = self.strategy_registry.list_strategies()
            for strategy in strategies:
                await self.load_model(strategy.strategy_id)
            logger.info(f"Loaded {len(self.loaded_models)} models")
        except Exception as e:
            logger.error(f"Error loading models: {e}")
    
    async def load_model(self, strategy_id: str) -> bool:
        """Load a specific model."""
        try:
            strategy = self.strategy_registry.get_strategy(strategy_id)
            if not strategy:
                return False
            
            # Load model based on agent type
            if strategy.agent_type.lower() == 'dqn':
                agent = DQNAgent.load_from_checkpoint(strategy.model_path)
            elif strategy.agent_type.lower() == 'ppo':
                agent = PPOAgent.load_from_checkpoint(strategy.model_path)
            else:
                logger.error(f"Unknown agent type: {strategy.agent_type}")
                return False
            
            agent.eval()  # Set to evaluation mode
            self.loaded_models[strategy_id] = {
                'agent': agent,
                'strategy': strategy,
                'loaded_at': time.time()
            }
            
            logger.info(f"Loaded model {strategy_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error loading model {strategy_id}: {e}")
            return False
    
    def get_model(self, strategy_id: str) -> Optional[Any]:
        """Get a loaded model."""
        return self.loaded_models.get(strategy_id)
    
    def get_default_model(self) -> Optional[Any]:
        """Get the default model (most recent)."""
        if not self.loaded_models:
            return None
        
        # Return the most recently loaded model
        latest_model = max(
            self.loaded_models.values(),
            key=lambda x: x['loaded_at']
        )
        return latest_model

# Global model manager
model_manager = ModelManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting RL inference server...")
    await model_manager.load_models()
    yield
    # Shutdown
    logger.info("Shutting down RL inference server...")

# Create FastAPI app
app = FastAPI(
    title="RL Trading Inference API",
    description="Reinforcement Learning model inference for trading decisions",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    health_data = check_inference_health()
    
    if health_data['status'] != 'healthy':
        raise HTTPException(status_code=503, detail=health_data)
    
    return health_data

@app.get("/ready")
async def readiness_check():
    """Readiness check endpoint."""
    if not model_manager.loaded_models:
        raise HTTPException(
            status_code=503, 
            detail="No models loaded"
        )
    
    return {
        "status": "ready",
        "loaded_models": len(model_manager.loaded_models),
        "available_strategies": list(model_manager.loaded_models.keys())
    }

@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus metrics endpoint."""
    return get_metrics()

@app.post("/predict", response_model=InferenceResponse)
async def predict(request: InferenceRequest, background_tasks: BackgroundTasks):
    """Make trading decision prediction."""
    start_time = time.time()
    
    # Increment request counter
    inference_requests.inc()
    
    try:
        # Get model
        if request.strategy_id:
            model_info = model_manager.get_model(request.strategy_id)
            if not model_info:
                raise HTTPException(
                    status_code=404,
                    detail=f"Strategy {request.strategy_id} not found"
                )
        else:
            model_info = model_manager.get_default_model()
            if not model_info:
                raise HTTPException(
                    status_code=503,
                    detail="No models available"
                )
        
        # Prepare state
        state = np.array(request.state, dtype=np.float32)
        if len(state.shape) == 1:
            state = state.reshape(1, -1)
        
        # Make prediction
        agent = model_info['agent']
        with torch.no_grad():
            action = agent.select_action(state, training=False)
            
            # Get confidence (if available)
            confidence = 1.0
            if hasattr(agent, 'get_action_confidence'):
                confidence = agent.get_action_confidence(state, action)
        
        processing_time = (time.time() - start_time) * 1000
        
        return InferenceResponse(
            action=int(action),
            confidence=float(confidence),
            strategy_id=model_info['strategy'].strategy_id,
            processing_time_ms=round(processing_time, 2)
        )
        
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/models")
async def list_models():
    """List available models."""
    models = []
    for strategy_id, model_info in model_manager.loaded_models.items():
        strategy = model_info['strategy']
        models.append({
            'strategy_id': strategy_id,
            'agent_type': strategy.agent_type,
            'loaded_at': model_info['loaded_at'],
            'performance': strategy.performance_metrics.__dict__ if strategy.performance_metrics else None
        })
    
    return {'models': models}

@app.post("/models/{strategy_id}/reload")
async def reload_model(strategy_id: str):
    """Reload a specific model."""
    success = await model_manager.load_model(strategy_id)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Failed to reload strategy {strategy_id}"
        )
    
    return {'status': 'reloaded', 'strategy_id': strategy_id}

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run server
    port = int(os.getenv('PORT', 8080))
    workers = int(os.getenv('INFERENCE_WORKERS', 1))
    
    uvicorn.run(
        "src.rl.inference.server:app",
        host="0.0.0.0",
        port=port,
        workers=workers,
        log_level="info"
    )