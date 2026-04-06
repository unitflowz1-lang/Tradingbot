with open('logs/forex_bot.log', 'r') as f:
    lines = f.readlines()
    for line in lines[-5:]:
        print(repr(line.strip()))
