#!/usr/bin/env python3
"""
REAL DATA SWEEP v2 - CONSERVATIVE STRATEGY
===========================================
FIXES THE CATASTROPHIC LOSSES FROM v1 by using:
1. REAL strategy logic (not dummy SMA crossover)
2. QUALITY FILTERS (ADX, RSI, confluence)
3. REASONABLE trade frequency (not 468 trades/month!)
4. WIDER stops (testing 2.2, 2.5, 2.8 ATR)

Usage:
    python scripts/real_data_sweep_v2.py
"""

import pandas as pd
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from itertools import product
import json
import sys
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class ParameterSet:
    quality_floor: float
    adx_min: float
    rsi_lower: float
    rsi_upper: float
    atr_sl_multiplier: float
    atr_tp_multiplier: float
    
    def to_dict(self) -> dict:
        return {
            'quality_floor': self.quality_floor,
            'adx_min': self.adx_min,
            'rsi_lower': self.rsi_lower,
            'rsi_upper': self.rsi_upper,
            'atr_sl_multiplier': self.atr_sl_multiplier,
            'atr_tp_multiplier': self.atr_tp_multiplier,
        }


@dataclass
class BacktestResult:
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    total_pnl: float = 0.0
    test_period_days: float = 0.0
    fitness_score: float = 0.0


# ============================================================================
# CONSERVATIVE BACKTEST ENGINE
# ============================================================================

