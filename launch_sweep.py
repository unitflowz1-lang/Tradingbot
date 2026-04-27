#!/usr/bin/env python3
"""
Quick launcher for parameter sweep with intelligent defaults
"""

import subprocess
import sys
import argparse
from pathlib import Path
from datetime import datetime

def run_sweep(mode='quick', save=True, plot=False, verbose=False):
    """Run parameter sweep with specified mode"""
    
    print("=" * 70)
    print("PARAMETER SWEEP LAUNCHER")
    print("=" * 70)
    print(f"\n📊 Mode: {mode.upper()}")
    print(f"💾 Save Results: {'Yes' if save else 'No'}")
    print(f"📈 Plot Heatmaps: {'Yes' if plot else 'No'}")
    print()
    
    # Build command
    cmd = ['python', 'run_parameter_sweep.py']
    
    if mode == 'quick':
        cmd.append('--quick')
        est_time = "5-10 minutes"
    elif mode == 'full':
        est_time = "2-4 hours"
    else:
        raise ValueError(f"Unknown mode: {mode}")
    
    if save:
        cmd.append('--save-results')
    
    if plot:
        cmd.append('--plot')
    
    if verbose:
        cmd.append('--verbose')
    
    print(f"⏱️  Estimated time: {est_time}")
    print(f"📋 Command: {' '.join(cmd)}")
    print("\n" + "=" * 70)
    print("Starting sweep...\n")
    
    # Run sweep
    try:
        result = subprocess.run(cmd, check=True)
        print("\n" + "=" * 70)
        print("✅ SWEEP COMPLETED SUCCESSFULLY")
        print("=" * 70)
        
        if save:
            print("\n📁 Results saved:")
            print("   • sweep_results.csv")
            print("   • sweep_results.json")
            if plot:
                print("   • heatmaps_*.png")
            
            print("\n🎯 Next steps:")
            print("   1. Review sweep_results.json for top configurations")
            print("   2. Run: python extract_best_params.py")
            print("   3. Deploy: See PARAMETER_INTEGRATION_GUIDE.md")
        
        return 0
    
    except subprocess.CalledProcessError as e:
        print("\n" + "=" * 70)
        print(f"❌ SWEEP FAILED (exit code: {e.returncode})")
        print("=" * 70)
        return 1
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Sweep interrupted by user")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description='Quick launcher for hyperparameter sweep',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python launch_sweep.py --quick        # Fast test (5-10 min)
  python launch_sweep.py --full         # Full sweep (2-4 hours)
  python launch_sweep.py --quick --plot # Quick + visualizations
  python launch_sweep.py --quick --no-save  # Quick, no output files
        """
    )
    
    mode_group = parser.add_mutually_exclusive_group(required=False)
    mode_group.add_argument('--quick', action='store_true', 
                           help='Quick test mode (5-10 minutes)')
    mode_group.add_argument('--full', action='store_true',
                           help='Full sweep (2-4 hours) - DEFAULT')
    
    parser.add_argument('--save', dest='save', action='store_true', default=True,
                       help='Save results to CSV/JSON (default: True)')
    parser.add_argument('--no-save', dest='save', action='store_false',
                       help='Do not save results')
    parser.add_argument('--plot', action='store_true',
                       help='Generate heatmap visualizations')
    parser.add_argument('--verbose', action='store_true',
                       help='Show detailed logging')
    
    args = parser.parse_args()
    
    # Determine mode
    if args.quick:
        mode = 'quick'
    elif args.full:
        mode = 'full'
    else:
        # Default: quick if quick was explicitly requested, else full
        mode = 'full'
    
    # Run sweep
    exit_code = run_sweep(
        mode=mode,
        save=args.save,
        plot=args.plot,
        verbose=args.verbose
    )
    
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
