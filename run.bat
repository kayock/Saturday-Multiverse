@echo off
rem Saturday Multiverse - Windows launcher
cd /d "%~dp0"
where py >nul 2>nul && (py -m server.app & goto :eof)
python -m server.app
pause
