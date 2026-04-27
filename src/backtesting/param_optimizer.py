"""
Parameter Optimization & Filter Ablation Backtester
====================================================
Finds optimal entry parameters to fix analysis paralysis and trade starvation.

Tests:
1. Quality Floor thresholds (30%-50%)
2. ML Confidence thresholds (0.50-0.56)
3. Filter Ablation (baseline_only, baseline_plus_quant, baseline_plus_adx)
4. Quantitative feed integration (Z-Score & GARCH constraints)

Fitness Metrics:
- Trade Frequency (penalize < 10 trades/month)
- Profit Factor / Expectancy
- Sharpe Ratio
- Max Drawdown (< 5%)

Output: Ranked parameter sets for production config.json update
"""

import pandas as pd
import numpy as np
import json
import os
from itertools import product
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('optimization_results/param_optimization.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class OptimizationConfig:
    """Parameter grid configuration"""
    # Quality Floor (Score Threshold)
    quality_floor: List[float] = None
    
    # ML Confidence Threshold
    ml_confidence_threshold: List[float] = None
    
    # Filter Ablation States
    filter_mode: List[str] = None
    
    # Quantitative Constraints
    zscore_min: float = -2.0
    zscore_max: float = 2.0
    garch_vol_min: float = 0.0000
    
    # Risk Management
    risk_per_trade: float = 0.01  # 1% of equity
    rr_ratio: float = 1.5  # 1:1.5 Risk/Reward
    
    # Backtest Settings
    initial_capital: float = 10000.0
    spread_pips: float = 1.0
    commission_pct: float = 0.001
    
    def __post_init__(self):
        if self.quality_floor is None:
            self.quality_floor = [0.30, 0.35, 0.40, 0.45, 0.50]
        if self.ml_confidence_threshold is None:
            self.ml_confidence_threshold = [0.50, 0.52, 0.54, 0.56]
        if self.filter_mode is None:
            self.filter_mode = ['baseline_only', 'baseline_plus_quant', 'baseline_plus_adx']


@dataclass
class BacktestResult:
    """Results from a single parameter combination"""
    # Parameters
    quality_floor: float
    ml_confidence_threshold: float
    filter_mode: str
    
    # Performance Metrics
    total_trades: int
    trades_per_month: float
    total_return_pct: float
    profit_factor: float
    expectancy: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    avg_win: float
    avg_loss: float
    
    # Fitness Score (composite)
    fitness_score: float = 0.0
    
    def calculate_fitness(self):
        """
        Calculate composite fitness score.
        
        Priorities:
        1. Trade Frequency (must have >= 10 trades/month, heavily penalize below)
        2. Profit Factor / Expectancy
        3. Sharpe Ratio
        4. Max Drawdown (penalize > 5%)
        """
        score = 0.0
        
        # 1. Trade Frequency Score (0-30 points)
        if self.trades_per_month >= 30:  # 1+ trades/day
            freq_score = 30.0
        elif self.trades_per_month >= 10:
            freq_score = 20.0 + (self.trades_per_month - 10) * 0.5
        elif self.trades_per_month >= 5:
            freq_score = 10.0 + (self.trades_per_month - 5) * 2.0
        else:
            # HEAVY penalty for starvation
            freq_score = max(0.0, self.trades_per_month * 2.0)
        
        # 2. Profit Factor Score (0-30 points)
        if self.profit_factor >= 2.0:
            pf_score = 30.0
        elif self.profit_factor >= 1.5:
            pf_score = 20.0 + (self.profit_factor - 1.5) * 20.0
        elif self.profit_factor >= 1.0:
            pf_score = 10.0 + (self.profit_factor - 1.0) * 20.0
        else:
            pf_score = max(0.0, self.profit_factor * 10.0)
        
        # 3. Sharpe Ratio Score (0-20 points)
        if self.sharpe_ratio >= 2.0:
            sharpe_score = 20.0
        elif self.sharpe_ratio >= 1.0:
            sharpe_score = 10.0 + (self.sharpe_ratio - 1.0) * 10.0
        elif self.sharpe_ratio >= 0.5:
            sharpe_score = 5.0 + (self.sharpe_ratio - 0.5) * 10.0
        else:
            sharpe_score = max(0.0, (self.sharpe_ratio + 1.0) * 5.0)
        
        # 4. Max Drawdown Score (0-20 points)
        if self.max_drawdown_pct <= 0.02:  # <= 2%
            dd_score = 20.0
        elif self.max_drawdown_pct <= 0.05:  # <= 5%
            dd_score = 15.0 + (0.05 - self.max_drawdown_pct) * 100.0
        elif self.max_drawdown_pct <= 0.10:  # <= 10%
            dd_score = 10.0 + (0.10 - self.max_drawdown_pct) * 100.0
        else:
            # Heavy penalty for excessive drawdown
            dd_score = max(0.0, 10.0 - (self.max_drawdown_pct - 0.10) * 100.0)
        
        # Composite Score
        score = freq_score + pf_score + sharpe_score + dd_score
        
        # Disqualification filters
        if self.trades_per_month < 5:
            score *= 0.3  # Severe penalty for trade starvation
        if self.max_drawdown_pct > 0.10:
            score *= 0.5  # Penalty for excessive drawdown
        if self.profit_factor < 1.0:
            score *= 0.4  # Penalty for losing system
        
        self.fitness_score = score
        return score


class ParameterOptimizer:
    """
    Runs parameter grid optimization with filter ablation testing.
    """
    
    def __init__(self, config: OptimizationConfig):
        self.config = config
        self.results: List[BacktestResult] = []
        self.trade_log: List[Dict] = []
        
    def load_historical_data(self, symbol: str, filepath: str) -> pd.DataFrame:
        """
        Load historical OHLCV data from CSV or MT5 export.
        
        Expected columns: timestamp, open, high, low, close, volume
        """
        logger.info(f"Loading data for {symbol} from {filepath}")
        
        if filepath.endswith('.csv'):
            df = pd.read_csv(filepath)
        elif filepath.endswith('.parquet'):
            df = pd.read_parquet(filepath)
        else:
            raise ValueError(f"Unsupported file format: {filepath}")
        
        # Standardize columns
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        # Calculate returns
        df['return'] = df['close'].pct_change()
        df['log_return'] = np.log(df['close'] / df['close'].shift(1))
        
        # Calculate ATR (for SL/TP sizing)
        df['atr'] = self._calculate_atr(df, period=14)
        
        logger.info(f"Loaded {len(df)} bars for {symbol} | Range: {df['timestamp'].min()} to {df['timestamp'].max()}")
        
        return df
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr
    
    def generate_parameter_grid(self) -> List[Dict]:
        """Generate all parameter combinations to test"""
        grid = []
        
        for qf, ml_conf, filter_mode in product(
            self.config.quality_floor,
            self.config.ml_confidence_threshold,
            self.config.filter_mode
        ):
            grid.append({
                'quality_floor': qf,
                'ml_confidence_threshold': ml_conf,
                'filter_mode': filter_mode
            })
        
        logger.info(f"Generated {len(grid)} parameter combinations to test")
        return grid
    
    def simulate_quant_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Simulate Z-Score (mean reversion) and GARCH (volatility) signals.
        
        In production, these come from your OU process and GARCH models.
        Here we simulate them for backtesting.
        """
        # Simulate Z-Score (mean-reverting process)
        prices = df['close'].values
        window = 50
        
        z_scores = np.zeros(len(prices))
        for i in range(window, len(prices)):
            window_prices = prices[i-window:i]
            mean = np.mean(window_prices)
            std = np.std(window_prices)
            if std > 0:
                z_scores[i] = (prices[i] - mean) / std
        
        df['z_score'] = z_scores
        
        # Simulate GARCH volatility (simplified EWMA)
        returns = df['return'].fillna(0).values
        garch_vol = np.zeros(len(returns))
        garch_vol[0] = np.std(returns)
        
        lambda_ewma = 0.94  # GARCH decay factor
        
        for i in range(1, len(returns)):
            garch_vol[i] = lambda_ewma * garch_vol[i-1]**2 + (1 - lambda_ewma) * returns[i-1]**2
        
        df['garch_vol'] = np.sqrt(garch_vol)
        
        return df
    
    def apply_entry_filters(self, signal: Dict, params: Dict, bar: pd.Series) -> bool:
        """
        Apply entry filters based on filter_mode.
        
        Returns True if signal passes all filters, False otherwise.
        """
        # 1. Quality Floor Check
        if signal.get('quality_score', 0.5) < params['quality_floor']:
            return False
        
        # 2. ML Confidence Check
        if signal.get('ml_confidence', 0.5) < params['ml_confidence_threshold']:
            return False
        
        # 3. Filter Ablation
        filter_mode = params['filter_mode']
        
        if filter_mode == 'baseline_only':
            # Only quality floor + ML confidence (already checked above)
            pass
        
        elif filter_mode == 'baseline_plus_quant':
            # Add Z-Score and GARCH constraints
            z_score = bar.get('z_score', 0.0)
            garch_vol = bar.get('garch_vol', 0.0)
            
            if z_score < self.config.zscore_min or z_score > self.config.zscore_max:
                return False
            if garch_vol < self.config.garch_vol_min:
                return False
        
        elif filter_mode == 'baseline_plus_adx':
            # Add ADX constraint (ADX > 15 for trend confirmation)
            adx = bar.get('adx', 20.0)  # Default to 20 if not available
            if adx < 15:
                return False
        
        return True
    
    def backtest_single_pass(self, df: pd.DataFrame, params: Dict) -> BacktestResult:
        """
        Run backtest with a single parameter combination.
        
        Exit Logic: Fixed SL/TP at 1:1.5 RR (no trailing stops)
        """
        equity = self.config.initial_capital
        peak_equity = equity
        max_drawdown = 0.0
        
        trades = []
        in_position = False
        entry_price = 0.0
        entry_time = None
        position_direction = None
        stop_loss = 0.0
        take_profit = 0.0
        position_size = 0.0
        
        # Simulate signals (in production, these come from your strategy)
        df_with_signals = self._generate_mock_signals(df)
        
        for i in range(100, len(df_with_signals)):  # Skip first 100 bars for indicator warmup
            bar = df_with_signals.iloc[i]
            
            # Check exit conditions if in position
            if in_position:
                exit_price = None
                exit_reason = None
                
                if position_direction == 'LONG':
                    if bar['low'] <= stop_loss:
                        exit_price = stop_loss
                        exit_reason = 'STOP_LOSS'
                    elif bar['high'] >= take_profit:
                        exit_price = take_profit
                        exit_reason = 'TAKE_PROFIT'
                
                elif position_direction == 'SHORT':
                    if bar['high'] >= stop_loss:
                        exit_price = stop_loss
                        exit_reason = 'STOP_LOSS'
                    elif bar['low'] <= take_profit:
                        exit_price = take_profit
                        exit_reason = 'TAKE_PROFIT'
                
                # Exit position
                if exit_price:
                    # Calculate P&L
                    if position_direction == 'LONG':
                        pnl = (exit_price - entry_price) * position_size * 100000
                    else:
                        pnl = (entry_price - exit_price) * position_size * 100000
                    
                    # Subtract costs
                    spread_cost = self.config.spread_pips * 0.0001 * position_size * 100000
                    commission = entry_price * position_size * 100000 * self.config.commission_pct
                    net_pnl = pnl - spread_cost - commission
                    
                    # Update equity
                    equity += net_pnl
                    
                    # Track max drawdown
                    if equity > peak_equity:
                        peak_equity = equity
                    drawdown = (peak_equity - equity) / peak_equity
                    if drawdown > max_drawdown:
                        max_drawdown = drawdown
                    
                    # Record trade
                    trades.append({
                        'entry_time': entry_time,
                        'exit_time': bar['timestamp'],
                        'direction': position_direction,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'gross_pnl': pnl,
                        'net_pnl': net_pnl,
                        'exit_reason': exit_reason,
                        'bars_held': i - entry_bar_idx
                    })
                    
                    in_position = False
            
            # Check entry conditions if not in position
            if not in_position and i < len(df_with_signals) - 1:
                signal = df_with_signals.iloc[i]
                
                # Apply filters
                if self.apply_entry_filters(signal, params, bar):
                    # Enter position
                    entry_price = bar['close']
                    entry_time = bar['timestamp']
                    entry_bar_idx = i
                    
                    # Determine direction from signal
                    position_direction = signal.get('direction', 'LONG')
                    
                    # Calculate position size (1% risk)
                    atr = bar.get('atr', entry_price * 0.005)
                    sl_distance = atr * 2  # 2 ATR stop
                    position_size = (equity * self.config.risk_per_trade) / sl_distance
                    
                    # Set SL/TP (1:1.5 RR)
                    if position_direction == 'LONG':
                        stop_loss = entry_price - sl_distance
                        take_profit = entry_price + (sl_distance * self.config.rr_ratio)
                    else:
                        stop_loss = entry_price + sl_distance
                        take_profit = entry_price - (sl_distance * self.config.rr_ratio)
                    
                    in_position = True
        
        # Calculate metrics
        return self._calculate_metrics(trades, equity, max_drawdown, params)
    
    def _generate_mock_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate mock trading signals for backtesting.
        
        In production, replace this with your actual strategy logic.
        This simulates signals based on simple technical indicators.
        """
        df = df.copy()
        
        # Simple MA crossover signal
        df['sma_20'] = df['close'].rolling(window=20).mean()
        df['sma_50'] = df['close'].rolling(window=50).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # ADX (simplified)
        df['adx'] = 25 + np.random.normal(0, 10, len(df))  # Mock ADX
        
        # Generate signals
        df['direction'] = 'NONE'
        df.loc[(df['sma_20'] > df['sma_50']) & (df['rsi'] < 70), 'direction'] = 'LONG'
        df.loc[(df['sma_20'] < df['sma_50']) & (df['rsi'] > 30), 'direction'] = 'SHORT'
        
        # Mock quality score and ML confidence
        df['quality_score'] = 0.4 + np.random.normal(0, 0.1, len(df))
        df['ml_confidence'] = 0.52 + np.random.normal(0, 0.08, len(df))
        
        # Clamp values
        df['quality_score'] = df['quality_score'].clip(0, 1)
        df['ml_confidence'] = df['ml_confidence'].clip(0, 1)
        
        return df
    
    def _calculate_metrics(self, trades: List[Dict], final_equity: float, 
                          max_drawdown: float, params: Dict) -> BacktestResult:
        """Calculate comprehensive backtest metrics"""
        
        if not trades:
            return BacktestResult(
                quality_floor=params['quality_floor'],
                ml_confidence_threshold=params['ml_confidence_threshold'],
                filter_mode=params['filter_mode'],
                total_trades=0,
                trades_per_month=0.0,
                total_return_pct=0.0,
                profit_factor=0.0,
                expectancy=0.0,
                sharpe_ratio=0.0,
                max_drawdown_pct=0.0,
                win_rate=0.0,
                avg_win=0.0,
                avg_loss=0.0
            )
        
        # Basic metrics
        total_trades = len(trades)
        winning_trades = [t for t in trades if t['net_pnl'] > 0]
        losing_trades = [t for t in trades if t['net_pnl'] <= 0]
        
        # Trade frequency
        if total_trades >= 2:
            time_span_days = (trades[-1]['exit_time'] - trades[0]['entry_time']).days
            trades_per_month = (total_trades / max(time_span_days, 1)) * 30
        else:
            trades_per_month = 0.0
        
        # Returns
        total_return = (final_equity - self.config.initial_capital) / self.config.initial_capital
        
        # Win rate
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0.0
        
        # Profit factor
        gross_profit = sum(t['net_pnl'] for t in winning_trades) if winning_trades else 0.0
        gross_loss = abs(sum(t['net_pnl'] for t in losing_trades)) if losing_trades else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Expectancy
        avg_win = gross_profit / len(winning_trades) if winning_trades else 0.0
        avg_loss = gross_loss / len(losing_trades) if losing_trades else 0.0
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        
        # Sharpe Ratio (simplified)
        returns = [t['net_pnl'] / self.config.initial_capital for t in trades]
        sharpe_ratio = (np.mean(returns) / np.std(returns) * np.sqrt(252)) if np.std(returns) > 0 else 0.0
        
        return BacktestResult(
            quality_floor=params['quality_floor'],
            ml_confidence_threshold=params['ml_confidence_threshold'],
            filter_mode=params['filter_mode'],
            total_trades=total_trades,
            trades_per_month=trades_per_month,
            total_return_pct=total_return * 100,
            profit_factor=profit_factor,
            expectancy=expectancy,
            sharpe_ratio=sharpe_ratio,
            max_drawdown_pct=max_drawdown * 100,
            win_rate=win_rate * 100,
            avg_win=avg_win,
            avg_loss=avg_loss
        )
    
    def run_optimization(self, df: pd.DataFrame) -> List[BacktestResult]:
        """
        Run full parameter grid optimization.
        """
        logger.info("="*80)
        logger.info("STARTING PARAMETER OPTIMIZATION")
        logger.info("="*80)
        
        # Generate parameter grid
        param_grid = self.generate_parameter_grid()
        
        # Add quantitative signals
        df_with_quant = self.simulate_quant_signals(df)
        
        # Test each parameter combination
        for i, params in enumerate(param_grid):
            logger.info(f"\n[{i+1}/{len(param_grid)}] Testing: {params}")
            
            result = self.backtest_single_pass(df_with_quant, params)
            result.calculate_fitness()
            
            self.results.append(result)
            
            logger.info(
                f"  Trades: {result.total_trades} | "
                f"Freq: {result.trades_per_month:.1f}/mo | "
                f"Return: {result.total_return_pct:.2f}% | "
                f"PF: {result.profit_factor:.2f} | "
                f"Sharpe: {result.sharpe_ratio:.2f} | "
                f"DD: {result.max_drawdown_pct:.2f}% | "
                f"Fitness: {result.fitness_score:.1f}"
            )
        
        # Sort by fitness score
        self.results.sort(key=lambda x: x.fitness_score, reverse=True)
        
        return self.results
    
    def print_top_results(self, top_n: int = 10):
        """Print top N parameter combinations"""
        logger.info("\n" + "="*80)
        logger.info(f"TOP {top_n} PARAMETER COMBINATIONS")
        logger.info("="*80)
        
        for i, result in enumerate(self.results[:top_n]):
            logger.info(f"\n#{i+1} | Fitness Score: {result.fitness_score:.1f}")
            logger.info(f"  Quality Floor: {result.quality_floor:.0%}")
            logger.info(f"  ML Confidence: {result.ml_confidence_threshold:.2f}")
            logger.info(f"  Filter Mode: {result.filter_mode}")
            logger.info(f"  Total Trades: {result.total_trades}")
            logger.info(f"  Trades/Month: {result.trades_per_month:.1f}")
            logger.info(f"  Total Return: {result.total_return_pct:.2f}%")
            logger.info(f"  Profit Factor: {result.profit_factor:.2f}")
            logger.info(f"  Expectancy: ${result.expectancy:.2f}")
            logger.info(f"  Sharpe Ratio: {result.sharpe_ratio:.2f}")
            logger.info(f"  Max Drawdown: {result.max_drawdown_pct:.2f}%")
            logger.info(f"  Win Rate: {result.win_rate:.1f}%")
    
    def save_results(self, filepath: str = 'optimization_results/param_optimization.json'):
        """Save optimization results to JSON"""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        results_dict = {
            'optimization_timestamp': datetime.now().isoformat(),
            'total_combinations_tested': len(self.results),
            'top_results': [asdict(r) for r in self.results[:20]]
        }
        
        with open(filepath, 'w') as f:
            json.dump(results_dict, f, indent=2, default=str)
        
        logger.info(f"\nResults saved to {filepath}")
    
    def generate_production_config(self, top_result: BacktestResult, 
                                   output_path: str = 'config/optimized_params.json'):
        """
        Generate production-ready config.json with optimized parameters.
        """
        config = {
            "optimization_date": datetime.now().isoformat(),
            "fitness_score": top_result.fitness_score,
            "entry_filters": {
                "quality_floor": top_result.quality_floor,
                "ml_confidence_min": top_result.ml_confidence_threshold,
                "filter_mode": top_result.filter_mode,
                "adx_min": 15 if 'adx' in top_result.filter_mode else None,
                "zscore_min": self.config.zscore_min,
                "zscore_max": self.config.zscore_max,
                "garch_vol_min": self.config.garch_vol_min
            },
            "risk_management": {
                "risk_per_trade": self.config.risk_per_trade,
                "rr_ratio": self.config.rr_ratio
            },
            "expected_performance": {
                "trades_per_month": top_result.trades_per_month,
                "total_return_pct": top_result.total_return_pct,
                "profit_factor": top_result.profit_factor,
                "sharpe_ratio": top_result.sharpe_ratio,
                "max_drawdown_pct": top_result.max_drawdown_pct,
                "win_rate": top_result.win_rate
            }
        }
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        logger.info(f"\nProduction config saved to {output_path}")
        return config


def main():
    """Run the full optimization pipeline"""
    
    # 1. Configure optimization
    config = OptimizationConfig(
        quality_floor=[0.30, 0.35, 0.40, 0.45, 0.50],
        ml_confidence_threshold=[0.50, 0.52, 0.54, 0.56],
        filter_mode=['baseline_only', 'baseline_plus_quant', 'baseline_plus_adx'],
        initial_capital=10000.0,
        risk_per_trade=0.01,
        rr_ratio=1.5
    )
    
    # 2. Initialize optimizer
    optimizer = ParameterOptimizer(config)
    
    # 3. Load historical data (adjust path to your data)
    # You can use EUR/USD data from your EURUSD Data folder
    data_files = {
        'EURUSD': 'EURUSD Data/EURUSD_H1.csv',  # Adjust path
        'GBPUSD': 'data/GBPUSD_H1.csv',
        'USDJPY': 'data/USDJPY_H1.csv'
    }
    
    # Try to load data
    symbol = 'EURUSD'
    data_file = data_files.get(symbol)
    
    if data_file and os.path.exists(data_file):
        df = optimizer.load_historical_data(symbol, data_file)
    else:
        logger.warning(f"Data file {data_file} not found. Generating synthetic data for testing...")
        # Generate synthetic data for testing
        dates = pd.date_range(start='2024-01-01', end='2024-12-31', freq='h')
        np.random.seed(42)
        
        df = pd.DataFrame({
            'timestamp': dates,
            'open': 1.1000 + np.cumsum(np.random.normal(0, 0.001, len(dates))),
            'high': 1.1000 + np.cumsum(np.random.normal(0, 0.001, len(dates))) + 0.0005,
            'low': 1.1000 + np.cumsum(np.random.normal(0, 0.001, len(dates))) - 0.0005,
            'close': 1.1000 + np.cumsum(np.random.normal(0, 0.001, len(dates))),
            'volume': np.random.randint(1000, 10000, len(dates))
        })
        
        # Calculate returns
        df['return'] = df['close'].pct_change()
    
    # 4. Run optimization
    results = optimizer.run_optimization(df)
    
    # 5. Display results
    optimizer.print_top_results(top_n=10)
    
    # 6. Save results
    optimizer.save_results()
    
    # 7. Generate production config
    if results:
        best_result = results[0]
        prod_config = optimizer.generate_production_config(best_result)
        
        logger.info("\n" + "="*80)
        logger.info("RECOMMENDED PRODUCTION PARAMETERS")
        logger.info("="*80)
        logger.info(f"Quality Floor: {best_result.quality_floor:.0%}")
        logger.info(f"ML Confidence Threshold: {best_result.ml_confidence_threshold:.2f}")
        logger.info(f"Filter Mode: {best_result.filter_mode}")
        logger.info(f"Expected Trades/Month: {best_result.trades_per_month:.1f}")
        logger.info(f"Expected Return: {best_result.total_return_pct:.2f}%")
        logger.info(f"Profit Factor: {best_result.profit_factor:.2f}")
        logger.info(f"Max Drawdown: {best_result.max_drawdown_pct:.2f}%")
        
        logger.info("\n" + "="*80)
        logger.info("NEXT STEPS")
        logger.info("="*80)
        logger.info("1. Review the top 10 results in optimization_results/param_optimization.json")
        logger.info("2. Update your bot's config with the recommended parameters")
        logger.info("3. Run a walk-forward validation to ensure no overfitting")
        logger.info("4. Deploy to paper trading for 1-2 weeks before live trading")


if __name__ == '__main__':
    main()
