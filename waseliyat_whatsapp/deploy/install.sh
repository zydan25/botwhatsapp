#!/usr/bin/env bash
set -euo pipefail
APP_DIR="/home/root/projects/waseliyat_whatsapp"
SERVICE="waseliyat.service"

cd "$APP_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created $APP_DIR/.env — edit it before starting the service."
fi

install -m 0644 deploy/waseliyat.service /etc/systemd/system/$SERVICE
systemctl daemon-reload
systemctl enable --now waseliyat
systemctl --no-pager --full status waseliyat || true
