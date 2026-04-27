import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

print("=" * 70)
print("BROKER IMPORT DEBUG")
print("=" * 70)

print("\n1. Checking if src/data/mt5_broker.py exists...")
if os.path.exists("src/data/mt5_broker.py"):
    print("   ✓ File exists")
else:
    print("   ✗ File NOT found")

print("\n2. Checking what's actually exported from src.data.mt5_broker...")
try:
    import src.data.mt5_broker as broker_module
    print(f"   ✓ Module imported: {broker_module}")
    
    # List all classes in the module
    classes = [name for name in dir(broker_module) if not name.startswith('_')]
    print(f"\n   Available exports: {classes[:10]}")  # Show first 10
    
    # Check for specific classes
    for class_name in ['MT5Broker', 'MT5BrokerInterface', 'MockBroker']:
        if hasattr(broker_module, class_name):
            print(f"   ✓ Found: {class_name}")
        else:
            print(f"   ✗ NOT found: {class_name}")
            
except ImportError as e:
    print(f"   ✗ Import failed: {e}")
except Exception as e:
    print(f"   ✗ Error: {e}")

print("\n3. Trying direct import of MT5Broker...")
try:
    from src.data.mt5_broker import MT5Broker
    print("   ✓ MT5Broker imported successfully")
except ImportError as e:
    print(f"   ✗ Failed: {e}")
except Exception as e:
    print(f"   ✗ Error: {e}")

print("\n4. Trying direct import of MT5BrokerInterface...")
try:
    from src.data.mt5_broker import MT5BrokerInterface
    print("   ✓ MT5BrokerInterface imported successfully")
except ImportError as e:
    print(f"   ✗ Failed: {e}")
except Exception as e:
    print(f"   ✗ Error: {e}")

print("\n5. Checking for circular imports...")
try:
    import src.data.mt5_broker
    print("   ✓ No circular import detected")
except Exception as e:
    print(f"   ✗ Circular import or other error: {e}")

print("\n" + "=" * 70)
