@echo off
rem Recompute rankings from the full archive -> data\out\use_cases_enriched.csv
rem   (import that CSV into Cameo via the generic table, see README)
cd /d "%~dp0\.."
where py >nul 2>nul && (py -3 resolve.py %*) || (python resolve.py %*)
pause
