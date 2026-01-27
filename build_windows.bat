@echo off
echo ========================================
echo AutoScreen Windows Build Script
echo ========================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python from https://python.org
    pause
    exit /b 1
)

:: Create virtual environment if it doesn't exist
if not exist "venv_win" (
    echo Creating virtual environment...
    python -m venv venv_win
)

:: Activate virtual environment and install dependencies
echo Activating virtual environment...
call venv_win\Scripts\activate.bat

echo Installing dependencies...
pip install -r requirements.txt

:: Build the executable
echo.
echo Building AutoScreen.exe...
pyinstaller --onefile --windowed --name "AutoScreen" --icon NONE autoscreen.py

echo.
echo ========================================
if exist "dist\AutoScreen.exe" (
    echo BUILD SUCCESSFUL!
    echo Executable: dist\AutoScreen.exe
    echo.
    echo You can now run the Inno Setup script (setup.iss) to create an installer.
) else (
    echo BUILD FAILED!
    echo Check the output above for errors.
)
echo ========================================
pause
