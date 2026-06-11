@echo off
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 scripts\run_web.py --open
  exit /b %errorlevel%
)

where python >nul 2>nul
if %errorlevel% equ 0 (
  python scripts\run_web.py --open
  exit /b %errorlevel%
)

echo Python 3.10 or newer is required.
pause
exit /b 1
