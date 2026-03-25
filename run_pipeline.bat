@echo off
echo Cleaning up previous instances...
FOR /F "tokens=5" %%a in ('netstat -aon ^| findstr :8000') do (
  if not "%%a"=="0" taskkill /F /PID %%a >nul 2>&1
)
FOR /F "tokens=5" %%a in ('netstat -aon ^| findstr :5173') do (
  if not "%%a"=="0" taskkill /F /PID %%a >nul 2>&1
)

echo Starting SCAL AI Backend (FastAPI) on Port 8000...
start cmd /k "C:\Users\Asus\AppData\Local\Programs\Python\Python313\python.exe -m uvicorn app:app --port 8000"

echo Starting SCAL AI Frontend (React/Vite) on Port 5173...
cd frontend
start cmd /k "npm run dev"

echo.
echo ==================================================
echo SCAL AI Pipeline is booting up locally!
echo.
echo 1. The BACKEND terminal is running Python/Tensorflow.
echo 2. The FRONTEND terminal is running Node/React.
echo.
echo Please open your browser to: http://localhost:5173
echo ==================================================
pause
