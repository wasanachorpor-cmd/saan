@echo off
cd /d "%~dp0"
title S.A.A.N.
netstat -ano | findstr "127.0.0.1:8000" | findstr "LISTENING" >nul
if %errorlevel%==0 exit /b 0
py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
