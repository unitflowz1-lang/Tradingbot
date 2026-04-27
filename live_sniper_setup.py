"""
LIVE SNIPER SETUP - Step 1
Wipes signal_tracking.db and resets macro_risk_cache to 0 for all symbols.
"""
import sqlite3, json, os, shutil, datetime

workspace = r'c:\Users\macki\Desktop\v8.6 core RL TradingBot'
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')

# ── 1. Delete signal_tracking.db ─────────────────────────────────────────────
db_path = os.path.join(workspace, 'data', 'signal_tracking.db')
if os.path.exists(db_path):
    db_bak = db_path + '.bak.HARD_WIPE_' + stamp
    shutil.copy2(db_path, db_bak)
    os.remove(db_path)
    print(f'[WIPE_OK] signal_tracking.db deleted (backup: {db_bak})')
else:
    print('[OK] signal_tracking.db already absent')

# ── 2. Re-wipe shadow_state.json just to be sure ─────────────────────────────
shadow_path = os.path.join(workspace, 'shadow_state.json')
clean = {'shadow_positions': {}, 'last_updated': datetime.datetime.now(datetime.timezone.utc).isoformat()}
with open(shadow_path, 'w', encoding='utf-8') as f:
    json.dump(clean, f, indent=2)
print('[WIPE_OK] shadow_state.json re-zeroed')

# ── 3. Force macro_risk_cache to 0 for every monitored symbol ─────────────────
SYMBOLS = ['EUR/USD', 'GBP/USD', 'USD/JPY', 'XAU/USD', 'AUD/USD', 'USD/CAD', 'NZD/USD']
mc_path = os.path.join(workspace, 'data', 'macro_risk_cache.json')
mc_payload = {
    'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'source': 'HARD_RESET_LIVE_SNIPER',
    'penalties': {sym: 0.0 for sym in SYMBOLS},
    'reasons':   {sym: 'LIVE_SNIPER_OVERRIDE_NO_MACRO_RISK' for sym in SYMBOLS},
    'global_block': False,
    'macro_risk_block': False,
}
mc_path_bak = mc_path + '.bak.HARD_WIPE_' + stamp
if os.path.exists(mc_path):
    shutil.copy2(mc_path, mc_path_bak)
with open(mc_path, 'w', encoding='utf-8') as f:
    json.dump(mc_payload, f, indent=2)
print(f'[WIPE_OK] macro_risk_cache.json forced to 0 for {len(SYMBOLS)} symbols')

# ── 4. Verify ─────────────────────────────────────────────────────────────────
print()
print('=' * 60)
print('  LIVE SNIPER SETUP VERIFICATION')
print('=' * 60)
print(f'  signal_tracking.db exists: {os.path.exists(db_path)}  (want: False)')
shadow_check = json.load(open(shadow_path))
print(f'  shadow_positions count:    {len(shadow_check.get("shadow_positions", {}))}  (want: 0)')
mc_check = json.load(open(mc_path))
non_zero = [s for s, p in mc_check["penalties"].items() if p != 0.0]
print(f'  macro penalties non-zero:  {non_zero}  (want: [])')
print(f'  macro_risk_block flag:     {mc_check.get("macro_risk_block")}  (want: False)')
print('=' * 60)
if not os.path.exists(db_path) and not non_zero and not mc_check.get('macro_risk_block'):
    print('[STATUS] ALL CLEAR — Live Sniper prerequisites confirmed')
else:
    print('[STATUS] WARNING — review failures above')
print('=' * 60)
