#!/bin/bash

# ArcusAI Server Installation Script (Ubuntu/Debian)

echo "=== ArcusAI Server Installer ==="
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv

# Set up project directory (assuming current directory)
CURRENT_DIR=$(pwd)
echo "Instalacja w: $CURRENT_DIR"

# Create Virtual Environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install uvicorn gunicorn

# Run interactive setup
python3 setup.py

# Run BookStack initialization
if [ -f .env ]; then
    echo "Inicjalizacja BookStack..."
    python3 init_bookstack.py
fi

# Create SystemD Service
SERVICE_FILE="/etc/systemd/system/arcus-ai.service"

echo "Tworzenie usługi systemd: $SERVICE_FILE"
sudo bash -c "cat <<EOF > $SERVICE_FILE
[Unit]
Description=ArcusAI Backend Service
After=network.target

[Service]
User=$USER
Group=www-data
WorkingDirectory=$CURRENT_DIR
Environment=\"PATH=$CURRENT_DIR/venv/bin\"
ExecStart=$CURRENT_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4

[Install]
WantedBy=multi-user.target
EOF"

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable arcus-ai
sudo systemctl start arcus-ai

echo "\nInstalacja zakończona! Serwer działa na porcie 8000."
sudo systemctl status arcus-ai
