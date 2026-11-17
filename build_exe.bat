@echo off
setlocal
cd /d "%~dp0"
call conda activate apichat >nul 2>nul
if errorlevel 1 goto noconda
python -m pip install pyinstaller
if errorlevel 1 goto pipfail
pyinstaller --noconfirm --clean APIChat.spec
if errorlevel 1 goto buildfail
echo.
echo Build complete: dist\APIChat\APIChat.exe
pause
exit /b 0

:noconda
echo [API Chat] Conda environment "apichat" was not found.
echo Please run setup_env.bat first.
pause
exit /b 1

:pipfail
echo [API Chat] Failed to install PyInstaller.
pause
exit /b 1

:buildfail
echo [API Chat] PyInstaller build failed.
pause
exit /b 1
