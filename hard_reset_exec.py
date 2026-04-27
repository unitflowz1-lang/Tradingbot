"""
HARD RESET EXECUTOR
Wipes transactional_tickets.json and shadow_state.json to 0 records.
Backups are created before any destructive action.
"""
import json, os, shutil, datetime

workspace = r'c:\Users\macki\Desktop\v8.6 core RL TradingBot'
ts_file = os.path.join(workspace, 'transactional_tickets.json')
shadow_file = os.path.join(workspace, 'shadow_state.json')
stamp = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
ts_bak = ts_file + '.bak.HARD_WIPE_' + stamp
shadow_bak = shadow_file + '.bak.HARD_WIPE_' + stamp

# --- Step 1: Backup and wipe transactional_tickets.json ---
shutil.copy2(ts_file, ts_bak)
with open(ts_file, 'r', encoding='utf-8') as f:
    before = json.load(f)
before_count = len(before)
with open(ts_file, 'w', encoding='utf-8') as f:
    json.dump({}, f)
with open(ts_file, 'r', encoding='utf-8') as f:
    after = json.load(f)
print(f'[WIPE_OK] transactional_tickets.json: {before_count} tickets -> {len(after)} tickets')
print(f'[BACKUP]  {ts_bak}')

# --- Step 2: Wipe shadow_state.json ---
if os.path.exists(shadow_file):
    with open(shadow_file, 'r', encoding='utf-8') as f:
        shadow_data = json.load(f)
    shadow_count = len(shadow_data.get('shadow_positions', {}))
    shutil.copy2(shadow_file, shadow_bak)
    print(f'[BACKUP]  {shadow_bak}')
else:
    shadow_count = 0

clean_shadow = {'shadow_positions': {}, 'last_updated': datetime.datetime.utcnow().isoformat()}
with open(shadow_file, 'w', encoding='utf-8') as f:
    json.dump(clean_shadow, f, indent=2)
print(f'[WIPE_OK] shadow_state.json: {shadow_count} shadow positions -> 0')

# --- Verification ---
with open(ts_file, 'r', encoding='utf-8') as f:
    verify_ts = json.load(f)
with open(shadow_file, 'r', encoding='utf-8') as f:
    verify_shadow = json.load(f)

registry_count = len(verify_ts)
shadow_positions_count = len(verify_shadow.get('shadow_positions', {}))
print(f'[VERIFY]  registry_count       = {registry_count}')
print(f'[VERIFY]  shadow_positions     = {shadow_positions_count}')

if registry_count == 0 and shadow_positions_count == 0:
    print('[HARD_RESET] CONFIRMED: Both files are at 0 records. Proceeding to code patches.')
else:
    print('[ERROR] Files not fully wiped - check manually!')
