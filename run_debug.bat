@echo off
setlocal
cd /d "%~dp0"
call conda activate apichat
if errorlevel 1 goto noconda
python app.py
if errorlevel 1 pause
exit /b 0

:noconda
echo [API Chat] Conda environment "apichat" was not found.
echo Please run setup_env.bat first.
pause
exit /b 1
