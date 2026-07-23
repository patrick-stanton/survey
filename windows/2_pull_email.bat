@echo off
rem Pull survey results from your mailbox into data\inbox (IMAP; optional)
cd /d "%~dp0\.."
where py >nul 2>nul && (py -3 pull_email.py %*) || (python pull_email.py %*)
pause
