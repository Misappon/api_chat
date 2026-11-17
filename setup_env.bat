@echo off
setlocal
cd /d "%~dp0"
where conda >nul 2>nul
if errorlevel 1 goto noconda
conda env list | findstr /C:"apichat" >nul 2>nul
if errorlevel 1 goto createenv
echo [API Chat] Conda environment apichat already exists.
goto install

:createenv
echo [API Chat] Creating conda environment apichat ...
conda create -n apichat python=3.11 -y
if errorlevel 1 goto createfail

:install
echo [API Chat] Installing Python dependencies ...
call conda run -n apichat python -m pip install -r requirements.txt
if errorlevel 1 goto installfail
echo.
echo Done. Double-click run.bat to start API Chat.
pause
exit /b 0

:noconda
echo [API Chat] conda was not found in PATH.
echo Install Miniconda or Anaconda and add conda to PATH first.
pause
exit /b 1

:createfail
echo [API Chat] Failed to create the environment.
echo If the conda network is blocked, try:
echo     conda create -n apichat python=3.11 -y --offline
pause
exit /b 1

:installfail
echo [API Chat] Failed to install dependencies. Check the network and retry.
pause
exit /b 1
