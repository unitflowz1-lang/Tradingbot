# LIVE DASHBOARD QUICK GUIDE
============================

## 🚀 HOW TO USE

### Start the Dashboard:
```powershell
# In a SECOND PowerShell window (while bot runs in first)
cd "c:\Users\macki\Desktop\v8.6 core RL TradingBot"
python scripts\live_dashboard.py
```

### Custom Options:
```powershell
# Update every 3 seconds (faster)
python scripts\live_dashboard.py --interval 3

# Update every 10 seconds (slower)
python scripts\live_dashboard.py --interval 10

# Specify custom log directory
python scripts\live_dashboard.py --log-dir logs --interval 5
```

---

## 📊 DASHBOARD SECTIONS

### 1. CORE METRICS
Shows your key performance indicators:
- **Win Rate**: % of winning trades (Target: 54-59%)
- **Profit Factor**: Gross profit / Gross loss (Target: >1.7)
- **Total PnL**: Cumulative profit/loss
- **Avg PnL/Trade**: Average profit per trade
- **Current Equity**: Starting $10,000 + PnL

**Color Codes:**
- ✅ Green = Excellent (WR ≥55%, PF ≥1.5)
- 🟡 Yellow = Good (WR ≥50%, PF ≥1.2)
- ❌ Red = Poor (WR <50%, PF <1.2)

### 2. RISK METRICS
Monitors your risk exposure:
- **Max Drawdown**: Peak-to-trough decline (Must stay <15%)
- **Max Win Streak**: Best consecutive wins
- **Max Loss Streak**: Worst consecutive losses
- **Current Streak**: Current win/loss run

**Warning Levels:**
- ✅ Green = DD ≤5%
- 🟡 Yellow = DD 5-10%
- ❌ Red = DD 10-15%
- 🚨 Critical = DD >15%

### 3. SIGNAL QUALITY
Shows signal filtering effectiveness:
- **Signals Admitted**: Passed quality floor
- **Signals Rejected**: Failed quality floor
- **Admission Rate**: % of signals that passed
- **Spread Traps**: Times spread blocked entry
- **Compounding**: Position scaling events

### 4. RECENT TRADES
Last 10 trades with details:
- Symbol (EUR/USD, GBP/USD, etc.)
- Direction (LONG/SHORT)
- PnL (Profit/Loss)
- Exit Reason (TP/SL)
- Timestamp

### 5. STATUS BANNER
Overall strategy assessment:
- 🎉 EXCELLENT - Above targets
- ✅ GOOD - On track
- ⚠️ MARGINAL - Needs improvement
- ❌ POOR - Consider stopping
- ⏳ WAITING - No trades yet

---

## 🎯 WHAT TO WATCH FOR

### ✅ GOOD SIGNS:
- Win Rate climbing toward 54-59%
- Profit Factor > 1.5
- Max Drawdown < 8%
- Mix of TP and SL exits (not all SL)
- Compounding triggers occasionally
- Spread traps blocking during news

### ⚠️ WARNING SIGNS:
- Win Rate < 48%
- Profit Factor < 1.0
- Max Drawdown > 10%
- 5+ consecutive losses
- All exits are SL (TP never hit)
- Very high admission rate (>90% - floor too low)

### 🚨 STOP IMMEDIATELY IF:
- Max Drawdown > 15%
- 10+ consecutive losses
- Bot stops logging (crashed)
- Profit Factor < 0.5 after 20+ trades

---

## 📋 MONITORING SCHEDULE

### When Market Opens (Sunday 22:00 UTC):
1. Start dashboard in second terminal
2. Watch for first signals (should see admission/rejection counts increase)
3. Wait for first trades (may take 30-60 min)
4. Monitor first 10 trades closely

### During Active Trading:
- Check dashboard every 1-2 hours
- Look at "Recent Trades" section for patterns
- Verify win rate is in target zone
- Ensure drawdown stays below 12%

### End of Day:
- Record final metrics
- Note any unusual patterns
- Check if compounding triggered
- Review spread trap activity

### After 3-5 Days:
- Run full analysis: `python scripts/analyze_dry_run_results.py`
- Compare dashboard metrics with analysis report
- Make go/no-go decision

---

## 🔧 TROUBLESHOOTING

### Dashboard Shows "No trades yet" for Hours:
- Market might be closed (weekend/holiday)
- Low volatility (no signals meeting quality floor)
- Check bot logs: `Get-Content logs/*.log -Tail 50`

### Win Rate Fluctuating Wildly:
- Normal with small sample size (<20 trades)
- Becomes stable after 50+ trades
- Don't panic until 30+ trades completed

### Dashboard Not Updating:
- Check if log file exists
- Verify bot is still running
- Restart dashboard if needed

### Error Messages:
```
❌ Error: 'current_streak'
```
→ Fixed in latest version, restart dashboard

```
❌ Error: No log files found
```
→ Bot hasn't created logs yet, wait 1-2 minutes

---

## 💡 PRO TIPS

### 1. Split Screen Setup:
- Left terminal: Bot running (`python main.py`)
- Right terminal: Dashboard (`python scripts/live_dashboard.py`)
- See both real-time!

### 2. Log Both to File:
```powershell
# Save dashboard output to file
python scripts/live_dashboard.py | Tee-Object dashboard_output.txt
```

### 3. Take Screenshots:
- Screenshot dashboard every 6 hours
- Create visual performance timeline
- Useful for post-analysis

### 4. Compare with Targets:
Keep this checklist visible:
```
Target Win Rate: 54-59%
Target Profit Factor: >1.7
Target Trades/Month: 60-90
Max Drawdown: <12%
```

---

## 📁 RELATED FILES

- `scripts/live_dashboard.py` - This dashboard
- `scripts/monitor_dry_run.py` - Alternative monitor (simpler)
- `scripts/analyze_dry_run_results.py` - Post-run analysis
- `logs/forex_bot.log` - Main bot log file
- `config/optimized_params.json` - Goldilocks parameters

---

## 🎉 READY TO GO!

The dashboard is now running and will auto-refresh every 5 seconds.

**When the market opens on Sunday 22:00 UTC, you'll see:**
1. Signals being admitted/rejected
2. First trades executing (in DRY RUN mode)
3. Win rate and profit factor calculating
4. Real-time PnL updates

**Just let it run and monitor periodically!**

---

**Generated:** 2026-04-25 02:22:00 UTC
**Status:** DASHBOARD ACTIVE & READY
**Next Update:** Market opens Sunday 22:00 UTC
