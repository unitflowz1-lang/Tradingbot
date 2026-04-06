#!/usr/bin/env python3
"""
Verification script for Weekly Distribution Report deployment
"""

import os
from pathlib import Path

print("\n" + "="*70)
print("✅ WEEKLY DISTRIBUTION REPORT - DEPLOYMENT VERIFICATION")
print("="*70)

# Check module file
weekly_module = Path("src/monitoring/weekly_distribution_report.py")
if weekly_module.exists():
    size = weekly_module.stat().st_size
    lines = len(weekly_module.read_text(encoding='utf-8', errors='ignore').split('\n'))
    print(f"\n✅ Module File: {weekly_module}")
    print(f"   Size: {size:,} bytes | Lines: {lines}")
else:
    print(f"\n❌ Module File NOT found: {weekly_module}")

# Check main.py integration
main_py = Path("main.py")
content = main_py.read_text(encoding='utf-8', errors='ignore')

checks = {
    "Import module": "from src.monitoring.weekly_distribution_report",
    "Initialize generator": "WeeklyDistributionReportGenerator(output_dir",
    "Record volatility": "weekly_distribution_report.record_volatility_sample",
    "Record rejections": "weekly_distribution_report.record_rejected_trade",
    "Update prices": "weekly_distribution_report.update_rejected_trade_price",
    "Generate weekly report": "weekly_distribution_report.should_generate_report()",
    "Quick stats logging": "weekly_distribution_report.get_quick_summary()"
}

print(f"\n📝 Integration Points in main.py:")
all_integrated = True
for check_name, check_string in checks.items():
    if check_string in content:
        print(f"   ✅ {check_name}")
    else:
        print(f"   ❌ {check_name} - NOT FOUND")
        all_integrated = False

# Check documentation files
docs = [
    "WEEKLY_DISTRIBUTION_REPORT_GUIDE.md",
    "WEEKLY_DISTRIBUTION_SUMMARY.md", 
    "COMPLETE_MONITORING_STACK.md",
    "WEEKLY_DISTRIBUTION_QUICKSTART.md",
    "WEEKLY_DISTRIBUTION_IMPLEMENTATION.md",
    "WEEKLY_DISTRIBUTION_DELIVERED.md"
]

print(f"\n📚 Documentation Files:")
all_docs_present = True
for doc in docs:
    doc_path = Path(doc)
    if doc_path.exists():
        size = doc_path.stat().st_size
        lines = len(doc_path.read_text(encoding='utf-8', errors='ignore').split('\n'))
        print(f"   ✅ {doc}: {lines} lines ({size:,} bytes)")
    else:
        print(f"   ❌ {doc}: NOT FOUND")
        all_docs_present = False

# Check report directories
print(f"\n📂 Report Directories:")
for dir_name in ["reports/daily_risk", "reports/weekly_distribution"]:
    dir_path = Path(dir_name)
    if dir_path.exists():
        print(f"   ✅ {dir_path} (ready for reports)")
    else:
        print(f"   ℹ️  {dir_path} (will be created on first run)")

print(f"\n" + "="*70)
if all_integrated and all_docs_present:
    print("✅ DEPLOYMENT STATUS: COMPLETE AND READY FOR PAPER TRADING")
else:
    print("⚠️  DEPLOYMENT STATUS: PARTIAL - Check errors above")
print("="*70)

print(f"\n🚀 Quick Start Commands:")
print(f"   1. Start bot:     python main.py")
print(f"   2. Monitor stats: tail -f logs/trading_*.log | grep WEEKLY")
print(f"   3. First report:  After 7 days in reports/weekly_distribution/")

print(f"\n📖 Documentation:")
print(f"   • WEEKLY_DISTRIBUTION_QUICKSTART.md - Start here!")
print(f"   • WEEKLY_DISTRIBUTION_REPORT_GUIDE.md - Full reference")
print(f"   • COMPLETE_MONITORING_STACK.md - Daily vs Weekly overview")

print(f"\n" + "="*70 + "\n")
