@echo off
echo ========================================
echo Document Q&A System - Quick Start
echo ========================================
echo.

echo Step 1: Checking Python installation...
python --version
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH
    pause
    exit /b 1
)
echo.

echo Step 2: Creating virtual environment...
if exist .venv (
    echo Virtual environment already exists, skipping...
) else (
    python -m venv .venv
    echo Virtual environment created!
)
echo.

echo Step 3: Activating virtual environment...
call .venv\Scripts\activate.bat
echo.

echo Step 4: Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo.

echo Step 5: Generating demo documents...
python scripts/make_samples.py
if %errorlevel% neq 0 (
    echo WARNING: Failed to generate samples, but continuing...
)
echo.

echo Step 6: Running smoke test to verify Azure services...
python scripts/smoke_test.py
if %errorlevel% neq 0 (
    echo WARNING: Smoke test failed - please check your .env configuration
    pause
)
echo.

echo ========================================
echo Setup Complete!
echo ========================================
echo.
echo To start the application, run these commands:
echo.
echo Terminal 1 - Backend API:
echo   .venv\Scripts\activate
echo   uvicorn src.api.main:app --reload
echo.
echo Terminal 2 - Frontend UI:
echo   .venv\Scripts\activate
echo   streamlit run frontend/app.py
echo.
echo Then open: http://localhost:8501
echo ========================================
pause
