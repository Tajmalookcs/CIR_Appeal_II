@echo off
REM ============================================================
REM  Helper used by "Start Appeals System.vbs".
REM  Do not double-click this file directly - it will show a
REM  console window. Use the .vbs launcher instead.
REM ============================================================

cd /d "%~dp0"

if not exist "logs" mkdir "logs"

echo. >> "logs\server.log"
echo ==================================================== >> "logs\server.log"
echo  Appeals System started %DATE% %TIME% >> "logs\server.log"
echo ==================================================== >> "logs\server.log"

REM 0.0.0.0 listens on every network card, so other PCs on the LAN can reach it.
REM Use 127.0.0.1 instead to restrict the system to this machine only.
"%~dp0venv\Scripts\python.exe" "%~dp0manage.py" runserver 0.0.0.0:%1 --noreload >> "logs\server.log" 2>&1

echo  Appeals System stopped %DATE% %TIME% >> "logs\server.log"
