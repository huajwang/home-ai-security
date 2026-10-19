@echo off
REM Listen on an Anker PowerConf and send transcripts to the ROCK 5T hub.
cd /d "%~dp0\.."
:again
python -m satellites.pc_assistant --listen --device PowerConf --hub-url https://10.0.0.83:8443
echo Voice satellite stopped. Restarting in 5 seconds...
timeout /t 5 /nobreak >nul
goto again
