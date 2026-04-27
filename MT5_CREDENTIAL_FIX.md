# ✅ MT5 Credential Fix - Critical Step

## Current Status
The bot is running but **failing to connect to MT5** because:
1. config.yaml had placeholder credentials (123456789 / "your_password")
2. MT5 Terminal is not logged in with the correct account

## What Was Fixed
✅ config.yaml updated:
   - login: 5044383203 (demo account verified)
   - password: "" (empty - MT5 Terminal auto-authenticates)
   - server: "MetaQuotes-Demo"

## Next Critical Step: Login to MT5 Terminal

**The bot cannot authenticate unless MT5 Terminal is already logged in to the correct account.**

### Steps to Fix

1. **Stop the running bot**
   - Press Ctrl+C in the terminal running the bot
   
2. **Open MetaTrader5 Terminal on your computer**
   - Look for: "MetaTrader 5" desktop icon or taskbar icon
   
3. **Verify you're logged in to the correct account**
   ```
   Account Number: 5044383203
   Server: MetaQuotes-Demo
   ```
   - If NOT logged in, click "File" → "Login"
   - Enter login: 5044383203
   - Enter password: (the demo account password)
   - Server: MetaQuotes-Demo
   - Click "Login"

4. **Verify connection in MT5**
   - Look for green indicator (connected)
   - Check account info shows: 5044383203
   - Check balance shows: $95,514.68 (or current balance)

5. **Once logged into MT5, restart the bot**
   ```bash
   python main_production.py
   ```

## How MT5 Authentication Works

```
MetaTrader5 Terminal (Must be logged in)
           ↓
        (Logged in to: 5044383203)
           ↓
    Python Script Connects
           ↓
    MT5.initialize() ← Connects to EXISTING logged-in session
           ↓
    Bot trades on that account
```

**KEY POINT:** The bot doesn't need a password if MT5 Terminal is already logged in. It just needs the login number.

## Troubleshooting

### Problem: "Invalid 'login' argument"
**Cause:** MT5 Terminal is either:
- Not running at all, OR
- Logged in to a DIFFERENT account, OR
- Not logged in at all

**Solution:**
1. Ensure MT5 Terminal is running
2. Ensure it shows: "Account: 5044383203"
3. Restart the bot

### Problem: "Cannot connect to broker"
**Cause:** MT5 Terminal crashed or logged out

**Solution:**
1. Check if MT5 Terminal is still running
2. Click on MT5 Terminal window to ensure it's in focus
3. Check: File → Account Information (should show 5044383203)
4. Restart the bot

### Problem: "Connection timeout"
**Cause:** MT5 Terminal taking too long to respond

**Solution:**
- Wait longer (bot retries for 2-3 minutes)
- Or restart MT5 Terminal and bot

## MT5 Terminal Location

If you can't find MT5 Terminal:
1. Look at: C:\Program Files\MetaTrader 5\terminal64.exe
2. Or check your desktop for icon labeled "MetaTrader 5"
3. Or search Windows for "MetaTrader"

## Password Question

**For demo account (5044383203):**
- If you HAVE the password: Set it in config.yaml
- If you DON'T have it: Leave password empty (bot uses terminal session)

**For your own account:**
- Get login number from MT5 Terminal
- Get password from your broker
- Update config.yaml:
  ```yaml
  broker:
    login: YOUR_LOGIN_NUMBER
    password: "YOUR_PASSWORD"
    server: "MetaQuotes-Demo"  # or your broker's server
  ```

## Verify MT5 is Ready

Before starting bot, run this:
```bash
python -c "
import MetaTrader5 as mt5
if mt5.initialize():
    acc = mt5.account_info()
    print(f'✓ MT5 Ready')
    print(f'  Account: {acc.login}')
    print(f'  Balance: {acc.balance}')
    mt5.shutdown()
else:
    print('✗ MT5 not ready')
    print('  → Ensure MetaTrader5 Terminal is running')
    print('  → Ensure you are logged in')
"
```

Expected output:
```
✓ MT5 Ready
  Account: 5044383203
  Balance: 95514.68
```

## Quick Checklist

Before restarting bot:
- [ ] config.yaml updated with correct login (5044383203)
- [ ] MetaTrader5 Terminal open on your screen
- [ ] Terminal shows green "Connected" indicator
- [ ] Terminal shows Account: 5044383203
- [ ] Terminal shows Server: MetaQuotes-Demo

Once all checked, start bot:
```bash
python main_production.py
```

## Expected Startup Sequence (After Fix)

```
[BOT] Initializing components...
[BOT] Using MT5BrokerInterface
[MT5] Connecting to account 5044383203...
[MT5] ✓ Connected successfully
[ENGINE] Connected to broker
[TRAILING_SL_INIT] Manager initialized
[ENGINE] Engine initialized successfully
[BOT] ML pipeline initialized
[BOT] Running backtests...
[ENGINE] Starting trading loop...
```

If you see these logs, **everything is working!** ✅

---

**Created:** 2026-04-16  
**Action Required:** Login to MT5 Terminal with account 5044383203
