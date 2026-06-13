@echo off
REM ============================================================
REM  PRC SCAL AI (Hviel) - LOCAL DEMO LAUNCHER
REM  Double-click this file to start the app for a presentation.
REM  Login PIN: 1509   |   URL: http://127.0.0.1:8000
REM ============================================================
title PRC SCAL AI (Hviel) - Local Server
cd /d "%~dp0"

set "PYEXE=C:\Users\Asus\AppData\Local\Programs\Python\Python313\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

echo.
echo  Starting PRC SCAL AI (Hviel) local server...
echo  This window must stay OPEN during the demo.
echo  When you are done, close this window to stop the server.
echo.

REM Open the browser after the server has had time to boot (~12s)
start "" /b cmd /c "timeout /t 12 /nobreak >nul & start """" http://127.0.0.1:8000"

"%PYEXE%" -m uvicorn app:app --host 127.0.0.1 --port 8000
pause
