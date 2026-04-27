"""
Main Trading Engine.
Orchestrates strategies, risk management, execution, and monitoring.
"""

import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime, time
import pandas as pd

from utils.logger import get_logger
from utils.config import ConfigManager, TradingConfig
from core.strategy_manager import StrategyManager, Strategy
from core.execution import ExecutionEngine, Broker, OrderRequest
from core.risk_manager import RiskManager, PositionSizingMethod
from core.portfolio import Portfolio, Trade, PortfolioMetrics
from core.data_handler import DataHandler


logger = get_logger(__name__)


@dataclass
class TradingState:
    """State of the trading engine."""
    is_running: bool = False
    is_connected: bool = False
    daily_loss: float = 0.0
    last_update: Optional[datetime] = None
    trades_today: int = 0


class TradingEngine:
    """
    Main trading engine orchestrating all components.
    Combines strategy generation, risk management, and execution.
    """
    
    def __init__(self, config: TradingConfig, broker: Broker, data_handler: DataHandler):
        """
        Initialize TradingEngine.
        
        Args:
            config: Trading configuration
            broker: Broker connection
            data_handler: Data handler for market data
        """
        self.config = config
        self.broker = broker
        self.data_handler = data_handler
        
        # Core components
        self.strategy_manager = StrategyManager()
        self.execution_engine = ExecutionEngine(broker)
        self.risk_manager = RiskManager(config.data.pairs[0] if config.data.pairs else 0,
                                       config.risk)
        self.portfolio = Portfolio(10000.0, config.risk)  # TODO: Get actual capital
        
        # State
        self.state = TradingState()
        self.market_data: Dict[str, pd.DataFrame] = {}
        self.symbol_atr: Dict[str, float] = {}
    
    async def initialize(self) -> bool:
        """
        Initialize the trading engine.
        Connects to broker and loads data.
        
        Returns:
            True if successful
        """
        logger.info("[ENGINE] Initializing trading engine...")
        
        try:
            # Connect to broker
            if not await self.broker.connect():
                logger.error("[ENGINE] Failed to connect to broker")
                return False
            
            self.state.is_connected = True
            logger.info("[ENGINE] Connected to broker")
            
            # Load initial market data
            await self._load_market_data()
            
            logger.info("[ENGINE] Engine initialized successfully")
            return True
        
        except Exception as e:
            logger.error(f"[ENGINE] Initialization error: {e}")
            return False
    
    async def run(self):
        """Main trading loop."""
        self.state.is_running = True
        logger.info("[ENGINE] Starting trading loop...")
        
        while self.state.is_running:
            try:
                # Check if trading is allowed
                if not self._check_trading_allowed():
                    await asyncio.sleep(60)  # Wait before retrying
                    continue
                
                # Update market data
                await self._load_market_data()
                
                # Generate signals
                signals = self.strategy_manager.generate_signals(self.market_data)
                
                # Process signals
                await self._process_signals(signals)
                
                # Update positions
                await self._update_positions()
                
                # Monitor risk
                self._monitor_risk()
                
                # Sleep before next iteration
                await asyncio.sleep(60)  # Every minute
            
            except Exception as e:
                logger.error(f"[ENGINE] Error in trading loop: {e}")
                await asyncio.sleep(60)
    
    def add_strategy(self, strategy: Strategy, weight: float = 1.0) -> bool:
        """Add a strategy to the engine."""
        return self.strategy_manager.register_strategy(strategy, weight)
    
    async def _load_market_data(self):
        """Load current market data for all pairs."""
        try:
            for symbol in self.config.data.pairs:
                try:
                    # Get historical data
                    data = self.data_handler.get_historical_data(
                        symbol,
                        start=datetime.now() - pd.Timedelta(days=100),
                        end=datetime.now(),
                        granularity=self.config.data.granularity
                    )
                    
                    if data is not None and len(data) > 0:
                        self.market_data[symbol] = data
                        
                        # Calculate ATR
                        self.symbol_atr[symbol] = self._calculate_atr(data)
                
                except Exception as e:
                    logger.error(f"Error loading data for {symbol}: {e}")
        
        except Exception as e:
            logger.error(f"Error in market data loading: {e}")
    
    async def _process_signals(self, signals: Dict):
        """Process strategy signals and submit orders."""
        try:
            # Aggregate signals per symbol
            aggregated = self.strategy_manager.aggregate_signals(signals)
            
            for symbol, signal in aggregated.items():
                if signal.value == "HOLD":
                    continue
                
                # Check if we should trade this symbol
                if symbol not in self.market_data:
                    continue
                
                # Get current price
                data = self.market_data[symbol]
                current_price = data['close'].iloc[-1]
                
                # Calculate position size
                try:
                    pos_size = self.risk_manager.calculate_position_size(
                        symbol,
                        current_price,
                        current_price - 0.005,  # Estimate SL for sizing
                        current_atr=self.symbol_atr.get(symbol)
                    )
                except Exception as e:
                    logger.error(f"Error calculating position size: {e}")
                    continue
                
                # Calculate stops and targets
                risk_levels = self.risk_manager.calculate_stops_and_targets(
                    current_price,
                    signal.value,
                    current_atr=self.symbol_atr.get(symbol)
                )
                
                # Submit order
                direction = signal.value
                order_id = await self.execution_engine.submit_market_order(
                    symbol=symbol,
                    direction=direction,
                    quantity=pos_size.quantity,
                    stop_loss=risk_levels.stop_loss,
                    take_profit=risk_levels.take_profit,
                    comment=f"Signal from {signal.strategy_name if hasattr(signal, 'strategy_name') else 'engine'}"
                )
                
                if order_id:
                    logger.info(f"[ENGINE] Order submitted: {order_id}")
        
        except Exception as e:
            logger.error(f"[ENGINE] Error processing signals: {e}")
    
    async def _update_positions(self):
        """Update open positions with current market data."""
        try:
            for symbol, data in self.market_data.items():
                if len(data) == 0:
                    continue
                
                current_price = data['close'].iloc[-1]
                
                # Update portfolio positions
                for trade_id, trade in list(self.portfolio.trades.items()):
                    if trade.symbol == symbol:
                        self.portfolio.update_position(trade_id, current_price)
                        
                        # Check stop loss
                        if trade.direction == "BUY" and current_price <= trade.stop_loss:
                            await self.execution_engine.close_position(
                                trade_id,
                                exit_reason="Stop loss hit"
                            )
                            self.portfolio.close_position(trade_id, current_price, "SL")
                        
                        elif trade.direction == "SELL" and current_price >= trade.stop_loss:
                            await self.execution_engine.close_position(
                                trade_id,
                                exit_reason="Stop loss hit"
                            )
                            self.portfolio.close_position(trade_id, current_price, "SL")
                        
                        # Check take profit
                        elif trade.direction == "BUY" and current_price >= trade.take_profit:
                            await self.execution_engine.close_position(
                                trade_id,
                                exit_reason="Take profit hit"
                            )
                            self.portfolio.close_position(trade_id, current_price, "TP")
                        
                        elif trade.direction == "SELL" and current_price <= trade.take_profit:
                            await self.execution_engine.close_position(
                                trade_id,
                                exit_reason="Take profit hit"
                            )
                            self.portfolio.close_position(trade_id, current_price, "TP")
        
        except Exception as e:
            logger.error(f"[ENGINE] Error updating positions: {e}")
    
    def _monitor_risk(self):
        """Monitor portfolio risk and apply safeguards."""
        try:
            metrics = self.portfolio.get_metrics()
            
            # Check drawdown limit
            if not self.risk_manager.check_drawdown_limit(self.portfolio.current_equity):
                logger.critical("[RISK] Max drawdown exceeded. Stopping trading.")
                self.state.is_running = False
                return
            
            # Check daily loss limit
            if not self.risk_manager.check_daily_loss_limit(self.state.daily_loss):
                logger.warning("[RISK] Daily loss limit exceeded. Stopping trading.")
                self.state.is_running = False
                return
            
            # Check margin
            if metrics.margin_utilization > 80:
                logger.warning(f"[RISK] High margin utilization: {metrics.margin_utilization:.1f}%")
            
            # Log metrics
            logger.info("[METRICS]",
                       equity=metrics.total_equity,
                       margin_util=metrics.margin_utilization,
                       open_trades=metrics.open_trades,
                       pnl=metrics.total_profit_loss)
        
        except Exception as e:
            logger.error(f"[ENGINE] Error monitoring risk: {e}")
    
    def _check_trading_allowed(self) -> bool:
        """Check if trading is allowed (non-stop conditions)."""
        if not self.state.is_connected:
            logger.warning("[ENGINE] Broker not connected")
            return False
        
        # Check trading hours (if configured)
        current_time = datetime.now().time()
        
        # Default: trade 24/7 if no session config
        return True
    
    def _calculate_atr(self, data: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range."""
        if len(data) < period:
            return 0.0
        
        high = data['high']
        low = data['low']
        close = data['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr.iloc[-1] if len(atr) > 0 else 0.0
    
    def get_portfolio_metrics(self) -> PortfolioMetrics:
        """Get current portfolio metrics."""
        return self.portfolio.get_metrics()
    
    async def shutdown(self):
        """Shutdown the trading engine."""
        logger.info("[ENGINE] Shutting down...")
        
        self.state.is_running = False
        
        # Close all positions
        for trade_id in list(self.portfolio.trades.keys()):
            current_price = 100.0  # TODO: Get actual price
            await self.execution_engine.close_position(trade_id)
            self.portfolio.close_position(trade_id, current_price, "Shutdown")
        
        # Disconnect from broker
        if self.state.is_connected:
            await self.broker.disconnect()
        
        logger.info("[ENGINE] Shutdown complete")
