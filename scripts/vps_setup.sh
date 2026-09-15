#!/bin/bash
# VPS Initial Setup Script (Run this ONCE on the VPS as a user with sudo privileges)

echo "Starting VPS Setup for WES Vendor..."

# 1. Update and install dependencies
sudo apt update
sudo apt install -y postgresql postgresql-contrib nginx python3-pip python3-venv git
# PDF Generation dependencies
sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0 libjpeg-dev libopenjp2-7-dev libffi-dev

echo "System dependencies installed."

# 2. Setup App Directory
# Assuming you cloned the repo to /var/www/wes-vendor
if [ ! -d "/var/www/wes-vendor" ]; then
    echo "Warning: /var/www/wes-vendor not found! Please clone the repo there before continuing."
    exit 1
fi

sudo chown -R www-data:www-data /var/www/wes-vendor/uploads 2>/dev/null || true

# 3. Create FastAPI systemd service
cat << 'SERVICE' | sudo tee /etc/systemd/system/wes-vendor.service
[Unit]
Description=WES Vendor FastAPI Application
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/wes-vendor
Environment="PATH=/var/www/wes-vendor/venv/bin"
EnvironmentFile=/var/www/wes-vendor/.env
ExecStart=/var/www/wes-vendor/venv/bin/gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:8000
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE

# 4. Create pgAdmin systemd service
cat << 'SERVICE' | sudo tee /etc/systemd/system/pgadmin.service
[Unit]
Description=pgAdmin4 Web Server
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/wes-vendor/pgadmin_env
Environment="PATH=/var/www/wes-vendor/pgadmin_env/bin"
Environment="PGADMIN_CONFIG_SERVER_MODE=True"
Environment="PGADMIN_DEFAULT_EMAIL=management@wenerbd.com"
Environment="PGADMIN_DEFAULT_PASSWORD=wes_admin_2026"
Environment="PGADMIN_LISTEN_PORT=5050"
ExecStart=/var/www/wes-vendor/pgadmin_env/bin/gunicorn --bind 127.0.0.1:5050 pgadmin4:app
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE

# 5. Enable services
sudo systemctl daemon-reload
sudo systemctl enable wes-vendor
sudo systemctl enable pgadmin

echo "Setup complete! Please configure /var/www/wes-vendor/.env and then run 'sudo systemctl start wes-vendor pgadmin'."
