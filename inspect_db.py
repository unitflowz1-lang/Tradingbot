"""Inspect signal_tracking.db and macro_risk_cache.json before wipe."""
import sqlite3, os, json

db_path = os.path.join('data', 'signal_tracking.db')
if not os.path.exists(db_path):
    print('[INFO] signal_tracking.db does not exist')
else:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall()]
    print(f'Tables in signal_tracking.db: {tables}')
    for table in tables:
        cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        count = cur.fetchone()[0]
        print(f'  {table}: {count} rows')
        # Show sample row
        cur.execute(f'SELECT * FROM "{table}" LIMIT 2')
        rows = cur.fetchall()
        for row in rows:
            print(f'    SAMPLE: {row}')
    con.close()

# macro_risk_cache
mc_path = os.path.join('data', 'macro_risk_cache.json')
if os.path.exists(mc_path):
    with open(mc_path, 'r', encoding='utf-8') as f:
        mc = json.load(f)
    print(f'\nmacro_risk_cache.json contents:')
    print(json.dumps(mc, indent=2))
