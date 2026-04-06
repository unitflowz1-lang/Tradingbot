import psutil
import os

def kill_terminal():
    found = False
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'] == 'terminal64.exe':
            found = True
            print(f"Found terminal64.exe with PID {proc.info['pid']}")
            try:
                proc.terminate()
                print("Sent terminate signal")
                proc.wait(timeout=5)
                print("Process terminated")
            except Exception as e:
                print(f"Failed to terminate: {e}")
                try:
                    print("Attempting to kill...")
                    proc.kill()
                    print("Killed")
                except Exception as e2:
                    print(f"Failed to kill: {e2}")
    
    if not found:
        print("terminal64.exe not found")

if __name__ == "__main__":
    kill_terminal()
