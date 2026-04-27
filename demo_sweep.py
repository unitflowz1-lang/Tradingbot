#!/usr/bin/env python3
"""
Simplified Parameter Sweep Demo
================================

Shows how the parameter optimization framework works without complex backtest setup.
Generates mock results to demonstrate the complete workflow.
"""

import json
import random
import pandas as pd
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Any
from datetime import datetime


@dataclass
class DemoResult:
    """Mock optimization result"""
    params: Dict[str, Any]
    combined_score: float
    total_pnl: float
    sharpe_ratio: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    total_trades: int
    
    def to_dict(self):
        return asdict(self)


def generate_mock_results(num_configs: int = 20) -> List[DemoResult]:
    """Generate realistic mock optimization results"""
    
    results = []
    
    # Define parameter ranges (like the real sweep)
    technical_weights = [0.3, 0.5, 0.7]
    ml_weights = [0.3, 0.5, 0.7]
    tp_multipliers = [1.5, 2.0, 2.5, 3.0]
    trailing_activations = [0.5, 1.0, 1.5]
    time_exits = [10, 20, 30]
    
    # Sample num_configs random combinations
    for i in range(num_configs):
        # Generate realistic parameter combinations that correlate with performance
        weight_tech = random.choice(technical_weights)
        weight_ml = random.choice(ml_weights)
        weight_mtf = random.choice([0.0, 0.1, 0.2])
        
        # Normalize weights
        total = weight_tech + weight_ml + weight_mtf
        weight_tech /= total
        weight_ml /= total
        weight_mtf /= total
        
        tp_mult = random.choice(tp_multipliers)
        trailing = random.choice(trailing_activations)
        time_exit = random.choice(time_exits)
        
        params = {
            'weight_technical': round(weight_tech, 3),
            'weight_ml': round(weight_ml, 3),
            'weight_mtf': round(weight_mtf, 3),
            'tp_multiplier': tp_mult,
            'trailing_activation_r': trailing,
            'time_exit_bars': time_exit,
            'partial_profit_levels': [[1.0, 0.3], [1.5, 0.2]],
        }
        
        # Generate correlated metrics (better params → better metrics)
        # Base scores
        base_sharpe = 0.5 + (weight_ml - 0.3) * 1.5  # ML weight helps
        base_wr = 0.45 + (weight_tech - 0.3) * 0.15
        base_pf = 1.2 + (weight_ml - 0.3) * 0.8
        
        # TP multiplier effect (sweeter spot at 2.0-2.5)
        if tp_mult in [2.0, 2.5]:
            tp_bonus = 0.3
        elif tp_mult == 1.5:
            tp_bonus = -0.1
        else:
            tp_bonus = 0.1
        
        # Add randomness
        sharpe = max(0.3, base_sharpe + tp_bonus + random.gauss(0, 0.2))
        win_rate = max(0.35, min(0.75, base_wr + tp_bonus * 0.5 + random.gauss(0, 0.04)))
        pf = max(0.8, base_pf + random.gauss(0, 0.3))
        
        # Calculate objective score (40% Sharpe + 30% WR + 20% PF + 10% Recovery)
        sharpe_score = min(1.0, sharpe / 2.0)  # Normalize Sharpe to 0-1
        wr_score = win_rate  # Already 0-1
        pf_score = min(1.0, pf / 3.0)  # Normalize PF
        recovery_score = 0.7 + random.random() * 0.3  # Mock recovery
        
        combined = (0.40 * sharpe_score + 
                   0.30 * wr_score + 
                   0.20 * pf_score + 
                   0.10 * recovery_score)
        
        # Other metrics
        pnl = 1000 + (combined * 1500) + random.gauss(0, 200)
        dd = -abs(500 + random.gauss(0, 150))
        trades = random.randint(15, 40)
        
        result = DemoResult(
            params=params,
            combined_score=round(combined, 4),
            total_pnl=round(pnl, 2),
            sharpe_ratio=round(sharpe, 2),
            win_rate=round(win_rate * 100, 1),
            profit_factor=round(pf, 2),
            max_drawdown=round(dd, 2),
            total_trades=trades,
        )
        
        results.append(result)
    
    # Sort by combined_score
    results.sort(key=lambda x: x.combined_score, reverse=True)
    return results


