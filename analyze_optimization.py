"""
Optimization Results Analyzer
Compares and ranks backtesting results to find optimal parameters
"""

import json
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime


class ResultsAnalyzer:
    """Analyzes and compares optimization results"""
    
    def __init__(self, results_dir: str = "optimization_results"):
        self.results_dir = Path(results_dir)
        self.results = []
        self.analysis = {}
    
    def load_results(self, filename: str = "optimization_results.json"):
        """Load results from file"""
        filepath = self.results_dir / filename
        if not filepath.exists():
            print(f"❌ Results file not found: {filepath}")
            return False
        
        try:
            with open(filepath, 'r') as f:
                self.results = json.load(f)
            print(f"✅ Loaded {len(self.results)} results")
            return True
        except Exception as e:
            print(f"❌ Error loading results: {e}")
            return False
    
    def analyze(self) -> Dict:
        """Analyze results comprehensively"""
        if not self.results:
            return {}
        
        # Filter successful backtests
        successful = [r for r in self.results if r.get('success') and r.get('metrics')]
        
        if not successful:
            return {'error': 'No successful results'}
        
        metrics_list = [r['metrics'] for r in successful]
        df = pd.DataFrame(metrics_list)
        
        # Get configs for each result
        for i, r in enumerate(successful):
            config = r.get('config', {})
            df.loc[i, 'atr_period'] = config.get('atr_period')
            df.loc[i, 'risk_ratio'] = config.get('risk_reward_ratio')
            df.loc[i, 'filter'] = config.get('entry_filter', {}).get('name', 'UNKNOWN')
            df.loc[i, 'config_name'] = r.get('config_name', '')
        
        self.analysis = {
            'total_tested': len(self.results),
            'successful': len(successful),
            'failed': len(self.results) - len(successful),
            'dataframe': df,
            'stats': self._calculate_stats(df),
            'rankings': self._rank_configs(df, successful)
        }
        
        return self.analysis
    
    def _calculate_stats(self, df: pd.DataFrame) -> Dict:
        """Calculate statistical summary"""
        return {
            'avg_pnl': df['total_pnl'].mean(),
            'median_pnl': df['total_pnl'].median(),
            'max_pnl': df['total_pnl'].max(),
            'min_pnl': df['total_pnl'].min(),
            'std_pnl': df['total_pnl'].std(),
            'avg_win_rate': df['win_rate'].mean(),
            'avg_profit_factor': df['profit_factor'].mean(),
            'avg_max_drawdown': df['max_drawdown'].mean(),
        }
    
    def _rank_configs(self, df: pd.DataFrame, successful: List) -> Dict:
        """Rank configurations by different metrics"""
        rankings = {}
        
        # By Profit Factor (best overall metric)
        rankings['by_profit_factor'] = self._rank_by_metric(
            df, successful, 'profit_factor', reverse=True
        )
        
        # By Total PnL
        rankings['by_total_pnl'] = self._rank_by_metric(
            df, successful, 'total_pnl', reverse=True
        )
        
        # By Win Rate
        rankings['by_win_rate'] = self._rank_by_metric(
            df, successful, 'win_rate', reverse=True
        )
        
        # By Sharpe Ratio (Risk-adjusted return)
        df['sharpe_ratio'] = df['total_pnl'] / (df['max_drawdown'] + 0.001)
        rankings['by_sharpe_ratio'] = self._rank_by_metric(
            df, successful, 'sharpe_ratio', reverse=True
        )
        
        # Best Risk:Reward (high profit factor, low drawdown)
        df['risk_reward_score'] = (df['profit_factor'] * 100) / (df['max_drawdown'] + 1)
        rankings['by_risk_reward'] = self._rank_by_metric(
            df, successful, 'risk_reward_score', reverse=True
        )
        
        return rankings
    
    def _rank_by_metric(self, df: pd.DataFrame, successful: List, 
                       metric: str, reverse: bool = True) -> List[Tuple]:
        """Rank configs by a specific metric"""
        if metric not in df.columns:
            return []
        
        sorted_indices = df[metric].argsort(reverse=reverse)
        top_5 = []
        
        for i, idx in enumerate(sorted_indices[:5], 1):
            result = successful[idx]
            config = result.get('config', {})
            metrics = result.get('metrics', {})
            
            top_5.append({
                'rank': i,
                'config_name': result.get('config_name', ''),
                'atr_period': config.get('atr_period'),
                'risk_ratio': config.get('risk_reward_ratio'),
                'filter': config.get('entry_filter', {}).get('name', ''),
                metric: df.loc[idx, metric],
                'pnl': metrics.get('total_pnl', 0),
                'win_rate': metrics.get('win_rate', 0),
                'profit_factor': metrics.get('profit_factor', 0),
            })
        
        return top_5
    
    def print_report(self):
        """Print detailed analysis report"""
        if not self.analysis:
            print("❌ No analysis data. Run analyze() first.")
            return
        
        print("\n" + "="*80)
        print("   OPTIMIZATION ANALYSIS REPORT")
        print("="*80)
        
        print(f"\n📊 RESULTS SUMMARY:")
        print(f"  Total Tests: {self.analysis['total_tested']}")
        print(f"  Successful: {self.analysis['successful']}")
        print(f"  Failed: {self.analysis['failed']}")
        
        stats = self.analysis['stats']
        print(f"\n📈 STATISTICS:")
        print(f"  Avg PnL: ${stats['avg_pnl']:.2f}")
        print(f"  Median PnL: ${stats['median_pnl']:.2f}")
        print(f"  Best PnL: ${stats['max_pnl']:.2f}")
        print(f"  Worst PnL: ${stats['min_pnl']:.2f}")
        print(f"  Std Dev: ${stats['std_pnl']:.2f}")
        print(f"  Avg Win Rate: {stats['avg_win_rate']:.1f}%")
        print(f"  Avg Profit Factor: {stats['avg_profit_factor']:.2f}")
        print(f"  Avg Max Drawdown: {stats['avg_max_drawdown']:.1f}%")
        
        # Show rankings
        self._print_rankings()
        
        print("\n" + "="*80)
    
    def _print_rankings(self):
        """Print top configurations by different metrics"""
        rankings = self.analysis.get('rankings', {})
        
        print(f"\n🏆 TOP 5 BY PROFIT FACTOR (Best Overall):")
        for item in rankings.get('by_profit_factor', []):
            print(f"  {item['rank']}. {item['config_name']}")
            print(f"     ATR: {item['atr_period']} | Risk:Reward: {item['risk_ratio']} | Filter: {item['filter']}")
            print(f"     Profit Factor: {item['profit_factor']:.2f} | PnL: ${item['pnl']:.2f} | Win: {item['win_rate']:.1f}%")
        
        print(f"\n💰 TOP 5 BY TOTAL PnL:")
        for item in rankings.get('by_total_pnl', []):
            print(f"  {item['rank']}. {item['config_name']}: ${item['pnl']:.2f}")
        
        print(f"\n🎯 TOP 5 BY RISK:REWARD RATIO (Risk-Adjusted):")
        for item in rankings.get('by_risk_reward', []):
            print(f"  {item['rank']}. {item['config_name']}")
            print(f"     Profit Factor: {item['profit_factor']:.2f} | Win Rate: {item['win_rate']:.1f}%")
    
    def export_csv(self, filename: str = "optimization_analysis.csv"):
        """Export results to CSV for further analysis"""
        if 'dataframe' not in self.analysis:
            print("❌ No dataframe to export. Run analyze() first.")
            return
        
        filepath = self.results_dir / filename
        df = self.analysis['dataframe']
        
        # Select key columns
        export_cols = [
            'config_name', 'atr_period', 'risk_ratio', 'filter',
            'trades', 'win_rate', 'total_pnl', 'profit_factor', 
            'max_drawdown', 'final_balance'
        ]
        
        export_cols = [c for c in export_cols if c in df.columns]
        df[export_cols].to_csv(filepath, index=False)
        
        print(f"✅ Exported to {filepath}")
    
    def get_best_config(self, metric: str = 'profit_factor') -> Dict:
        """Get best configuration by specified metric"""
        rankings = self.analysis.get('rankings', {})
        
        if metric == 'profit_factor':
            top = rankings.get('by_profit_factor', [])
        elif metric == 'pnl':
            top = rankings.get('by_total_pnl', [])
        elif metric == 'win_rate':
            top = rankings.get('by_win_rate', [])
        elif metric == 'risk_reward':
            top = rankings.get('by_risk_reward', [])
        else:
            return {}
        
        if top:
            return top[0]
        return {}


def main():
    """Main entry point"""
    analyzer = ResultsAnalyzer()
    
    # Load and analyze results
    if analyzer.load_results():
        analyzer.analyze()
        analyzer.print_report()
        analyzer.export_csv()
        
        # Get best configuration
        best = analyzer.get_best_config('profit_factor')
        if best:
            print(f"\n🎯 RECOMMENDED FOR LIVE TRADING:")
            print(f"   Configuration: {best['config_name']}")
            print(f"   ATR Period: {best['atr_period']}")
            print(f"   Risk:Reward Ratio: {best['risk_ratio']}")
            print(f"   Entry Filter: {best['filter']}")


if __name__ == "__main__":
    main()
