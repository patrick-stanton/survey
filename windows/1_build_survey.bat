@echo off
rem Build dist\survey.html from data\use_cases.csv + config.yaml
cd /d "%~dp0\.."
where py >nul 2>nul && (py -3 build_survey.py %*) || (python build_survey.py %*)
pause
