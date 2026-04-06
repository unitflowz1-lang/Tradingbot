@echo off
echo Starting MT5 Connection Test as Administrator...
echo.

cd /d "%~dp0"
call .venv\Scripts\activate.bat

echo Testing basic MT5 connection...
python test_mt5_basic.py

echo.
echo Testing full MT5 connection...
python connect_mt5_demo.py

echo.
echo Press any key to exit...
pause > nul