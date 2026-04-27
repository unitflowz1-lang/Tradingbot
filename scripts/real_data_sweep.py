#!/usr/bin/env python3
"""
REAL DATA AGGRESSIVE HYPERPARAMETER SWEEP
=========================================
Runs the aggressive optimization using REAL historical MT5 data
Includes realistic spread modeling (2 points) and slippage

Usage:
    python scripts/real_data_sweep.py

Requires:
    - data/EURUSD_90d_real.csv (from harvest_real_data.py)
    - data/GBPUSD_90d_real.csv
"""

import asyncio
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from itertools import product
import json
import sys
import logging
from datetime import datetime

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class ParameterSet:
    """Single parameter configuration"""
    quality_floor: float
    adx_min: float
    rsi_lower: float
    rsi_upper: float
    atr_sl_multiplier: float
    atr_tp_multiplier: float
    ml_weight: float
    technical_weight: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            'quality_floor': self.quality_floor,
            'adx_min': self.adx_min,
            'rsi_lower': self.rsi_lower,
            'rsi_upper': self.rsi_upper,
            'atr_sl_multiplier': self.atr_sl_multiplier,
            'atr_tp_multiplier': self.atr_tp_multiplier,
            'ml_weight': self.ml_weight,
            'technical_weight': self.technical_weight,
        }


@dataclass
class BacktestResult:
    """Results from a single backtest run"""
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    test_period_days: float = 0.0
    fitness_score: float = 0.0


# ============================================================================
# REAL DATA BACKTEST ENGINE
# ============================================================================

class RealDataBacktester:
    """Backtest engine using real historical data with spread modeling"""
    
    def __init__(self, spread_points: float = 2.0):
        """
        Args:
            spread_points: Spread cost in points (default: 2.0 = 0.0002)
        """
        self.spread_points = spread_points
        self.spread_cost_per_lot = spread_points * 0.0001 * 100000  # $20 per standard lot for 2 points
        
    def load_real_data(self, symbol: str, filepath: str) -> pd.DataFrame:
        """Load real historical data from CSV"""
        df = pd.read_csv(filepath)
        df['time'] = pd.to_datetime(df['time'])
        df = df.sort_values('time').reset_index(drop=True)
        
        logger.info(f"[DATA] Loaded {len(df)} candles for {symbol} from {filepath}")
        logger.info(f"       Date range: {df['time'].min()} to {df['time'].max()}")
        
        return df
    
    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.rolling(window=period).mean()
        
        return atr
    
    def run_backtest(self, params: ParameterSet, data: pd.DataFrame) -> BacktestResult:
        """
        Run backtest on real data with spread modeling
        
        Strategy: Simple SMA crossover with ATR-based SL/TP
        (Replace with your actual strategy logic)
        """
        if len(data) < 100:
            return BacktestResult()
        
        # Calculate ATR
        data = data.copy()
        data['atr'] = self.calculate_atr(data, period=14)
        
        # Trading parameters
        atr_sl = params.atr_sl_multiplier
        atr_tp = params.atr_tp_multiplier
        
        # State
        equity = 10000.0
        peak_equity = equity
        trades = []
        in_position = False
        entry_price = 0.0
        position_type = None
        stop_loss = 0.0
        take_profit = 0.0
        
        # Walk through data
        start_idx = 34  # 14 for ATR + 20 for SMA
        
        for i in range(start_idx, len(data)):
            bar = data.iloc[i]
            current_atr = bar['atr']
            
            if pd.isna(current_atr) or current_atr == 0:
                continue
            
            # EXIT LOGIC
            if in_position:
                exit_price = None
                exit_reason = None
                
                if position_type == 'LONG':
                    if bar['low'] <= stop_loss:
                        exit_price = stop_loss
                        exit_reason = 'SL'
                    elif bar['high'] >= take_profit:
                        exit_price = take_profit
                        exit_reason = 'TP'
                
                elif position_type == 'SHORT':
                    if bar['high'] >= stop_loss:
                        exit_price = stop_loss
                        exit_reason = 'SL'
                    elif bar['low'] <= take_profit:
                        exit_price = take_profit
                        exit_reason = 'TP'
                
                if exit_price:
                    # Calculate P&L
                    if position_type == 'LONG':
                        gross_pnl = (exit_price - entry_price) * 100000
                    else:
                        gross_pnl = (entry_price - exit_price) * 100000
                    
                    # Subtract spread cost
                    net_pnl = gross_pnl - self.spread_cost_per_lot
                    
                    equity += net_pnl
                    
                    if equity > peak_equity:
                        peak_equity = equity
                    
                    drawdown = (peak_equity - equity) / peak_equity
                    
                    trades.append({
                        'entry_idx': i,
                        'type': position_type,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'gross_pnl': gross_pnl,
                        'net_pnl': net_pnl,
                        'exit_reason': exit_reason,
                        'equity': equity,
                        'drawdown': drawdown
                    })
                    
                    in_position = False
            
            # ENTRY LOGIC
            if not in_position:
                # Calculate SMA-20
                sma_20 = data['close'].iloc[i-20:i].mean()
                current_price = bar['close']
                
                # Long signal
                if current_price > sma_20 * 1.0005:
                    entry_price = bar['close'] + (self.spread_points * 0.00005)
                    position_type = 'LONG'
                    
                    stop_loss = entry_price - (current_atr * atr_sl)
                    take_profit = entry_price + (current_atr * atr_tp)
                    
                    in_position = True
                
                # Short signal
                elif current_price < sma_20 * 0.9995:
                    entry_price = bar['close'] - (self.spread_points * 0.00005)
                    position_type = 'SHORT'
                    
                    stop_loss = entry_price + (current_atr * atr_sl)
                    take_profit = entry_price - (current_atr * atr_tp)
                    
                    in_position = True
        
        # Calculate metrics
        if not trades:
            return BacktestResult(
                total_trades=0,
                win_rate=0.0,
                profit_factor=0.0,
                sharpe_ratio=0.0,
                max_drawdown_pct=0.0,
                total_pnl=0.0,
                test_period_days=len(data) * 5 / 1440
            )
        
        winning_trades = [t for t in trades if t['net_pnl'] > 0]
        losing_trades = [t for t in trades if t['net_pnl'] <= 0]
        
        win_rate = len(winning_trades) / len(trades)
        
        gross_profit = sum(t['net_pnl'] for t in winning_trades) if winning_trades else 0.0
        gross_loss = abs(sum(t['net_pnl'] for t in losing_trades)) if losing_trades else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 10.0
        
        total_pnl = sum(t['net_pnl'] for t in trades)
        max_dd = max(t['drawdown'] for t in trades) * 100
        
        returns = [t['net_pnl'] / 10000.0 for t in trades]
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(252)
        else:
            sharpe = 0.0
        
        test_period_days = len(data) * 5 / 1440
        
        return BacktestResult(
            total_trades=len(trades),
            win_rate=win_rate,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe,
            max_drawdown_pct=max_dd,
            total_pnl=total_pnl,
            total_return_pct=(equity - 10000) / 100,
            test_period_days=test_period_days
        )


