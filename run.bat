@echo off
setlocal
cd /d "%~dp0"
call conda activate apichat >nul 2>nul
if errorlevel 1 goto noconda
if not exist "%CONDA_PREFIX%\pythonw.exe" goto nopythonw
start "" "%CONDA_PREFIX%\pythonw.exe" "%~dp0app.py"
exit /b 0

:noconda
echo [API Chat] Conda environment "apichat" was not found.
echo Please run setup_env.bat first.
pause
exit /b 1

:nopythonw
echo [API Chat] pythonw.exe was not found in the apichat environment.
echo Please recreate the environment with setup_env.bat.
pause
exit /b 1
