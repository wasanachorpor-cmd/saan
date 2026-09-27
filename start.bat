@echo off
cd /d "%~dp0"
title S.A.A.N.

netstat -ano | findstr "127.0.0.1:8000" | findstr "LISTENING" >nul
if %errorlevel%==0 (
  start "" "http://127.0.0.1:8000"
  exit /b 0
)

echo.
echo  S.A.A.N. is starting.
echo  Leave this window open. Closing it turns the site off.
echo.
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8000"
py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
echo.
echo  The site has stopped. Press any key to close.
pause >nul
