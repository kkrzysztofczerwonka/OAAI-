@echo off
setlocal
echo [%date% %time%] === ArcusAI Windows Backend Service ===

:: Change to backend directory if not already there
cd /d "%~dp0"
call "%~dp0venv\Scripts\activate.bat"

echo [%date% %time%] [+] Sprawdzanie czy backend moze wystartowac...
python -c "import fastapi; import uvicorn" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] %date% %time% - Brak wymaganych paczek! Najpierw uruchom: install_windows.bat
    pause
    exit /b 1
)

:: Environment check
if not exist .env (
    echo [WARNING] %date% %time% - Plik .env nie istnieje! Najpierw uruchom: install_windows.bat
    pause
    exit /b 1
)

:: Run the app using uvicorn
echo [%date% %time%] [+] Uruchamianie serwer ArcusAI na http://0.0.0.0:8000
echo [%date% %time%] [+] Logi beda wyswietlane ponizej. Kliknij Ctrl+C aby zatrzymac.
echo.

:: Use --log-level debug for troubleshooting
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4 --log-level debug

if %errorlevel% neq 0 (
    echo.
    echo [CRITICAL] %date% %time% - Serwer przestal dzialac z bledem (Exit Code: %errorlevel%)
    echo [DEBUG] Sprawdz powyzsze komunikaty bledow.
    pause
) else (
    echo.
    echo [%date% %time%] Serwer zostal zatrzymany poprawnie.
    pause
)
