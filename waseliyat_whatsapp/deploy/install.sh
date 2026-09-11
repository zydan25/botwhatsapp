#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/root/projects/waseliyat"
PM2_APP="waseliyat"

cd "$APP_DIR"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created $APP_DIR/.env — edit it before starting PM2."
fi

# PM2 is the primary process manager for this Flask/Socket.IO app.
if ! command -v pm2 >/dev/null 2>&1; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm is required to install PM2. Install Node.js/npm first." >&2
    exit 1
  fi
  npm install -g pm2
fi

pm2 delete "$PM2_APP" >/dev/null 2>&1 || true
pm2 start ecosystem.config.js
pm2 save

cat <<'EOF'

Waseliyat is now managed by PM2.

Useful commands:
  pm2 status
  pm2 logs waseliyat
  pm2 restart waseliyat
  pm2 stop waseliyat
  pm2 save

To enable automatic PM2 startup after reboot, run:
  pm2 startup
and execute the command PM2 prints, then run:
  pm2 save
EOF

pm2 status "$PM2_APP" || true
