#!/usr/bin/env python3
"""
Comprehensive Win Rate Analysis Tool
Identifies patterns in losing trades to optimize entry/exit strategies
"""

import json
import logging
from pathlib import Path
from collections import defaultdict
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def analyze_backtest_trades():
    """Analyze recent backtest trades to identify loss patterns"""
    
    # Try to find backtest results
    results_files = list(Path('.').glob('*backtest*.json')) + list(Path('.').glob('*results*.json'))
    
    if not results_files:
        logger.warning("No backtest JSON files found. Generating analysis report...")
        generate_improvement_report()
        return
    
    latest_file = max(results_files, key=lambda p: p.stat().st_mtime)
    logger.info(f"Analyzing: {latest_file}")
    
    try:
        with open(latest_file, 'r') as f:
            data = json.load(f)
    except:
        logger.error(f"Could not read {latest_file}")
        generate_improvement_report()
        return
    
    trades = data.get('trades', [])
    if not trades:
        logger.warning("No trades found in backtest data")
        generate_improvement_report()
        return
    
    logger.info(f"\n{'='*80}")
    logger.info(f"WIN RATE ANALYSIS - {len(trades)} trades")
    logger.info(f"{'='*80}\n")
    
    # Categorize trades
    winners = [t for t in trades if t.get('pnl', 0) > 0]
    losers = [t for t in trades if t.get('pnl', 0) <= 0]
    
    win_rate = len(winners) / len(trades) * 100 if trades else 0
    
    logger.info(f"✓ Winning Trades: {len(winners)} ({win_rate:.1f}%)")
    logger.info(f"✗ Losing Trades:  {len(losers)} ({100-win_rate:.1f}%)")
    
    if winners:
        avg_win = sum(t.get('pnl', 0) for t in winners) / len(winners)
        logger.info(f"  Average Win: ${avg_win:.2f}")
    
    if losers:
        avg_loss = sum(abs(t.get('pnl', 0)) for t in losers) / len(losers)
        logger.info(f"  Average Loss: -${avg_loss:.2f}")
    
    # Analyze losing trade patterns
    logger.info(f"\n{'='*80}")
    logger.info("LOSING TRADE PATTERNS")
    logger.info(f"{'='*80}\n")
    
    # Group by direction
    losing_buys = [t for t in losers if t.get('direction', '').upper() == 'BUY']
    losing_sells = [t for t in losers if t.get('direction', '').upper() == 'SELL']
    
    logger.info(f"Losing BUY trades:  {len(losing_buys)}")
    logger.info(f"Losing SELL trades: {len(losing_sells)}")
    
    # Group by entry signals
    signal_patterns = defaultdict(lambda: {'total': 0, 'won': 0, 'lost': 0, 'pnl': 0})
    
    for trade in trades:
        signal = trade.get('signal', 'UNKNOWN')
        signal_patterns[signal]['total'] += 1
        signal_patterns[signal]['pnl'] += trade.get('pnl', 0)
        
        if trade.get('pnl', 0) > 0:
            signal_patterns[signal]['won'] += 1
        else:
            signal_patterns[signal]['lost'] += 1
    
    logger.info(f"\nSignal Quality by Entry Type:")
    logger.info("-" * 60)
    
    for signal, stats in sorted(signal_patterns.items(), 
                                key=lambda x: x[1]['total'], 
                                reverse=True):
        total = stats['total']
        won = stats['won']
        wr = (won / total * 100) if total > 0 else 0
        pnl = stats['pnl']
        
        logger.info(f"  {signal:20s}: {won:3d}W {stats['lost']:3d}L | WR:{wr:5.1f}% | PnL: ${pnl:8.2f}")
    
    # Volatility analysis
    logger.info(f"\n{'='*80}")
    logger.info("VOLATILITY & MARKET CONDITION ANALYSIS")
    logger.info(f"{'='*80}\n")
    
    atr_groups = defaultdict(lambda: {'total': 0, 'won': 0, 'pnl': 0})
    
    for trade in trades:
        atr = trade.get('atr', 0)
        if atr < 0.0005:
            group = "Low (<0.0005)"
        elif atr < 0.001:
            group = "Medium (0.0005-0.001)"
        elif atr < 0.002:
            group = "High (0.001-0.002)"
        else:
            group = "Very High (>0.002)"
        
        atr_groups[group]['total'] += 1
        atr_groups[group]['pnl'] += trade.get('pnl', 0)
        if trade.get('pnl', 0) > 0:
            atr_groups[group]['won'] += 1
    
    logger.info("Performance by Volatility (ATR):")
    for group, stats in sorted(atr_groups.items()):
        total = stats['total']
        won = stats['won']
        wr = (won / total * 100) if total > 0 else 0
        logger.info(f"  {group:25s}: {won:3d}W {total-won:3d}L | WR:{wr:5.1f}% | PnL: ${stats['pnl']:8.2f}")
    
    # Duration analysis
    logger.info(f"\nTrade Duration Analysis:")
    logger.info("-" * 60)
    
    duration_groups = defaultdict(lambda: {'total': 0, 'won': 0, 'pnl': 0})
    
    for trade in trades:
        duration = trade.get('duration_bars', 0)
        if duration < 5:
            group = "Scalp (<5)"
        elif duration < 20:
            group = "Short (5-20)"
        elif duration < 60:
            group = "Medium (20-60)"
        else:
            group = "Long (>60)"
        
        duration_groups[group]['total'] += 1
        duration_groups[group]['pnl'] += trade.get('pnl', 0)
        if trade.get('pnl', 0) > 0:
            duration_groups[group]['won'] += 1
    
    for group, stats in sorted(duration_groups.items()):
        total = stats['total']
        won = stats['won']
        wr = (won / total * 100) if total > 0 else 0
        logger.info(f"  {group:20s}: {won:3d}W {total-won:3d}L | WR:{wr:5.1f}% | PnL: ${stats['pnl']:8.2f}")


