
import os
import sys
from pathlib import Path
import MetaTrader5 as mt5

# Add src to python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import get_config_manager

import ctypes

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def main():
    print("Testing connection with UPDATED credentials...")
    
    # Check Admin - but don't exit, just warn strongly
    if not is_admin():
        print("\n⚠️  WARNING: PROCESS NOT RUNNING AS ADMIN ⚠️")
        print("   Connection will likely fail with 'Authorization failed'.")
        print("   Please restart your terminal as Administrator.\n")
    
    # Force environment to mt5
    os.environ['ENVIRONMENT'] = 'mt5'
    
    config_manager = get_config_manager()
    # Force reload to get simplest latest file content
    config_manager.load_config() 
    
    # Peek at raw config to verify update
    raw_broker_config = config_manager._config.get('broker', {})
    login = raw_broker_config.get('login')
    password = raw_broker_config.get('password')
    server = raw_broker_config.get('server')
    
    print(f"Credentials loaded: Login={login}, Server={server}")
    
    if str(login) != "5044383203":
         print("❌ Error: Config does not match expected new login 5044383203")

    # Initialize MT5
    mt5_path = r"C:\Program Files\MetaTrader 5\terminal64.exe"
    print(f"Initializing MT5 at: {mt5_path}")
    
    if not mt5.initialize(path=mt5_path):
        print(f"❌ Initialization failed: {mt5.last_error()}")
        return

    print("✅ MT5 Initialized")
    
    # Login
    print(f"Attempting login to account {login}...")
    authorized = mt5.login(login=int(login), password=str(password), server=str(server))
    if authorized:
        print(f"🎉 SUCCESS! Connected to account #{login}")
        account_info = mt5.account_info()
        print(f"   Balance: {account_info.balance}")
        print(f"   Equity: {account_info.equity}")
    else:
        print(f"❌ Login failed: {mt5.last_error()}")

    mt5.shutdown()

if __name__ == "__main__":
    main()
