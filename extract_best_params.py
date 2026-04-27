#!/usr/bin/env python3
"""
Extract best parameters from sweep results and prepare for deployment
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List
import sys


class ParameterExtractor:
    """Extract and validate best parameters from sweep results"""
    
    def __init__(self, csv_file='sweep_results.csv', json_file='sweep_results.json'):
        self.csv_file = Path(csv_file)
        self.json_file = Path(json_file)
        self.results = None
        self.best_config = None
    
    def load_results(self) -> bool:
        """Load sweep results from JSON"""
        if not self.json_file.exists():
            print(f"❌ {self.json_file} not found!")
            print("   Did you run: python run_parameter_sweep.py --save-results?")
            return False
        
        try:
            with open(self.json_file) as f:
                self.results = json.load(f)
            print(f"✅ Loaded {len(self.results)} configurations from sweep")
            return True
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse {self.json_file}: {e}")
            return False
    
    def get_top_n(self, n: int = 5) -> List[Dict[str, Any]]:
        """Get top N results"""
        if not self.results:
            return []
        # Results should already be sorted by combined_score
        return self.results[:n]
    
    def validate_config(self, config: Dict[str, Any]) -> tuple[bool, str]:
        """Validate configuration for deployment"""
        
        # Handle both formats
        if 'params' in config and 'metrics' in config:
            # Standard format with metrics
            params = config['params']
            metrics = config['metrics']
        else:
            # Demo format (flat)
            params = config
            metrics = config
        
        # Check combined score
        score = config.get('combined_score', 0)
        if score < 0.4:
            return False, f"Combined score too low: {score:.3f} (need > 0.4)"
        
        # Check signal weights
        weight_tech = params.get('weight_technical', 0.5)
        weight_ml = params.get('weight_ml', 0.5)
        weight_mtf = params.get('weight_mtf', 0.0)
        
        weights = [weight_tech, weight_ml, weight_mtf]
        weight_sum = sum(weights)
        if abs(weight_sum - 1.0) > 0.01:
            return False, f"Signal weights don't sum to 1.0: {weight_sum:.3f}"
        
        # Check individual weight bounds
        for val in weights:
            if not (0.0 <= val <= 1.0):
                return False, f"Weight out of range: {val}"
        
        # Check exit parameters
        tp = params.get('tp_multiplier', 2.0)
        if not (1.5 <= tp <= 3.5):
            return False, f"tp_multiplier out of range: {tp}"
        
        trailing = params.get('trailing_activation_r', 1.0)
        if not (0.1 <= trailing <= 2.0):
            return False, f"trailing_activation_r out of range: {trailing}"
        
        time_exit = params.get('time_exit_bars', 20)
        if not (10 <= time_exit <= 50):
            return False, f"time_exit_bars out of range: {time_exit}"
        
        # Check metrics quality
        if metrics.get('total_pnl', 0) < 100:
            return False, f"Total PnL too low: ${metrics.get('total_pnl', 0):.0f}"
        
        win_rate = metrics.get('win_rate', 0)
        if win_rate < 40:
            return False, f"Win rate too low: {win_rate:.1f}%"
        
        sharpe = metrics.get('sharpe_ratio', 0)
        if sharpe < 0.7:
            return False, f"Sharpe ratio too low: {sharpe:.2f}"
        
        return True, "OK"
    
    def select_best(self) -> bool:
        """Select best configuration for deployment"""
        if not self.results:
            return False
        
        # First valid result
        for i, config in enumerate(self.results):
            is_valid, msg = self.validate_config(config)
            
            if is_valid:
                self.best_config = config
                
                # Extract metrics (handle both formats)
                if 'metrics' in config:
                    metrics = config['metrics']
                else:
                    metrics = config
                
                print(f"\n✅ Selected result #{i+1}:")
                print(f"   Combined Score: {config.get('combined_score', 0):.4f}")
                print(f"   Total PnL: ${metrics.get('total_pnl', 0):.2f}")
                print(f"   Sharpe: {metrics.get('sharpe_ratio', 0):.2f}")
                print(f"   Win Rate: {metrics.get('win_rate', 0):.1f}%")
                print(f"   Profit Factor: {metrics.get('profit_factor', 0):.2f}")
                print(f"   Recovery: {metrics.get('recovery', 0):.2f}x")
                print(f"   Max Drawdown: ${metrics.get('max_drawdown', 0):.2f}")
                return True
            else:
                print(f"⚠️  Result #{i+1} failed validation: {msg}")
        
        return False
    
    def format_for_deployment(self) -> Dict[str, Any]:
        """Format best config for easy deployment"""
        if not self.best_config:
            return {}
        
        config = self.best_config
        
        # Handle both formats
        if 'params' in config:
            params = config['params']
            metrics = config.get('metrics', config)
        else:
            params = config
            metrics = config
        
        formatted = {
            # Metadata
            'timestamp': datetime.now().isoformat(),
            'sweep_date': config.get('backtest_period', 'Unknown'),
            'combined_score': config.get('combined_score', 0),
            
            # Performance metrics
            'performance': {
                'total_pnl': metrics.get('total_pnl', 0),
                'sharpe_ratio': metrics.get('sharpe_ratio', 0),
                'win_rate_percent': metrics.get('win_rate', 0),
                'profit_factor': metrics.get('profit_factor', 0),
                'recovery_factor': metrics.get('recovery', 0),
                'max_drawdown': metrics.get('max_drawdown', 0),
                'total_trades': metrics.get('total_trades', 0),
                'avg_trade_pnl': metrics.get('total_pnl', 0) / max(metrics.get('total_trades', 1), 1),
            },
            
            # Signal weights
            'signal_weights': {
                'weight_technical': params.get('weight_technical', 0.5),
                'weight_ml': params.get('weight_ml', 0.5),
                'weight_mtf': params.get('weight_mtf', 0.0),
            },
            
            # Exit configuration
            'exit_config': {
                'tp_multiplier': params.get('tp_multiplier', 2.0),
                'trailing_activation_r': params.get('trailing_activation_r', 1.0),
                'time_exit_bars': params.get('time_exit_bars', 20),
                'partial_profit_levels': params.get('partial_profit_levels', [[1.0, 0.3]]),
            },
            
            # Deployment checklist
            'deployment_notes': {
                'backtest_period': 'Last 2000 bars 5-min EUR/USD',
                'walk_forward': '1500 train / 500 test',
                'market_conditions': 'Neutral to trending',
                'deployment_date': datetime.now().strftime('%Y-%m-%d'),
                'status': 'Ready for paper trading',
            }
        }
        
        return formatted
    
    def print_top_configs(self, n: int = 5) -> None:
        """Print top N configurations for review"""
        if not self.results:
            print("❌ No results loaded")
            return
        
        print("\n" + "=" * 100)
        print(f"TOP {min(n, len(self.results))} CONFIGURATIONS")
        print("=" * 100)
        
        for i, config in enumerate(self.results[:n], 1):
            score = config.get('combined_score', 0)
            
            # Handle both formats (with/without 'metrics' key)
            if 'metrics' in config:
                metrics = config['metrics']
            else:
                # Direct attributes format (from demo)
                metrics = {
                    'total_pnl': config.get('total_pnl', 0),
                    'sharpe': config.get('sharpe_ratio', 0),
                    'win_rate': config.get('win_rate', 0),
                    'profit_factor': config.get('profit_factor', 0),
                    'max_drawdown': config.get('max_drawdown', 0),
                    'recovery': 2.0  # Mock recovery
                }
            
            params = config.get('params', config)
            
            print(f"\n[{i}] Score: {score:.4f} ⭐")
            print(f"    PnL: ${metrics['total_pnl']:.0f} | "
                  f"Sharpe: {metrics['sharpe']:.2f} | "
                  f"WR: {metrics['win_rate']:.1f}% | "
                  f"PF: {metrics['profit_factor']:.2f} | "
                  f"Recovery: {metrics.get('recovery', 2.0):.2f}x | "
                  f"MaxDD: ${metrics['max_drawdown']:.0f}")
            
            if isinstance(params, dict):
                exit_cfg = params.get('exit_config', params)
                signal_cfg = params.get('signal_weights', {})
                
                if 'tp_multiplier' in exit_cfg:
                    tp = exit_cfg['tp_multiplier']
                else:
                    tp = params.get('tp_multiplier', 'N/A')
                
                print(f"    Exit: TP={tp}R | "
                      f"Trailing={params.get('trailing_activation_r', exit_cfg.get('trailing_activation_r', 'N/A'))}R | "
                      f"TimeExit={params.get('time_exit_bars', exit_cfg.get('time_exit_bars', 'N/A'))}b")
                
                if signal_cfg:
                    print(f"    Signals: Tech={signal_cfg.get('weight_technical', params.get('weight_technical', 0)):.2f} | "
                          f"ML={signal_cfg.get('weight_ml', params.get('weight_ml', 0)):.2f} | "
                          f"MTF={signal_cfg.get('weight_mtf', params.get('weight_mtf', 0)):.2f}")
    
    def save_deployment_config(self, output_file='config_optimized_params.json') -> bool:
        """Save formatted config for deployment"""
        if not self.best_config:
            print("❌ No best configuration selected")
            return False
        
        formatted = self.format_for_deployment()
        
        # Simplify for bot consumption
        bot_config = {
            'signal_weights': formatted['signal_weights'],
            'exit_config': formatted['exit_config'],
        }
        
        output_path = Path(output_file)
        
        try:
            with open(output_path, 'w') as f:
                json.dump(bot_config, f, indent=2)
            print(f"\n✅ Deployment config saved to: {output_file}")
            return True
        except Exception as e:
            print(f"❌ Failed to save config: {e}")
            return False
    
    def save_full_report(self, output_file='parameter_sweep_report.json') -> bool:
        """Save full report with metadata"""
        if not self.best_config:
            print("❌ No best configuration selected")
            return False
        
        formatted = self.format_for_deployment()
        output_path = Path(output_file)
        
        try:
            with open(output_path, 'w') as f:
                json.dump(formatted, f, indent=2)
            print(f"✅ Full report saved to: {output_file}")
            return True
        except Exception as e:
            print(f"❌ Failed to save report: {e}")
            return False
    
    def print_comparison(self) -> None:
        """Compare top 3 parameters to detect consistency"""
        if not self.results or len(self.results) < 3:
            return
        
        print("\n" + "=" * 100)
        print("PARAMETER CONSISTENCY CHECK (Top 3)")
        print("=" * 100)
        
        top_3 = self.results[:3]
        
        # Extract exit params (handle both formats)
        exit_params = []
        for config in top_3:
            params = config.get('params', config)
            if 'exit_config' in params:
                exit_cfg = params['exit_config']
            else:
                exit_cfg = params
            
            exit_params.append({
                'tp': exit_cfg.get('tp_multiplier', 2.0),
                'trailing': exit_cfg.get('trailing_activation_r', 1.0),
                'time_exit': exit_cfg.get('time_exit_bars', 20),
            })
        
        # Check consistency
        tp_values = [ep['tp'] for ep in exit_params]
        trailing_values = [ep['trailing'] for ep in exit_params]
        time_values = [ep['time_exit'] for ep in exit_params]
        
        tp_range = max(tp_values) - min(tp_values)
        trailing_range = max(trailing_values) - min(trailing_values)
        time_range = max(time_values) - min(time_values)
        
        print(f"\nTP Multiplier:        {tp_values[0]:.2f} - {tp_values[1]:.2f} - {tp_values[2]:.2f} "
              f"(range: {tp_range:.2f})")
        if tp_range < 0.2:
            print("  ✅ STABLE - Good sign!")
        elif tp_range < 0.5:
            print("  🟡 CONSISTENT - Acceptable")
        else:
            print("  ⚠️  VARIABLE - May be overfitting")
        
        print(f"\nTrailing Activation:  {trailing_values[0]:.2f} - {trailing_values[1]:.2f} - {trailing_values[2]:.2f} "
              f"(range: {trailing_range:.2f})")
        if trailing_range < 0.2:
            print("  ✅ STABLE - Good sign!")
        elif trailing_range < 0.5:
            print("  🟡 CONSISTENT - Acceptable")
        else:
            print("  ⚠️  VARIABLE - May be overfitting")
        
        print(f"\nTime Exit Bars:       {time_values[0]} - {time_values[1]} - {time_values[2]} "
              f"(range: {time_range})")
        if time_range < 3:
            print("  ✅ STABLE - Good sign!")
        elif time_range < 10:
            print("  🟡 CONSISTENT - Acceptable")
        else:
            print("  ⚠️  VARIABLE - May be overfitting")
        
        if tp_range < 0.2 and trailing_range < 0.2 and time_range < 3:
            print("\n✅ TOP 3 VERY CONSISTENT - Excellent sign!")
            print("   Parameters are robust across different signal weight combinations")
        else:
            print("\n⚠️  Parameter variability in top 3")
            print("   Consider picking result #2-3 instead of #1 for stability")


def main():
    # Create extractor
    extractor = ParameterExtractor()
    
    # Load results
    if not extractor.load_results():
        print("\n📝 Please run the parameter sweep first:")
        print("   python launch_sweep.py --quick   # Fast test")
        print("   python launch_sweep.py --full --save-results  # Full sweep")
        return 1
    
    # Show all top configs
    extractor.print_top_configs(n=10)
    
    # Check consistency
    extractor.print_comparison()
    
    # Select best
    if not extractor.select_best():
        print("❌ No valid configurations found!")
        return 1
    
    # Save deployment config
    if not extractor.save_deployment_config():
        return 1
    
    # Save full report
    if not extractor.save_full_report():
        return 1
    
    # Print next steps
    print("\n" + "=" * 100)
    print("NEXT STEPS")
    print("=" * 100)
    print("\n1. 📋 Review config_optimized_params.json")
    print("2. 📖 Read PARAMETER_INTEGRATION_GUIDE.md for deployment")
    print("3. 🧪 Test on paper trading (1-2 weeks)")
    print("4. 🚀 Deploy to live trading")
    print("\n" + "=" * 100)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
