@echo off
rem Validate everything in data\inbox into the append-only archive
cd /d "%~dp0\.."
where py >nul 2>nul && (py -3 ingest.py %*) || (python ingest.py %*)
pause
