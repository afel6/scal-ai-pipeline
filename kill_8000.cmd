@echo off
echo Attempting to forcefully terminate any process locked on Port 8000...
FOR /F "tokens=5" %%a in ('netstat -aon ^| findstr :8000') do (
  if not "%%a"=="0" (
    echo Killing Process ID %%a
    taskkill /F /PID %%a
  )
)
echo Port 8000 successfully bypassed.
