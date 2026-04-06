"""Debug import issues"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

print("Starting import debug...")

try:
    print("1. Importing base modules...")
    from src.rl.environments.base import PortfolioState, EnvironmentConfig
    print("   ✅ Base imports OK")
    
    print("2. Importing reward calculator...")
    from src.rl.environments.reward_calculator import RewardCalculator
    print("   ✅ RewardCalculator import OK")
    
    print("3. Importing models...")
    from src.models import MarketData
    print("   ✅ MarketData import OK")
    
    print("4. Importing advanced reward calculator module...")
    import src.rl.environments.advanced_reward_calculator as arc_module
    print(f"   ✅ Module imported, contents: {dir(arc_module)}")
    
    print("5. Checking if classes are defined...")
    if hasattr(arc_module, 'AdvancedRewardCalculator'):
        print("   ✅ AdvancedRewardCalculator found!")
    else:
        print("   ❌ AdvancedRewardCalculator NOT found!")
        
    if hasattr(arc_module, 'AdvancedRewardConfig'):
        print("   ✅ AdvancedRewardConfig found!")
    else:
        print("   ❌ AdvancedRewardConfig NOT found!")
        
    print("6. Trying direct import...")
    from src.rl.environments.advanced_reward_calculator import AdvancedRewardCalculator
    print("   ✅ Direct import successful!")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()