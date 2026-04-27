import json
with open('logs/forex_bot.log', 'r') as f:
    lines = f.readlines()
    for line in lines[-30:]:
        try:
            data = json.loads(line)
            print(f"[{data.get('level')}] {data.get('message')}")
        except:
            pass
