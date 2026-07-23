@echo off
rem Quarantine suspect responses (run with no args to see --list usage)
cd /d "%~dp0\.."
where py >nul 2>nul && (py -3 exclude.py --list %*) || (python exclude.py --list %*)
pause
