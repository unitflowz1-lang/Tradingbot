"""
Complete Stress Test Orchestrator
═══════════════════════════════════════════════════════════════
Masters script that runs all stress tests and generates reports.
"""

import sys
from pathlib import Path

# Add stress_test to path
stress_test_dir = Path(__file__).parent
sys.path.insert(0, str(stress_test_dir))

from adverse_market_generator import AdverseMarketGenerator
from stress_test_simulator import StressTestSimulator
from stress_test_report_generator import StressTestReportGenerator
import json


def main():
    """Run complete stress test suite."""
    print("\n" + "=" * 80)
    print("FOREX TRADING BOT - COMPREHENSIVE STRESS TEST SUITE")
    print("=" * 80)
    print()
    
    # Configuration
    test_config = {
        'initial_capital': 100000.0,
        'risk_per_trade': 0.02,
        'position_sizing_method': 'equity_%',
        'strategies': ['sma', 'mean_reversion', 'breakout'],
        'strategy_weights': {'sma': 0.4, 'mean_reversion': 0.35, 'breakout': 0.25},
    }
    
    # Results storage
    all_results = {}
    
    # Stress scenarios
    scenarios = {
        'flash_crash': {
            'description': 'Sudden sharp market drop with extreme spreads and slippage',
            'pairs': ['EURUSD', 'GBPUSD', 'USDJPY'],
            'candles': 500,
        },
        'sustained_downtrend': {
            'description': 'Prolonged market decline over multiple days',
            'pairs': ['EURUSD', 'GBPUSD', 'USDJPY'],
            'candles': 500,
        },
        'high_volatility': {
            'description': 'Extreme price volatility and whipsaws',
            'pairs': ['EURUSD', 'GBPUSD', 'USDJPY'],
            'candles': 500,
        }
    }
    
    print("🔧 CONFIGURATION")
    print("-" * 80)
    print(f"Initial Capital: ${test_config['initial_capital']:,.2f}")
    print(f"Risk Per Trade: {test_config['risk_per_trade']:.1%}")
    print(f"Position Sizing: {test_config['position_sizing_method']}")
    print(f"Strategies: {', '.join(test_config['strategies'])}")
    print(f"Strategy Weights: {test_config['strategy_weights']}")
    print()
    
    print("📊 STRESS TEST SCENARIOS")
    print("-" * 80)
    for scenario_name, scenario_info in scenarios.items():
        print(f"  • {scenario_name.upper()}")
        print(f"    {scenario_info['description']}")
    print()
    
    # Initialize generators
    market_generator = AdverseMarketGenerator(seed=42)
    report_generator = StressTestReportGenerator()
    
    print("=" * 80)
    print("PHASE 1: GENERATING BASELINE DATA (NORMAL CONDITIONS)")
    print("=" * 80)
    print()
    
    baseline_results = {}
    
    for scenario_name in scenarios.keys():
        print(f"📈 Generating baseline for {scenario_name}...")
        
        baseline_data = market_generator.generate_comparison_baseline(
            pairs=scenarios[scenario_name]['pairs'],
            num_candles=scenarios[scenario_name]['candles'],
        )
        
        baseline_sim = StressTestSimulator(test_config)
        baseline_result = baseline_sim.run_simulation(baseline_data, f"{scenario_name}_baseline")
        baseline_results[scenario_name] = baseline_result
        
        print(f"  ✅ Max Drawdown: {baseline_result['max_drawdown_pct']:.2f}%")
        print(f"  ✅ Signals Generated: {baseline_result['strategy_signals']}")
        print()
    
    print("=" * 80)
    print("PHASE 2: RUNNING STRESS TEST SIMULATIONS")
    print("=" * 80)
    print()
    
    stress_results = {}
    
    for scenario_name, scenario_info in scenarios.items():
        print(f"🔥 STRESS TEST: {scenario_name.upper()}")
        print(f"  {scenario_info['description']}")
        print()
        
        # Generate adverse market data
        print("  Generating adverse market conditions...")
        market_data = market_generator.generate_stress_test_data(
            pairs=scenario_info['pairs'],
            num_candles=scenario_info['candles'],
            scenario=scenario_name,
        )
        
        # Run simulation
        print("  Running bot simulation under stress...")
        stress_sim = StressTestSimulator(test_config)
        stress_result = stress_sim.run_simulation(market_data, scenario_name)
        stress_results[scenario_name] = stress_result
        
        # Export raw data
        stress_sim.export_results(f'stress_test_results/{scenario_name}')
        
        # Key metrics
        print()
        print("  📊 KEY METRICS:")
        print(f"    • Position Sizing Decisions: {stress_result['position_sizing_decisions']}")
        print(f"    • Stop-Loss Events: {stress_result['drawdown_events']}")
        print(f"    • Strategy Signals: {stress_result['strategy_signals']}")
        print(f"    • ML Evaluations: {stress_result['ml_evaluations']}")
        print(f"    • Regime Switches: {stress_result['regime_switches']}")
        print(f"    • Risk Breaches: {stress_result['risk_breaches']}")
        print(f"    • Max Drawdown: {stress_result['max_drawdown_pct']:.2f}%")
        print(f"    • Final Equity: ${stress_result['final_equity']:,.2f}")
        print()
    
    print("=" * 80)
    print("PHASE 3: GENERATING COMPREHENSIVE REPORTS")
    print("=" * 80)
    print()
    
    for scenario_name in scenarios.keys():
        print(f"📝 Generating report for {scenario_name}...")
        
        report_text = report_generator.generate_full_report(
            stress_results[scenario_name],
            baseline_results[scenario_name],
            scenario_name,
            'stress_test_results'
        )
        
        print(f"  ✅ Report saved to stress_test_results/stress_test_report_{scenario_name}.txt")
    
    print()
    
    print("=" * 80)
    print("PHASE 4: GENERATING SUMMARY ANALYSIS")
    print("=" * 80)
    print()
    
    # Generate comparative analysis
    summary = {
        'test_timestamp': str(__import__('datetime').datetime.now().isoformat()),
        'configuration': test_config,
        'baseline_results': baseline_results,
        'stress_results': stress_results,
        'comparative_analysis': {},
    }
    
    print("📊 COMPARATIVE ANALYSIS")
    print("-" * 80)
    print()
    
    for scenario_name in scenarios.keys():
        baseline = baseline_results[scenario_name]
        stress = stress_results[scenario_name]
        
        print(f"Scenario: {scenario_name.upper()}")
        
        # Drawdown comparison
        baseline_dd = baseline['max_drawdown_pct']
        stress_dd = stress['max_drawdown_pct']
        dd_impact = stress_dd - baseline_dd
        
        print(f"  Max Drawdown:")
        print(f"    Baseline: {baseline_dd:.2f}%")
        print(f"    Stress:   {stress_dd:.2f}%")
        print(f"    Impact:   {dd_impact:+.2f}% ({(dd_impact/baseline_dd*100):+.1f}%)")
        
        # Risk breaches
        baseline_breaches = baseline['risk_breaches']
        stress_breaches = stress['risk_breaches']
        
        print(f"  Risk Breaches:")
        print(f"    Baseline: {baseline_breaches}")
        print(f"    Stress:   {stress_breaches}")
        print(f"    New breaches: {stress_breaches - baseline_breaches}")
        
        # Signals
        baseline_signals = baseline['strategy_signals']
        stress_signals = stress['strategy_signals']
        
        print(f"  Strategy Signals:")
        print(f"    Baseline: {baseline_signals}")
        print(f"    Stress:   {stress_signals}")
        print()
        
        summary['comparative_analysis'][scenario_name] = {
            'drawdown_impact': dd_impact,
            'risk_breach_increase': stress_breaches - baseline_breaches,
            'signal_change': stress_signals - baseline_signals,
        }
    
    # Save summary to JSON
    summary_json_path = Path('stress_test_results/stress_test_summary.json')
    summary_json_path.parent.mkdir(parents=True, exist_ok=True)
    summary_json_path.write_text(json.dumps(summary, indent=2))
    
    print("=" * 80)
    print("✅ STRESS TEST SUITE COMPLETE")
    print("=" * 80)
    print()
    print("📁 Output Files Generated:")
    print("  • stress_test_results/stress_test_report_flash_crash.txt")
    print("  • stress_test_results/stress_test_report_sustained_downtrend.txt")
    print("  • stress_test_results/stress_test_report_high_volatility.txt")
    print("  • stress_test_results/stress_test_summary.json")
    print("  • stress_test_results/{scenario}/position_sizing.csv")
    print("  • stress_test_results/{scenario}/stop_loss_events.csv")
    print("  • stress_test_results/{scenario}/strategy_signals.csv")
    print("  • stress_test_results/{scenario}/ml_evaluations.csv")
    print("  • stress_test_results/{scenario}/regime_switches.csv")
    print("  • stress_test_results/{scenario}/risk_breaches.csv")
    print("  • stress_test_results/{scenario}/drawdown_events.csv")
    print()
    print("🎯 Results Summary:")
    print(f"  • {len(scenarios)} stress scenarios tested")
    print(f"  • {len(scenarios)} comprehensive reports generated")
    print(f"  • All risk metrics tracked and analyzed")
    print(f"  • Expected vs actual performance documented")
    print()
    print("=" * 80)


if __name__ == "__main__":
    main()
