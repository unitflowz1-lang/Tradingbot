@echo off
echo ==========================================
echo MT5 Final Connection Test - Administrator
echo ==========================================
echo.

REM Check if running as admin
net session >nul 2>&1
if %errorLevel% == 0 (
    echo ✅ Running as Administrator
) else (
    echo ❌ NOT running as Administrator
    echo.
    echo Please right-click this file and select "Run as administrator"
    echo.
    pause
    exit /b 1
)

echo.
echo 🔄 Setting up environment...
cd /d "%~dp0"
call .venv\Scripts\activate.bat

echo.
echo 🧪 Testing existing MT5 session...
python test_existing_session.py

echo.
echo 🚀 Testing full connection...
python test_current_account.py

echo.
echo ✅ Tests completed!
echo.
echo If successful, you can now run:
echo   python main.py
echo.
pause