def generate_improvement_report():
    """Generate specific improvement recommendations"""
    
    logger.info(f"\n{'='*80}")
    logger.info("WIN RATE IMPROVEMENT RECOMMENDATIONS")
    logger.info(f"{'='*80}\n")
    
    recommendations = [
        {
            "phase": "PHASE 1: Entry Signal Quality",
            "items": [
                "✓ DONE: Raised signal_quality_min from 0.58 to 0.68",
                "✓ DONE: Raised ADX min threshold from 10 to 20",
                "✓ DONE: Tightened RSI bands from 30-70 to 35-65",
                "✓ DONE: Raised ML confidence from 0.55 to 0.58",
                "→ NEXT: Integrate ML model predictions with entry filters",
            ]
        },
        {
            "phase": "PHASE 2: Exit Strategy Optimization",
            "items": [
                "→ Verify advanced_exit_handler is active in backtest",
                "→ Analyze losing trades to optimize take-profit levels",
                "→ Implement dynamic stop-loss based on ATR",
                "→ Add breakeven stop after 50% of target reached",
                "→ Test trailing stop for trending markets",
            ]
        },
        {
            "phase": "PHASE 3: Market Filtering",
            "items": [
                "✓ DONE: MarketRegimeDetector with session awareness",
                "→ Skip trades during choppy markets (ADX < 15)",
                "→ Reduce position size during high volatility",
                "→ Focus on major session times (London/NY overlap)",
            ]
        },
        {
            "phase": "PHASE 4: Risk Management",
            "items": [
                "→ Implement dynamic position sizing based on signal quality",
                "→ Adjust risk per trade based on market conditions",
                "→ Add max daily loss limit",
                "→ Implement account balance trailing stop",
            ]
        },
    ]
    
    for rec in recommendations:
        logger.info(f"\n{rec['phase']}")
        logger.info("-" * 60)
        for item in rec['items']:
            logger.info(f"  {item}")


if __name__ == "__main__":
    logger.info("Starting Win Rate Analysis...\n")
    analyze_backtest_trades()
    logger.info(f"\n{'='*80}")
    logger.info("Analysis Complete")
    logger.info(f"{'='*80}\n")