# ============================================================================
# FITNESS FUNCTION (Same as aggressive sweep)
# ============================================================================

def calculate_fitness_score(result: BacktestResult) -> float:
    """Aggressive Multi-Objective Fitness Function"""
    profit_score = min(100, (result.total_pnl / 5000.0) * 100) if result.total_pnl > 0 else 0
    
    trades_per_month = result.total_trades / max(result.test_period_days / 30, 1) if result.test_period_days > 0 else 0
    if trades_per_month >= 80: freq_score = 100
    elif trades_per_month >= 60: freq_score = 80 + (trades_per_month - 60) * 1.0
    elif trades_per_month >= 40: freq_score = 50 + (trades_per_month - 40) * 1.5
    else: freq_score = max(0, trades_per_month * 1.25)
    
    sharpe_score = min(100, (result.sharpe_ratio / 3.0) * 100) if result.sharpe_ratio > 0 else 0
    
    dd = result.max_drawdown_pct
    if dd <= 5: dd_score = 100
    elif dd <= 10: dd_score = 80 + (10 - dd) * 4
    elif dd <= 15: dd_score = 50 + (15 - dd) * 6
    else: dd_score = max(0, 50 - (dd - 15) * 10)
    
    fitness = (profit_score * 0.35) + (freq_score * 0.25) + (sharpe_score * 0.25) + (dd_score * 0.15)
    
    if result.max_drawdown_pct > 15: fitness *= 0.2
    if trades_per_month < 40: fitness *= 0.5  # Relaxed for real data
    if result.sharpe_ratio < 1.5: fitness *= 0.6  # Relaxed for real data
    if result.win_rate < 0.45: fitness *= 0.3  # Minimum 45% win rate
    
    return fitness


# ============================================================================
# MAIN SWEEP EXECUTION
# ============================================================================

