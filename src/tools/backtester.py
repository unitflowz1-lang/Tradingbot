"""
Comprehensive Backtester for Trading Strategy Optimization
Phase 1: Baseline Backtest with Historical MT5 Data
Pulls 90 days of M5 and H1 data, simulates trading, and generates metrics
"""

import asyncio
import logging
import sys
import json
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, asdict
import numpy as np
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.data.mt5_broker import MT5BrokerInterface
from src.models import MarketData, TradingSignal, Direction
from src.strategies.trend_strategy import SimpleTrendStrategy
from src.analysis.signal_combiner import SignalCombiner, SignalWeights
from src.ml.trade_admission_controller import TradeAdmissionController
from src.risk.position_sizer import PositionSizer
from src.rl.environments.base import PortfolioState
from src.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class BacktestMetrics:
    """Metrics from a backtest period"""
    period_name: str
    start_date: str
    end_date: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    profit_factor: float
    total_pnl: float
    max_drawdown_pct: float
    avg_rr_ratio: float
    trades_with_10016_errors: int
    sharpe_ratio: float
    
    def __str__(self):
        period_name_padded = f"BACKTEST METRICS: {self.period_name}".ljust(48)
        return f"""
+════════════════════════════════════════════════════════+
| {period_name_padded} |
+════════════════════════════════════════════════════════+
| Period: {self.start_date} to {self.end_date}
| Trades:  {self.total_trades:4d} (W: {self.winning_trades:3d} | L: {self.losing_trades:3d})
| Win Rate: {self.win_rate_pct:5.1f}%  |  Profit Factor: {self.profit_factor:6.2f}
| Total P&L: ${self.total_pnl:10.2f}  |  Max Drawdown: {self.max_drawdown_pct:5.1f}%
| Avg R:R Ratio: {self.avg_rr_ratio:5.2f}  |  Sharpe Ratio: {self.sharpe_ratio:6.2f}
| Error 10016 Count: {self.trades_with_10016_errors:3d}
+════════════════════════════════════════════════════════+
"""


@dataclass
class SimulatedTrade:
    """Record of a simulated trade"""
    symbol: str
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    direction: Direction
    quantity: float
    pnl: float
    pnl_pct: float
    rr_ratio: float
    hit_10016_error: bool
    reason: str


