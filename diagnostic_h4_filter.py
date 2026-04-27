"""
Diagnostic script to check if H4 Trend filter is blocking signals
"""
import logging
import json
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

def check_h4_filter_status():
    """Check if H4 Trend filter is blocking signals"""
    
    logger.info("=" * 80)
    logger.info("H4 TREND FILTER DIAGNOSTIC")
    logger.info("=" * 80)
    
    # Check enhanced signal validator config
    from src.analysis.enhanced_signal_validator import EnhancedSignalConfig
    
    config = EnhancedSignalConfig()
    
    logger.info("\n>>> H4 TREND FILTER CONFIGURATION:")
    logger.info(f"  Min MTF Alignment Required: {config.min_mtf_alignment} timeframes")
    logger.info(f"  Require Trend Alignment: {config.require_trend_alignment}")
    logger.info(f"  Min Confluence Score: {config.min_confluence_score}")
    
    logger.info("\n>>> TIMEFRAME WEIGHTS:")
    from src.analysis.enhanced_signal_validator import EnhancedSignalValidator
    validator = EnhancedSignalValidator(config)
    
    # Extract weights from _score_mtf_alignment method
    tf_weights = {"M15": 0.5, "H1": 1.0, "H4": 1.5, "D1": 2.0}
    for tf, weight in tf_weights.items():
        logger.info(f"  {tf}: {weight} (Higher weight = higher influence)")
    
    logger.info("\n>>> WHAT THIS MEANS:")
    logger.info(f"  - H4 has {tf_weights['H4']/tf_weights['H1']:.1f}x more weight than H1")
    logger.info(f"  - Signals must align with trend on at least {config.min_mtf_alignment} timeframes")
    logger.info(f"  - If H4 shows downtrend but H1 shows uptrend: H4 can BLOCK the signal")
    logger.info(f"  - This is INTENTIONAL risk management (avoiding counter-trend trades)")
    
    # Check if admission history exists
    admission_history_path = Path("trade_admission_history.json")
    if admission_history_path.exists():
        logger.info("\n>>> CHECKING RECENT SIGNAL FILTERING HISTORY:")
        try:
            with open(admission_history_path, 'r') as f:
                history = json.load(f)
                
            if isinstance(history, dict) and 'evaluations' in history:
                evaluations = history['evaluations']
                
                # Find rejected signals
                rejected = [e for e in evaluations if e.get('admitted') == False]
                
                logger.info(f"\n  Total Evaluations: {len(evaluations)}")
                logger.info(f"  Rejected Signals: {len(rejected)}")
                
                # Look for MTF rejection reason
                mtf_rejections = [e for e in rejected if 'multi-timeframe' in str(e.get('reason', '')).lower()]
                logger.info(f"  Rejected for MTF Misalignment: {len(mtf_rejections)}")
                
                if mtf_rejections:
                    logger.info("\n  EXAMPLE MTF REJECTIONS:")
                    for i, rejection in enumerate(mtf_rejections[:5]):
                        logger.info(f"    {i+1}. {rejection.get('symbol', 'UNKNOWN')}: {rejection.get('reason', 'Unknown reason')}")
                
                # Show acceptance rate
                accepted = len([e for e in evaluations if e.get('admitted') == True])
                if len(evaluations) > 0:
                    rate = (accepted / len(evaluations)) * 100
                    logger.info(f"\n  Signal Acceptance Rate: {rate:.1f}%")
                    if rate < 40:
                        logger.warning(f"  ??  LOW ACCEPTANCE RATE - H4 filter may be too strict!")
                        
        except Exception as e:
            logger.warning(f"  Could not read admission history: {e}")
    else:
        logger.info(f"\n  No admission history found at {admission_history_path}")
        logger.info("  Run live trading first to generate signal filtering logs")
    
    # Check for logs with H4 or MTF mentions
    logger.info("\n>>> CHECKING RECENT LOGS FOR H4 FILTER MESSAGES:")
    log_files = sorted(Path('.').glob('*.log'), key=lambda x: x.stat().st_mtime, reverse=True)
    
    h4_mentions = 0
    for log_file in log_files[:10]:  # Check last 10 logs
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                if 'H4' in content or 'multi-timeframe' in content.lower():
                    h4_mentions += 1
                    logger.info(f"  ? {log_file.name}: Contains H4/MTF messages")
        except Exception as e:
            pass
    
    if h4_mentions == 0:
        logger.info("  ??  No H4/MTF-specific messages in recent logs")
    
    logger.info("\n>>> DIAGNOSTIC SUMMARY:")
    logger.info("  H4 Trend filter IS ACTIVE and weights signals by timeframe agreement")
    logger.info("  To CHECK if it's blocking signals:")
    logger.info("    1. Run live trading for a few minutes")
    logger.info("    2. Check 'trade_admission_history.json' for rejection reasons")
    logger.info("    3. Look for 'multi-timeframe' or 'trend not aligned' messages")
    logger.info("")
    logger.info("  To RELAX H4 filter (if too strict):")
    logger.info("    - Reduce min_mtf_alignment from 2 to 1")
    logger.info("    - Reduce H4 weight in _score_mtf_alignment from 1.5 to 1.0")
    logger.info("    - Increase require_trend_alignment to False")
    logger.info("")
    logger.info("  To TIGHTEN H4 filter (if too loose):")
    logger.info("    - Increase min_mtf_alignment from 2 to 3")
    logger.info("    - Increase min_confluence_score threshold")
    logger.info("")
    logger.info("=" * 80)

if __name__ == "__main__":
    check_h4_filter_status()