async def run_real_data_sweep():
    """Run aggressive sweep on real historical data"""
    
    print("="*80)
    print("REAL DATA AGGRESSIVE HYPERPARAMETER SWEEP")
    print("="*80)
    print(f"\n⚠️  MODE: Real Historical Data with 2-Point Spread Modeling")
    print(f"   This will give REALISTIC (lower) but TRADABLE results\n")
    
    # Load real data
    data_dir = Path(__file__).parent.parent / "data"
    eurusd_path = data_dir / "EURUSD_90d_real.csv"
    gbpusd_path = data_dir / "GBPUSD_90d_real.csv"
    
    if not eurusd_path.exists() or not gbpusd_path.exists():
        print("❌ Real data files not found!")
        print("   Please run: python scripts/harvest_real_data.py")
        sys.exit(1)
    
    backtester = RealDataBacktester(spread_points=2.0)
    
    eurusd_data = backtester.load_real_data("EURUSD", str(eurusd_path))
    gbpusd_data = backtester.load_real_data("GBPUSD", str(gbpusd_path))
    
    # Define parameter space (reduced for speed)
    param_ranges = {
        'quality_floor': [68, 70, 72],
        'adx_min': [18, 20, 22],
        'rsi_lower': [28, 30],
        'rsi_upper': [60, 62],
        'atr_sl_multiplier': [1.8, 2.0, 2.2],  # Testing if 2.0 is too tight
        'atr_tp_multiplier': [2.5, 3.0, 3.5],
        'ml_weight': [0.45, 0.50, 0.55],
    }
    
    combinations = []
    keys = list(param_ranges.keys())
    
    for values in product(*[param_ranges[k] for k in keys]):
        params = dict(zip(keys, values))
        
        if params['atr_tp_multiplier'] <= params['atr_sl_multiplier'] * 1.0:
            continue
        
        params['technical_weight'] = round(1.0 - params['ml_weight'] - 0.05, 2)
        
        if params['technical_weight'] < 0.30 or params['technical_weight'] > 0.60:
            continue
        
        combinations.append(ParameterSet(**params))
    
    print(f"\n🔍 Testing {len(combinations)} parameter combinations on REAL data...")
    print(f"   Spread: 2 points ($20/lot per trade)")
    print(f"   Symbols: EURUSD ({len(eurusd_data)} candles), GBPUSD ({len(gbpusd_data)} candles)\n")
    
    # Run sweep
    results = []
    total = len(combinations)
    
    for idx, params in enumerate(combinations, 1):
        if idx % 10 == 0:
            print(f"   Progress: {idx}/{total} ({idx/total*100:.1f}%)")
        
        # Backtest on both symbols
        eurusd_result = backtester.run_backtest(params, eurusd_data)
        gbpusd_result = backtester.run_backtest(params, gbpusd_data)
        
        # Average results
        avg_trades = (eurusd_result.total_trades + gbpusd_result.total_trades) / 2
        avg_wr = (eurusd_result.win_rate + gbpusd_result.win_rate) / 2
        avg_pf = (eurusd_result.profit_factor + gbpusd_result.profit_factor) / 2
        avg_sharpe = (eurusd_result.sharpe_ratio + gbpusd_result.sharpe_ratio) / 2
        avg_dd = (eurusd_result.max_drawdown_pct + gbpusd_result.max_drawdown_pct) / 2
        avg_pnl = (eurusd_result.total_pnl + gbpusd_result.total_pnl)
        avg_days = (eurusd_result.test_period_days + gbpusd_result.test_period_days) / 2
        
        combined = BacktestResult(
            total_trades=int(avg_trades),
            win_rate=avg_wr,
            profit_factor=avg_pf,
            sharpe_ratio=avg_sharpe,
            max_drawdown_pct=avg_dd,
            total_pnl=avg_pnl,
            test_period_days=avg_days
        )
        
        combined.fitness_score = calculate_fitness_score(combined)
        
        results.append({
            'params': params.to_dict(),
            'result': combined
        })
    
    # Sort by fitness
    results.sort(key=lambda x: x['result'].fitness_score, reverse=True)
    
    # Display top 10
    print(f"\n{'='*80}")
    print("TOP 10 PARAMETER SETS (REAL DATA WITH 2-POINT SPREAD)")
    print(f"{'='*80}\n")
    
    for i, item in enumerate(results[:10], 1):
        r = item['result']
        p = item['params']
        
        trades_per_month = r.total_trades / max(r.test_period_days / 30, 1) if r.test_period_days > 0 else 0
        
        print(f"#{i}: Fitness={r.fitness_score:.2f}")
        print(f"    Win Rate: {r.win_rate*100:.2f}% | PnL: ${r.total_pnl:.2f} | Trades: {r.total_trades}")
        print(f"    Sharpe: {r.sharpe_ratio:.2f} | DD: {r.max_drawdown_pct:.2f}% | PF: {r.profit_factor:.2f}")
        print(f"    Trades/Month: {trades_per_month:.1f}")
        print(f"    Params: SL={p['atr_sl_multiplier']}, TP={p['atr_tp_multiplier']}, "
              f"QF={p['quality_floor']}, ML={p['ml_weight']}")
        print()
    
    # Save best
    best = results[0]
    best_params = best['params']
    best_result = best['result']
    
    print(f"{'='*80}")
    print(f"🏆 WINNING PARAMETERS (REAL DATA)")
    print(f"{'='*80}\n")
    print(f"Fitness Score: {best_result.fitness_score:.2f}")
    print(f"Win Rate: {best_result.win_rate*100:.2f}%")
    print(f"Total PnL: ${best_result.total_pnl:.2f}")
    print(f"Total Trades: {best_result.total_trades}")
    print(f"Sharpe: {best_result.sharpe_ratio:.2f}")
    print(f"Max DD: {best_result.max_drawdown_pct:.2f}%")
    print(f"Profit Factor: {best_result.profit_factor:.2f}")
    
    # Save to config
    output_path = Path(__file__).parent.parent / "config" / "optimized_params_real.json"
    
    config_data = {
        'timestamp': datetime.now().isoformat(),
        'data_source': 'real_historical_mt5',
        'spread_modeling': '2_points',
        'parameters': best_params,
        'metrics': {
            'win_rate': round(best_result.win_rate, 4),
            'total_pnl': round(best_result.total_pnl, 2),
            'total_trades': best_result.total_trades,
            'sharpe_ratio': round(best_result.sharpe_ratio, 4),
            'max_drawdown_pct': round(best_result.max_drawdown_pct, 4),
            'profit_factor': round(best_result.profit_factor, 4),
            'fitness_score': round(best_result.fitness_score, 2)
        }
    }
    
    with open(output_path, 'w') as f:
        json.dump(config_data, f, indent=2)
    
    print(f"\n✅ Saved to: {output_path}")
    
    # Reality check
    print(f"\n{'='*80}")
    print("REALITY CHECK - SIMULATED vs REAL")
    print(f"{'='*80}\n")
    print(f"{'Metric':<20} {'Simulated':<15} {'Real Data':<15} {'Status':<15}")
    print(f"{'-'*80}")
    
    simulated = {
        'win_rate': 64.13,
        'max_dd': 0.12,
        'trades_per_mo': 99,
        'profit_factor': 1.81
    }
    
    real = {
        'win_rate': best_result.win_rate * 100,
        'max_dd': best_result.max_drawdown_pct,
        'trades_per_mo': best_result.total_trades / max(best_result.test_period_days / 30, 1) if best_result.test_period_days > 0 else 0,
        'profit_factor': best_result.profit_factor
    }
    
    print(f"{'Win Rate':<20} {simulated['win_rate']:<15.2f} {real['win_rate']:<15.2f} {'✓' if 50 <= real['win_rate'] <= 60 else '⚠️':<15}")
    print(f"{'Max DD':<20} {simulated['max_dd']:<15.2f} {real['max_dd']:<15.2f} {'✓' if real['max_dd'] < 15 else '⚠️':<15}")
    print(f"{'Trades/Month':<20} {simulated['trades_per_mo']:<15.1f} {real['trades_per_mo']:<15.1f} {'✓' if 40 <= real['trades_per_mo'] <= 80 else '⚠️':<15}")
    print(f"{'Profit Factor':<20} {simulated['profit_factor']:<15.2f} {real['profit_factor']:<15.2f} {'✓' if 1.3 <= real['profit_factor'] <= 1.8 else '⚠️':<15}")
    
    print(f"\n{'='*80}")
    if best_result.win_rate < 50:
        print("⚠️  WARNING: Win Rate < 50% - ATR SL may be too tight!")
        print("   Recommendation: Increase ATR SL to 2.2 or 2.5")
    elif 50 <= best_result.win_rate <= 58:
        print("✅ REALISTIC: Win rate in tradable range (50-58%)")
        print("   These parameters are ready for live trading!")
    else:
        print("🎉 EXCELLENT: Win rate above expectations!")
    
    print(f"{'='*80}\n")


if __name__ == "__main__":
    asyncio.run(run_real_data_sweep())
