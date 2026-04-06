# 🤖 MT5 Demo Account Setup Instructions

## Current Status
✅ MT5 Terminal is installed and running  
❌ Demo account connection needs manual setup

## Step-by-Step Setup

### 1. 🔑 Login to MT5 Terminal Manually

**Open MT5 Terminal** (should already be running)

**Login to your demo account:**
1. In MT5 Terminal, look at the top-left corner
2. Click on the account area or go to **File → Login to Trade Account**
3. Enter your credentials:
   - **Login:** `5044383203`
   - **Password:** `!t1bTkHu`
   - **Server:** `ExLTS*DO`
   
   > If `ExLTS*DO` doesn't work, try searching for "ExLTS" and select the demo server

4. Click **OK**

**Verify successful login:**
- ✅ You should see your account balance displayed
- ✅ Market prices should be updating in Market Watch
- ✅ Bottom-right corner should show "Connected"

### 2. ⚙️ Enable Algorithmic Trading

**Open Options:**
1. Go to **Tools → Options** (or press Ctrl+O)
2. Click on the **Expert Advisors** tab

**Enable required settings:**
- ✅ Check "Allow algorithmic trading"
- ✅ Check "Allow DLL imports"  
- ✅ Check "Allow imports of external experts"
- Click **OK**

**Enable AutoTrading:**
1. Look for the **AutoTrading** button in the toolbar
2. If it's red/disabled, click it to make it green
3. You should see "Expert Advisors enabled" in the status bar

### 3. 🧪 Test the Connection

After completing the above steps, run one of these commands:

```bash
# Simple connection test
python test_mt5_simple.py

# Full connection test with account info
python connect_mt5_demo.py

# Complete setup guide
python complete_mt5_setup.py
```

### 4. 🚀 Start Trading (Once Connected)

```bash
# Start the AI trading bot
python main.py
```

## Troubleshooting

### If login fails:
- **Double-check credentials** (Login: 5038790723, Password: CvTYV-W7)
- **Try different server names:**
  - `ExLTS-Demo`
  - `ExLTS`
  - `ExLTS-MT5Demo`
  - Search for "ExLTS" in the server list
- **Contact your broker** for the correct server name

### If "Authorization failed" error persists:
1. **Restart MT5 Terminal** completely
2. **Run the Python script as Administrator:**
   - Right-click Command Prompt → "Run as Administrator"
   - Navigate to the project folder
   - Run the test script
3. **Make sure you're logged in manually first** in MT5 Terminal

### If algorithmic trading is disabled:
- Ensure the **AutoTrading button is green**
- Check **Tools → Options → Expert Advisors** settings
- **Restart MT5 Terminal** if needed

## Demo Account Details

- **Account Type:** Demo (virtual money, no risk)
- **Login:** 5038790723
- **Password:** CvTYV-W7
- **Server:** ExLTS*DO
- **Purpose:** Safe testing of trading strategies

## Next Steps After Connection

1. **Paper Trading:** Test strategies with virtual money
2. **Monitor Performance:** Track trades in both bot and MT5 Terminal  
3. **Analyze Results:** Use the bot's analytics features
4. **Optimize Strategies:** Adjust parameters based on results

## Support

If you continue to have issues:
1. Check that your demo account is still active
2. Try connecting manually in MT5 Terminal first
3. Contact ExLTS support for server information
4. Ensure your internet connection is stable

---

**Remember:** This is a demo account with virtual money. All trades are simulated and carry no financial risk.