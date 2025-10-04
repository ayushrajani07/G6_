@echo off
REM G6 Live Dashboard - Simple Batch Launcher
REM This starts the live dashboard with all panels refreshing every 5 seconds

echo Starting G6 Live Dashboard...
echo ==============================
echo.
echo Unified dashboard (single process: panels + UI)
echo Panels written by unified summary loop (PanelsWriter)
echo UI frame refresh every 2 seconds
echo.
echo Press Ctrl+C to stop
echo.

REM Set panels directory (auto-detect governs behavior; legacy panels toggle removed)
set G6_PANELS_DIR=data/panels

echo Launching unified summary dashboard...
echo.
C:/Users/ASUS/Documents/G6/qq/g6_reorganized/.venv/Scripts/python.exe -m scripts.summary.app --refresh 2
echo.
echo Dashboard stopped.
pause