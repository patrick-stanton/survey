@echo off
rem Map retired use cases to current ones (interactive) after a catalog change
cd /d "%~dp0\.."
where py >nul 2>nul && (py -3 reconcile.py %*) || (python reconcile.py %*)
pause
