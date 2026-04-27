# DRY RUN QUICK REFERENCE CARD
===============================

## 🚀 LAUNCH BOT (Windows)

```powershell
# Option 1: Use the launcher script (recommended)
.\start_dry_run.ps1

# Option 2: Run directly
python main.py
```

## 🚀 LAUNCH BOT (Linux/Mac)

```bash
# Option 1: Use the launcher script
chmod +x start_dry_run.sh
./start_dry_run.sh

# Option 2: Run directly
python main.py
```

---

## 👀 MONITOR IN REAL-TIME

Open a **second terminal** and run:

```bash
python scripts/monitor_dry_run.py --interval 10
```

This shows live dashboard with:
- Win rate
- Profit factor
- Drawdown
- Trade count
- Compounding triggers
- Spread trap blocks

---

## 📊 ANALYZE RESULTS (After Run)

```bash
python scripts/analyze_dry_run_results.py
```

Generates comprehensive report with success/failure verdict.

---

## 🎯 SUCCESS CRITERIA

| Metric | PASS | CAUTION | FAIL |
|--------|------|---------|------|
| Win Rate | ≥ 52% | 48-52% | < 48% |
| Profit Factor | ≥ 1.3 | 1.0-1.3 | < 1.0 |
| Max Drawdown | ≤ 12% | 12-15% | > 15% |
| Trade Count (3-5 days) | ≥ 20 | 10-20 | < 10 |

---

## 🔍 MONITOR LOGS

```bash
# Watch all logs in real-time
tail -f logs/*.log

# Filter for trades only
tail -f logs/*.log | grep -E "TRADE|EXIT|PnL"

# Filter for signals
tail -f logs/*.log | grep -E "SIGNAL|quality"

# Filter for warnings/errors
tail -f logs/*.log | grep -E "WARNING|ERROR|CRITICAL"
```

---

## 🛑 STOP BOT

Press `Ctrl+C` in the terminal running the bot.

---

## ⚠️ WARNING SIGNS (Stop Immediately)

- [ ] Drawdown > 10%
- [ ] 5+ consecutive losses
- [ ] Bot stops logging trades
- [ ] Runtime errors in logs
- [ ] Spread trap blocking > 50% of signals

---

## 📁 IMPORTANT FILES

| File | Purpose |
|------|---------|
| `config/optimized_params.json` | Active trading parameters |
| `.env` | Environment configuration (DRY_RUN=1) |
| `logs/dry_run_*.log` | Dry run log files |
| `start_dry_run.ps1` | Windows launcher |
| `start_dry_run.sh` | Linux/Mac launcher |
| `scripts/monitor_dry_run.py` | Real-time monitor |
| `scripts/analyze_dry_run_results.py` | Post-run analyzer |

---

## 📋 DAILY CHECKLIST

### Morning (Market Open):
- [ ] Check bot is running
- [ ] Review overnight trades
- [ ] Verify no errors in logs
- [ ] Check current drawdown

### Mid-Day:
- [ ] Monitor win rate trend
- [ ] Check trade frequency
- [ ] Verify compounding logic working
- [ ] Review spread trap activity

### Evening (Market Close):
- [ ] Calculate daily metrics
- [ ] Log results in trading journal
- [ ] Check for any warnings
- [ ] Plan adjustments if needed

---

## 🎯 EXPECTED TIMELINE

### Day 1-2: Initial Testing
- First 10-20 trades executed
- Verify bot behavior is correct
- Check for runtime errors
- Confirm spread protection working

### Day 3: Mid-Point Review
- Run analysis: `python scripts/analyze_dry_run_results.py`
- Check if metrics are on track
- Adjust parameters if needed

### Day 4-5: Final Validation
- Complete 3-5 day test period
- Run final analysis
- Compare against success criteria
- Make go/no-go decision

### Day 6+: Go Live (If Passed)
- Set `DRY_RUN=0` in `.env`
- Start with 50% position sizes
- Monitor closely for 24 hours
- Gradually increase to full size

---

## 🔧 TROUBLESHOOTING

### Bot Won't Start:
```bash
# Check MT5 is running
python -c "import MetaTrader5 as mt5; print(mt5.initialize())"

# Check Python version
python --version  # Should be 3.12+

# Check dependencies
pip install -r requirements.txt
```

### No Trades Executing:
- Market might be closed (weekend/holiday)
- Signal quality below floor
- Spread too high (spread trap active)
- Check logs for rejection reasons

### High Drawdown:
- Stop bot if > 15%
- Review losing trades for patterns
- Consider widening ATR SL
- Reduce position size

### Low Trade Frequency:
- Quality floor might be too high
- Market conditions (low volatility)
- Check signal admission rate in logs

---

## 📞 EMERGENCY CONTACTS

If bot behaves unexpectedly:

1. **STOP:** Press Ctrl+C immediately
2. **CHECK:** Review last 100 lines of logs
3. **ANALYZE:** Run analysis script
4. **DECIDE:** Adjust or stop based on findings

---

**Generated:** 2026-04-25
**Status:** READY FOR DRY RUN
**Duration:** 3-5 days