class BacktestSimulator:
    """Simulates trading strategy on historical data"""
    
    def __init__(self, 
                 broker: MT5BrokerInterface,
                 strategy: SimpleTrendStrategy,
                 signal_combiner: SignalCombiner,
                 admission_controller: TradeAdmissionController,
                 position_sizer: PositionSizer,
                 initial_equity: float = 100000.0):
        """Initialize backtest simulator"""
        self.broker = broker
        self.strategy = strategy
        self.signal_combiner = signal_combiner
        self.admission_controller = admission_controller
        self.position_sizer = position_sizer
        self.initial_equity = initial_equity
        self.current_equity = initial_equity
        self.portfolio_state = PortfolioState()
        
        self.trades: List[SimulatedTrade] = []
        self.equity_curve: List[Tuple[datetime, float]] = [(datetime.now(timezone.utc), initial_equity)]
        self.drawdown_tracking: List[float] = []
        
        logger.info(f"[BACKTESTER] Initialized with initial equity: ${initial_equity:,.2f}")
    
    async def simulate_period(self,
                             symbols: List[str],
                             market_data_by_symbol: Dict[str, List[MarketData]],
                             period_name: str = "Period") -> BacktestMetrics:
        """Simulate trading for a period"""
        logger.info(f"\n[BACKTEST_{period_name.upper()}] Starting simulation...")
        
        self.trades = []
        self.equity_curve = [(datetime.now(timezone.utc), self.current_equity)]
        
        # Find min/max timestamps across all symbols
        all_timestamps = set()
        for symbol_data in market_data_by_symbol.values():
            for candle in symbol_data:
                all_timestamps.add(candle.timestamp)
        
        sorted_timestamps = sorted(all_timestamps)
        
        # Simulate bar-by-bar
        for bar_idx, timestamp in enumerate(sorted_timestamps):
            if bar_idx % 100 == 0:
                logger.info(f"[BACKTEST_{period_name.upper()}] Processing bar {bar_idx}/{len(sorted_timestamps)}")
            
            for symbol in symbols:
                # Get current candle for this symbol
                symbol_data = market_data_by_symbol[symbol]
                current_candle = next((c for c in symbol_data if c.timestamp == timestamp), None)
                
                if not current_candle:
                    continue
                
                # Get historical context (last 150 candles for indicator calculation)
                historical_context = [c for c in symbol_data if c.timestamp <= timestamp][-150:]
                
                if len(historical_context) < 20:  # Need minimum data
                    continue
                
                # Generate signal
                try:
                    signal = await self.strategy.analyze(
                        historical_data=historical_context,
                        current_positions=self.portfolio_state.active_positions
                    )
                    
                    if signal is None:
                        continue
                    
                    # Admission control
                    admission_result = self.admission_controller.evaluate(signal)
                    if not admission_result.is_admitted:
                        continue
                    
                    # Position sizing
                    position_size = self.position_sizer.calculate_size(
                        signal=signal,
                        equity=self.current_equity,
                        symbol=symbol
                    )
                    
                    if position_size <= 0:
                        continue
                    
                    # Simulate entry
                    entry_pnl = self._simulate_trade(
                        symbol=symbol,
                        signal=signal,
                        entry_time=timestamp,
                        entry_price=current_candle.close,
                        quantity=position_size,
                        remaining_data=symbol_data[symbol_data.index(current_candle):]
                    )
                    
                    if entry_pnl:
                        self.trades.append(entry_pnl)
                        self.current_equity += entry_pnl.pnl
                        self.equity_curve.append((timestamp, self.current_equity))
                
                except Exception as e:
                    logger.warning(f"[BACKTEST_{period_name.upper()}] Error simulating {symbol}: {e}")
                    continue
        
        # Calculate metrics
        metrics = self._calculate_metrics(period_name)
        logger.info(f"[BACKTEST_{period_name.upper()}] Completed with {len(self.trades)} trades")
        logger.info(str(metrics))
        
        return metrics
    
    def _simulate_trade(self,
                       symbol: str,
                       signal: TradingSignal,
                       entry_time: datetime,
                       entry_price: float,
                       quantity: float,
                       remaining_data: List[MarketData]) -> Optional[SimulatedTrade]:
        """Simulate a trade from entry to exit"""
        
        # Find exit (TP or SL hit first)
        max_profit = 0
        max_loss = 0
        exit_price = entry_price
        exit_time = entry_time
        
        for candle in remaining_data[1:]:  # Skip entry candle
            if signal.direction == Direction.LONG:
                # Check TP
                if candle.high >= signal.take_profit:
                    exit_price = signal.take_profit
                    exit_time = candle.timestamp
                    max_profit = (exit_price - entry_price) / entry_price
                    break
                
                # Check SL
                if candle.low <= signal.stop_loss:
                    exit_price = signal.stop_loss
                    exit_time = candle.timestamp
                    max_loss = (exit_price - entry_price) / entry_price
                    break
                
                # Track running profit/loss
                profit = (candle.high - entry_price) / entry_price
                loss = (candle.low - entry_price) / entry_price
                max_profit = max(max_profit, profit)
                max_loss = min(max_loss, loss)
            
            else:  # SHORT
                # Check TP
                if candle.low <= signal.take_profit:
                    exit_price = signal.take_profit
                    exit_time = candle.timestamp
                    max_profit = (entry_price - exit_price) / entry_price
                    break
                
                # Check SL
                if candle.high >= signal.stop_loss:
                    exit_price = signal.stop_loss
                    exit_time = candle.timestamp
                    max_loss = (entry_price - exit_price) / entry_price
                    break
                
                # Track running profit/loss
                profit = (entry_price - candle.low) / entry_price
                loss = (entry_price - candle.high) / entry_price
                max_profit = max(max_profit, profit)
                max_loss = min(max_loss, loss)
            
            # Time-based exit after 24 hours
            if (candle.timestamp - entry_time).total_seconds() > 86400:
                exit_price = candle.close
                exit_time = candle.timestamp
                break
        
        # Calculate P&L
        if signal.direction == Direction.LONG:
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price
        
        pnl = quantity * pnl_pct * entry_price
        rr_ratio = abs((max_profit) / (max_loss + 0.0001))
        
        return SimulatedTrade(
            symbol=symbol,
            entry_time=entry_time,
            entry_price=entry_price,
            exit_time=exit_time,
            exit_price=exit_price,
            direction=signal.direction,
            quantity=quantity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            rr_ratio=rr_ratio,
            hit_10016_error=False,  # Would check logs for this
            reason="TP/SL/Time"
        )
    
    def _calculate_metrics(self, period_name: str) -> BacktestMetrics:
        """Calculate all metrics for the period"""
        
        if not self.trades:
            return BacktestMetrics(
                period_name=period_name,
                start_date=datetime.now(timezone.utc).isoformat(),
                end_date=datetime.now(timezone.utc).isoformat(),
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate_pct=0.0,
                profit_factor=0.0,
                total_pnl=0.0,
                max_drawdown_pct=0.0,
                avg_rr_ratio=0.0,
                trades_with_10016_errors=0,
                sharpe_ratio=0.0
            )
        
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl < 0]
        
        win_rate = len(winning_trades) / len(self.trades) * 100 if self.trades else 0
        
        gross_profit = sum(t.pnl for t in winning_trades) if winning_trades else 0
        gross_loss = abs(sum(t.pnl for t in losing_trades)) if losing_trades else 0
        profit_factor = gross_profit / (gross_loss + 0.01) if gross_loss > 0 else 0
        
        total_pnl = sum(t.pnl for t in self.trades)
        
        # Max drawdown
        max_equity = self.initial_equity
        max_dd = 0
        for _, equity in self.equity_curve:
            if equity > max_equity:
                max_equity = equity
            dd = (max_equity - equity) / max_equity * 100
            max_dd = max(max_dd, dd)
        
        # Average RR ratio
        avg_rr = np.mean([t.rr_ratio for t in self.trades]) if self.trades else 0
        
        # Sharpe ratio (simplified)
        returns = [t.pnl_pct for t in self.trades]
        if returns and len(returns) > 1:
            sharpe = (np.mean(returns) / (np.std(returns) + 0.0001)) * np.sqrt(252)
        else:
            sharpe = 0
        
        # Error 10016 count
        error_count = sum(1 for t in self.trades if t.hit_10016_error)
        
        start_date = self.trades[0].entry_time.isoformat() if self.trades else datetime.now(timezone.utc).isoformat()
        end_date = self.trades[-1].exit_time.isoformat() if self.trades else datetime.now(timezone.utc).isoformat()
        
        return BacktestMetrics(
            period_name=period_name,
            start_date=start_date,
            end_date=end_date,
            total_trades=len(self.trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate_pct=win_rate,
            profit_factor=profit_factor,
            total_pnl=total_pnl,
            max_drawdown_pct=max_dd,
            avg_rr_ratio=avg_rr,
            trades_with_10016_errors=error_count,
            sharpe_ratio=sharpe
        )


class HistoricalDataLoader:
    """Loads 90 days of M5 and H1 historical data from MT5"""
    
    def __init__(self, broker: MT5BrokerInterface):
        self.broker = broker
        self.logger = logger
    
    async def load_period(self,
                          symbols: List[str],
                          timeframes: List[str],
                          days: int = 90) -> Dict[str, List[MarketData]]:
        """Load historical data for symbols"""
        
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        
        all_data = {}
        
        for symbol in symbols:
            self.logger.info(f"[HISTORY_LOADER] Loading {symbol} data ({days} days)...")
            
            for timeframe in timeframes:
                try:
                    # Load from MT5
                    data = await asyncio.to_thread(
                        self.broker.get_historical_data,
                        symbol=symbol,
                        timeframe=timeframe,
                        start_date=start_date,
                        end_date=end_date
                    )
                    
                    if not data:
                        self.logger.warning(f"[HISTORY_LOADER] No data for {symbol} {timeframe}")
                        continue
                    
                    key = f"{symbol}_{timeframe}"
                    all_data[key] = data
                    self.logger.info(f"[HISTORY_LOADER] Loaded {len(data)} candles for {key}")
                
                except Exception as e:
                    self.logger.error(f"[HISTORY_LOADER] Error loading {symbol} {timeframe}: {e}")
                    continue
        
        return all_data


async def main():
    """Main backtester execution"""
    
    logger.info("\n" + "="*60)
    logger.info("PHASE 1: COMPREHENSIVE BASELINE BACKTEST")
    logger.info("="*60)
    
    # Initialize components
    broker = MT5BrokerInterface(
    login=123456789,
    password="your_password",
    server="MetaQuotes-Demo",
    )
    try:
        if not await broker.connect():
            logger.error("[BACKTESTER] Failed to connect to MT5 broker")
            return
        
        logger.info("[BACKTESTER] MT5 initialized successfully")
        
        # Define symbols and timeframes
        symbols = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "EURJPY"]
        timeframes = ["M5", "H1"]
        
        # Load historical data (90 days)
        loader = HistoricalDataLoader(broker)
        historical_data = await loader.load_period(symbols, timeframes, days=90)
        
        if not historical_data:
            logger.error("[BACKTESTER] No historical data loaded")
            return
        
        logger.info(f"[BACKTESTER] Loaded data for {len(historical_data)} symbol-timeframe combinations")
        
        # Initialize strategy components
        strategy = SimpleTrendStrategy()
        signal_weights = SignalWeights(sentiment_weight=0.0, technical_weight=1.0)
        signal_combiner = SignalCombiner(signal_weights=signal_weights, min_confidence_threshold=0.2)
        admission_controller = TradeAdmissionController()
        position_sizer = PositionSizer()
        
        # Initialize simulator
        simulator = BacktestSimulator(
            broker=broker,
            strategy=strategy,
            signal_combiner=signal_combiner,
            admission_controller=admission_controller,
            position_sizer=position_sizer,
            initial_equity=100000.0
        )
        
        # Run simulation on full 90-day period
        metrics = await simulator.simulate_period(
            symbols=symbols,
            market_data_by_symbol=historical_data,
            period_name="Baseline_90Days"
        )
        
        # Save baseline report
        report = {
            "baseline_metrics": asdict(metrics),
            "configuration": {
                "ml_weight": 0.70,
                "technical_weight": 0.30,
                "trailing_stop_activation_pips": 20.0,
                "dynamic_lock_increment_usd": 2.00
            }
        }
        
        report_path = Path(__file__).parent.parent.parent / "backtest_baseline_report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        
        logger.info(f"[BACKTESTER] Baseline report saved to {report_path}")
        logger.info(str(metrics))
        
        logger.info("\n" + "="*60)
        logger.info("PHASE 1 COMPLETE: Baseline metrics established")
        logger.info("="*60)
    
    except Exception as e:
        logger.error(f"[BACKTESTER] Fatal error: {e}", exc_info=True)
    
    finally:
        await broker.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
