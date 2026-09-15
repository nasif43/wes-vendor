#!/bin/bash
# VPS Deployment Script (No Docker)
# Run as root or with sudo

set -e

# Configuration variables
APP_DIR="/var/www/wes-vendor"
DB_NAME="wes_vendor"
DB_USER="wes_user"
DB_PASSWORD="secure_db_password" # Change this!
PGADMIN_EMAIL="admin@wes-vendor.local"
PGADMIN_PASSWORD="admin" # Change this!
REPO_URL="https://github.com/nasif43/wes-vendor.git" 

echo "1. Installing OS Dependencies..."
apt update
apt install -y postgresql postgresql-contrib nginx python3-venv python3-pip git curl

echo "2. Setting up PostgreSQL..."
# Create user and DB (ignore errors if they already exist)
sudo -u postgres psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';" || true
sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};" || true
sudo -u postgres psql -c "ALTER USER ${DB_USER} CREATEDB;" || true

echo "3. Setting up Application Directory..."
if [ ! -d "$APP_DIR" ]; then
    mkdir -p /var/www
    git clone -b vps-deployment "$REPO_URL" "$APP_DIR"
else
    cd "$APP_DIR"
    git fetch origin vps-deployment
    git reset --hard origin/vps-deployment
fi

cd "$APP_DIR"

echo "4. Setting up Application Virtual Environment..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Setup .env file for the VPS (Overwrite existing one)
cat <<EOF > .env
DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}
UPLOAD_DIR=./uploads
APP_URL=http://localhost
SECRET_KEY=$(openssl rand -hex 32)
DEBUG=false
EOF

echo "5. Running Database Migrations..."
alembic upgrade head
deactivate

echo "6. Setting up pgAdmin4 natively..."
if [ ! -d "/var/lib/pgadmin" ]; then
    mkdir -p /var/lib/pgadmin /var/log/pgadmin
    chown -R www-data:www-data /var/lib/pgadmin /var/log/pgadmin

    python3 -m venv pgadmin_env
    source pgadmin_env/bin/activate
    pip install pgadmin4 gunicorn

    cat <<EOF > pgadmin_env/lib/python*/site-packages/pgadmin4/config_local.py
import os
LOG_FILE = '/var/log/pgadmin/pgadmin4.log'
SQLITE_PATH = '/var/lib/pgadmin/pgadmin4.db'
SESSION_DB_PATH = '/var/lib/pgadmin/sessions'
STORAGE_DIR = '/var/lib/pgadmin/storage'
EOF

    # Initialize pgAdmin database
    export PGADMIN_SETUP_EMAIL="${PGADMIN_EMAIL}"
    export PGADMIN_SETUP_PASSWORD="${PGADMIN_PASSWORD}"
    yes "Y" | pgadmin4 setup
    deactivate
fi

echo "7. Creating Systemd Services..."
# FastAPI Service
cat <<EOF > /etc/systemd/system/wes-vendor.service
[Unit]
Description=WES Vendor FastAPI Application
After=network.target postgresql.service

[Service]
User=root
Group=www-data
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin"
ExecStart=${APP_DIR}/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# pgAdmin4 Service
cat <<EOF > /etc/systemd/system/pgadmin4.service
[Unit]
Description=pgAdmin4 Web GUI
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/pgadmin_env/bin"
ExecStart=${APP_DIR}/pgadmin_env/bin/gunicorn --bind 127.0.0.1:5050 --workers 1 --threads 8 pgadmin4.pgAdmin4:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable wes-vendor pgadmin4
systemctl restart wes-vendor pgadmin4

echo "8. Configuring Nginx..."
cat <<EOF > /etc/nginx/sites-available/wes-vendor
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /pgadmin/ {
        proxy_set_header X-Script-Name /pgadmin;
        proxy_set_header Host \$host;
        proxy_pass http://127.0.0.1:5050/;
        proxy_redirect off;
    }
}
EOF

ln -sf /etc/nginx/sites-available/wes-vendor /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
systemctl restart nginx

echo "================================================="
echo "Deployment complete!"
echo "App is on port 80: http://<VPS_IP>/"
echo "pgAdmin is at: http://<VPS_IP>/pgadmin"
echo "pgAdmin Login: ${PGADMIN_EMAIL} / ${PGADMIN_PASSWORD}"
echo "================================================="