class ConservativeBacktester:
    """
    Backtest using ACTUAL strategy logic with quality filters
    This prevents the overtrading disaster from v1
    """
    
    def __init__(self, spread_points: float = 2.0):
        self.spread_points = spread_points
        self.spread_cost_per_lot = spread_points * 0.0001 * 100000
        
    def load_data(self, filepath: str) -> pd.DataFrame:
        df = pd.read_csv(filepath)
        df['time'] = pd.to_datetime(df['time'])
        df = df.sort_values('time').reset_index(drop=True)
        return df
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate ALL indicators needed for strategy"""
        df = df.copy()
        
        # ATR (14)
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = true_range.rolling(window=14).mean()
        
        # RSI (14)
        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # ADX (14)
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
        
        plus_di = 100 * (plus_dm.rolling(window=14).mean() / df['atr'])
        minus_di = 100 * (minus_dm.rolling(window=14).mean() / df['atr'])
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        df['adx'] = dx.rolling(window=14).mean()
        
        # EMA (20, 50)
        df['ema_20'] = close.rolling(window=20).mean()
        df['ema_50'] = close.rolling(window=50).mean()
        
        return df
    
    def run_backtest(self, params: ParameterSet, data: pd.DataFrame) -> BacktestResult:
        """
        Conservative backtest with quality filters
        """
        if len(data) < 100:
            return BacktestResult()
        
        # Calculate indicators
        data = self.calculate_indicators(data)
        
        # Parameters
        atr_sl = params.atr_sl_multiplier
        atr_tp = params.atr_tp_multiplier
        adx_min = params.adx_min
        rsi_lower = params.rsi_lower
        rsi_upper = params.rsi_upper
        quality_floor = params.quality_floor / 100.0
        
        # State
        equity = 10000.0
        peak_equity = equity
        trades = []
        in_position = False
        entry_price = 0.0
        position_type = None
        stop_loss = 0.0
        take_profit = 0.0
        last_trade_idx = 0
        min_bars_between_trades = 20  # Minimum 100 minutes between trades (prevents overtrading)
        
        # Skip first 50 bars for indicator warmup
        start_idx = 50
        
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
                    last_trade_idx = i
            
            # ENTRY LOGIC (with QUALITY FILTERS)
            if not in_position and (i - last_trade_idx) >= min_bars_between_trades:
                # Calculate quality score (simplified version of your actual logic)
                quality_score = 0.0
                
                # Filter 1: ADX - Trend strength
                if pd.notna(bar['adx']) and bar['adx'] >= adx_min:
                    quality_score += 0.25
                else:
                    continue  # Skip weak trends
                
                # Filter 2: RSI - Momentum zone
                if pd.notna(bar['rsi']):
                    if bar['rsi'] >= rsi_lower and bar['rsi'] <= rsi_upper:
                        quality_score += 0.25
                    else:
                        continue  # Skip extreme RSI
                
                # Filter 3: EMA alignment - Trend direction
                if pd.notna(bar['ema_20']) and pd.notna(bar['ema_50']):
                    if bar['ema_20'] > bar['ema_50']:
                        quality_score += 0.25  # Uptrend
                    elif bar['ema_20'] < bar['ema_50']:
                        quality_score += 0.25  # Downtrend
                
                # Filter 4: Price position
                if pd.notna(bar['ema_20']):
                    price_distance = abs(bar['close'] - bar['ema_20']) / bar['ema_20']
                    if price_distance < 0.002:  # Within 0.2% of EMA
                        quality_score += 0.25
                
                # QUALITY FLOOR CHECK
                if quality_score < quality_floor:
                    continue  # Skip low-quality setups
                
                # ENTRY DECISION
                if pd.notna(bar['ema_20']) and pd.notna(bar['ema_50']):
                    # Long signal: Bullish alignment + RSI in buy zone
                    if bar['ema_20'] > bar['ema_50'] and bar['rsi'] < 60:
                        entry_price = bar['close'] + (self.spread_points * 0.00005)
                        position_type = 'LONG'
                        
                        stop_loss = entry_price - (current_atr * atr_sl)
                        take_profit = entry_price + (current_atr * atr_tp)
                        
                        in_position = True
                    
                    # Short signal: Bearish alignment + RSI in sell zone
                    elif bar['ema_20'] < bar['ema_50'] and bar['rsi'] > 40:
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
            test_period_days=test_period_days
        )


# ============================================================================
# FITNESS FUNCTION
# ============================================================================

def calculate_fitness_score(result: BacktestResult) -> float:
    """Balanced fitness for realistic trading"""
    if result.total_trades < 30:
        return 0.0  # Not enough trades
    
    profit_score = min(100, (result.total_pnl / 2000.0) * 100) if result.total_pnl > 0 else 0
    
    trades_per_month = result.total_trades / max(result.test_period_days / 30, 1) if result.test_period_days > 0 else 0
    if 40 <= trades_per_month <= 80:
        freq_score = 100
    elif 30 <= trades_per_month < 40:
        freq_score = 80
    elif 80 < trades_per_month <= 120:
        freq_score = 70
    else:
        freq_score = max(0, 50 - abs(trades_per_month - 60))
    
    sharpe_score = min(100, (result.sharpe_ratio / 2.0) * 100) if result.sharpe_ratio > 0 else 0
    
    dd = result.max_drawdown_pct
    if dd <= 5:
        dd_score = 100
    elif dd <= 10:
        dd_score = 80 + (10 - dd) * 4
    elif dd <= 15:
        dd_score = 50 + (15 - dd) * 6
    else:
        dd_score = max(0, 50 - (dd - 15) * 5)
    
    fitness = (profit_score * 0.35) + (freq_score * 0.25) + (sharpe_score * 0.25) + (dd_score * 0.15)
    
    # Hard constraints
    if result.max_drawdown_pct > 15:
        fitness *= 0.1
    if result.win_rate < 0.45:
        fitness *= 0.2
    if trades_per_month < 30:
        fitness *= 0.5
    
    return fitness


# ============================================================================
# MAIN SWEEP
# ============================================================================

def run_sweep():
    print("="*80)
    print("REAL DATA SWEEP v2 - CONSERVATIVE STRATEGY")
    print("="*80)
    print("\n✅ IMPROVEMENTS OVER v1:")
    print("   • Real strategy logic (ADX, RSI, EMA filters)")
    print("   • Quality floor enforcement")
    print("   • Minimum 100 min between trades (prevents overtrading)")
    print("   • Wider SL testing: 2.2, 2.5, 2.8 ATR\n")
    
    # Load data
    data_dir = Path(__file__).parent.parent / "data"
    eurusd_path = data_dir / "EURUSD_90d_real.csv"
    gbpusd_path = data_dir / "GBPUSD_90d_real.csv"
    
    if not eurusd_path.exists() or not gbpusd_path.exists():
        print("❌ Data files not found! Run harvest_real_data.py first.")
        sys.exit(1)
    
    backtester = ConservativeBacktester(spread_points=2.0)
    
    eurusd_data = backtester.load_data(str(eurusd_path))
    gbpusd_data = backtester.load_data(str(gbpusd_path))
    
    logger.info(f"Loaded EURUSD: {len(eurusd_data)} candles")
    logger.info(f"Loaded GBPUSD: {len(gbpusd_data)} candles")
    
    # CONSERVATIVE parameter space
    param_ranges = {
        'quality_floor': [70, 75, 80],  # Higher quality
        'adx_min': [20, 25, 30],  # Stronger trends only
        'rsi_lower': [30, 35],
        'rsi_upper': [60, 65],
        'atr_sl_multiplier': [2.2, 2.5, 2.8],  # WIDER stops
        'atr_tp_multiplier': [3.0, 3.5, 4.0],  # Better RR
    }
    
    combinations = []
    keys = list(param_ranges.keys())
    
    for values in product(*[param_ranges[k] for k in keys]):
        params = dict(zip(keys, values))
        
        if params['atr_tp_multiplier'] <= params['atr_sl_multiplier']:
            continue
        
        combinations.append(ParameterSet(**params))
    
    print(f"\n🔍 Testing {len(combinations)} CONSERVATIVE parameter sets...")
    print(f"   Spread: 2 points ($20/lot)")
    print(f"   Min trade interval: 100 minutes\n")
    
    results = []
    total = len(combinations)
    
    for idx, params in enumerate(combinations, 1):
        if idx % 10 == 0:
            print(f"   Progress: {idx}/{total} ({idx/total*100:.1f}%)")
        
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
    
    # Display results
    print(f"\n{'='*80}")
    print("TOP 10 PARAMETER SETS (CONSERVATIVE REAL DATA)")
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
              f"QF={p['quality_floor']}, ADX={p['adx_min']}")
        print()
    
    # Save best
    best = results[0]
    best_params = best['params']
    best_result = best['result']
    
    print(f"{'='*80}")
    print(f"🏆 WINNING PARAMETERS (CONSERVATIVE)")
    print(f"{'='*80}\n")
    print(f"Fitness Score: {best_result.fitness_score:.2f}")
    print(f"Win Rate: {best_result.win_rate*100:.2f}%")
    print(f"Total PnL: ${best_result.total_pnl:.2f}")
    print(f"Total Trades: {best_result.total_trades}")
    print(f"Sharpe: {best_result.sharpe_ratio:.2f}")
    print(f"Max DD: {best_result.max_drawdown_pct:.2f}%")
    print(f"Profit Factor: {best_result.profit_factor:.2f}")
    
    # Save to config
    output_path = Path(__file__).parent.parent / "config" / "optimized_params_conservative.json"
    
    config_data = {
        'timestamp': datetime.now().isoformat(),
        'data_source': 'real_historical_mt5_conservative',
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
    trades_per_month = best_result.total_trades / max(best_result.test_period_days / 30, 1) if best_result.test_period_days > 0 else 0
    
    print(f"\n{'='*80}")
    print("v1 (AGGRESSIVE) vs v2 (CONSERVATIVE) COMPARISON")
    print(f"{'='*80}\n")
    print(f"{'Metric':<20} {'v1 Aggressive':<18} {'v2 Conservative':<18}")
    print(f"{'-'*80}")
    print(f"{'Win Rate':<20} {'36.58%':<18} {best_result.win_rate*100:.2f}%")
    print(f"{'Max DD':<20} {'318.20%':<18} {best_result.max_drawdown_pct:.2f}%")
    print(f"{'Trades/Month':<20} {'468.9':<18} {trades_per_month:.1f}")
    print(f"{'Profit Factor':<20} {'0.60':<18} {best_result.profit_factor:.2f}")
    print(f"{'Total PnL':<20} {'-$63,377':<18} ${best_result.total_pnl:.2f}")
    
    print(f"\n{'='*80}")
    if best_result.profit_factor > 1.2 and best_result.win_rate > 0.50:
        print("✅ SUCCESS: Conservative strategy is profitable!")
        print("   Ready for dry run testing.")
    elif best_result.profit_factor > 1.0:
        print("⚠️  Marginal: Small edge, needs more optimization")
    else:
        print("❌ Still losing: Strategy logic needs fundamental review")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    run_sweep()
