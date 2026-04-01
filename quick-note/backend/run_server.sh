#!/bin/bash
# ArcusAI Run Backend (Without Virtual Environment)
# Designed for Linux servers where venv is not desired

CURRENT_DIR=$(cd "$(dirname "$0")" && pwd)
cd "$CURRENT_DIR"

echo "=== ArcusAI Backend Service (Linux) ==="
echo "Uruchamianie z katalogu: $CURRENT_DIR"

# Check if Python3 is installed
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 nie jest zainstalowany!"
    exit 1
fi

# Check if mandatory packages are installed
echo "Sprawdzanie wymaganych paczek..."
python3 -c "import fastapi; import uvicorn" &> /dev/null
if [ $? -ne 0 ]; then
    echo "[!] Nie znaleziono wymaganych bibliotek. Proba instalacji globalnej..."
    pip3 install -r requirements.txt
fi

# Verify .env
if [ ! -f .env ]; then
    echo "[!] Brak pliku .env. Uruchamianie kreatora konfiguracji..."
    python3 setup.py
fi

# Execute uvicorn
echo "[+] Uruchamianie serwera na http://0.0.0.0:8000"
echo "[+] Aby zatrzymac: Ctrl+C"

python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
