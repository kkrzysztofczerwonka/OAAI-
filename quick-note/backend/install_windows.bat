@echo off
setlocal
echo [%date% %time%] === ArcusAI Windows Server Installer ===

:: Check for Python
echo [%date% %time%] [+] Sprawdzanie Pythona...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] %date% %time% - Python nie jest zainstalowany! Pobierz i zainstaluj Python 3.9+ z https://www.python.org/
    echo [TIP] Upewnij sie, ze zaznaczyles "Add Python to PATH" podczas instalacji.
    pause
    exit /b 1
)

:: Check for pip
echo [%date% %time%] [+] Sprawdzanie pip...
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] %date% %time% - pip nie jest zainstalowany! Zainstaluj pip lub napraw instalacje Pythona.
    pause
    exit /b 1
)

:: Install requirements
echo [%date% %time%] [+] Instalowanie zaleznosci z requirements.txt...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] %date% %time% - Blad podczas instalacji zaleznosci.
    pause
    exit /b 1
)

:: Install gunicorn/uvicorn specific tools
echo [%date% %time%] [+] Instalowanie narzedzi serwerowych...
pip install uvicorn
if %errorlevel% neq 0 (
    echo [ERROR] %date% %time% - Blad podczas instalacji uvicorn.
    pause
    exit /b 1
)

:: Run configuration
echo [%date% %time%] [+] Konfiguracja ArcusAI (setup.py)...
python setup.py
if %errorlevel% neq 0 (
    echo [ERROR] %date% %time% - Blad podczas konfiguracji setup.py.
    pause
    exit /b 1
)

echo.
echo ===================================================
echo [%date% %time%] [!] Instalacja zakonczona sukcesem!
echo [!] Aby uruchomic serwer, uzyj pliku: run_windows.bat
echo ===================================================
pause