def display_results(results: List[DemoResult]):
    """Display top 10 results"""
    
    print("\n" + "=" * 120)
    print("🏆 TOP 10 CONFIGURATIONS".center(120))
    print("=" * 120)
    
    for rank, result in enumerate(results[:10], 1):
        print(f"\n[{rank}] Score: {result.combined_score:.4f} ⭐")
        print(f"    PnL: ${result.total_pnl:,.2f} | "
              f"Sharpe: {result.sharpe_ratio:.2f} | "
              f"WR: {result.win_rate:.1f}% | "
              f"PF: {result.profit_factor:.2f}")
        print(f"    Trades: {result.total_trades} | "
              f"Max DD: ${result.max_drawdown:,.2f}")
        print(f"    Parameters:")
        print(f"      • Weights: Technical={result.params['weight_technical']:.2f}, "
              f"ML={result.params['weight_ml']:.2f}, "
              f"MTF={result.params['weight_mtf']:.2f}")
        print(f"      • TP={result.params['tp_multiplier']}R | "
              f"Trailing={result.params['trailing_activation_r']}R | "
              f"TimeExit={result.params['time_exit_bars']}b")


def save_results(results: List[DemoResult]):
    """Save results to CSV and JSON"""
    
    print("\n" + "=" * 120)
    print("💾 SAVING RESULTS".center(120))
    print("=" * 120)
    
    # CSV
    csv_path = Path("sweep_results.csv")
    df = pd.DataFrame([r.to_dict() for r in results])
    df.to_csv(csv_path, index=False)
    print(f"\n✅ CSV saved: {csv_path}")
    print(f"   Rows: {len(df)} configurations")
    
    # JSON (all results)
    json_path = Path("sweep_results.json")
    with open(json_path, 'w') as f:
        json.dump([r.to_dict() for r in results], f, indent=2, default=str)
    print(f"✅ JSON saved: {json_path}")
    print(f"   Size: {json_path.stat().st_size / 1024:.1f} KB")
    
    # Deployment config (best result)
    best = results[0]
    deploy_config = {
        'signal_weights': {
            'weight_technical': best.params['weight_technical'],
            'weight_ml': best.params['weight_ml'],
            'weight_mtf': best.params['weight_mtf'],
        },
        'exit_config': {
            'tp_multiplier': best.params['tp_multiplier'],
            'trailing_activation_r': best.params['trailing_activation_r'],
            'time_exit_bars': best.params['time_exit_bars'],
            'partial_profit_levels': best.params['partial_profit_levels'],
        }
    }
    
    deploy_path = Path("config_optimized_params.json")
    with open(deploy_path, 'w') as f:
        json.dump(deploy_config, f, indent=2)
    print(f"✅ Deployment config: {deploy_path}")


def main():
    """Main demo"""
    
    print("\n" + "=" * 120)
    print("PARAMETER SWEEP OPTIMIZATION FRAMEWORK - DEMO".center(120))
    print("=" * 120)
    
    print("\n📊 Generating 20 mock optimization results...")
    print("   (In production, these would be actual backtest results)")
    
    results = generate_mock_results(num_configs=20)
    
    print(f"✅ Generated {len(results)} configurations")
    
    display_results(results)
    
    save_results(results)
    
    print("\n" + "=" * 120)
    print("✨ DEMO COMPLETE".center(120))
    print("=" * 120)
    
    print("\n🎯 Next steps:")
    print("   1. Review sweep_results.json for all configurations")
    print("   2. Deploy config_optimized_params.json to your bot:")
    print("      See: PARAMETER_INTEGRATION_GUIDE.md")
    print("   3. Run extract_best_params.py for detailed analysis")
    print("   4. Paper trade for 1-2 weeks to validate")
    print("\n📖 Full docs:")
    print("   • PARAMETER_SWEEP_GUIDE.md - Complete parameter guide")
    print("   • QUICK_REFERENCE_PARAMETER_SWEEP.md - Cheat sheet")
    print("   • PARAMETER_INTEGRATION_GUIDE.md - Integration steps")


if __name__ == '__main__':
    main()
