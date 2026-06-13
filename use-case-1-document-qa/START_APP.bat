@echo off
echo ========================================
echo Document Q&A System - Starting...
echo ========================================
echo.
echo This will open TWO terminal windows:
echo   1. Backend API (FastAPI)
echo   2. Frontend UI (Streamlit)
echo.
echo Keep both windows open while using the app!
echo.
echo Press any key to start...
pause >nul

echo Starting Backend API...
start "Document Q&A - Backend" cmd /k "cd /d %~dp0 && .venv\Scripts\activate && uvicorn src.api.main:app --reload"

timeout /t 3 >nul

echo Starting Frontend UI...
start "Document Q&A - Frontend" cmd /k "cd /d %~dp0 && .venv\Scripts\activate && streamlit run frontend\app.py"

timeout /t 3 >nul

echo.
echo ========================================
echo Application Starting!
echo ========================================
echo.
echo Backend API will run on: http://localhost:8000
echo Frontend UI will run on: http://localhost:8501
echo.
echo Your browser should open automatically.
echo If not, open: http://localhost:8501
echo.
echo To stop: Close both terminal windows
echo ========================================
