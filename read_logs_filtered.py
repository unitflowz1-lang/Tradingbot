import json
with open('logs/forex_bot.log', 'r') as f:
    lines = f.readlines()
    for line in lines[-200:]: # Read more lines
        try:
            data = json.loads(line)
            msg = data.get('message', '')
            level = data.get('level', '')
            logger = data.get('logger', '')
            print(f"[{level}] {logger}: {msg}")
        except:
            pass
