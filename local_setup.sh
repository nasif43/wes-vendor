#!/bin/bash
# Local Setup Script (No Docker)
# Run this to set up your local environment like the VPS

set -e

DB_USER="wes_user"
DB_NAME="wes_vendor_local"
DB_PASSWORD="changeme"

echo "1. Setting up local PostgreSQL..."
# Ensure postgres is running
sudo systemctl start postgresql || echo "PostgreSQL not found via systemctl. Make sure it's running!"

sudo -u postgres psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';" || true
sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};" || true
sudo -u postgres psql -c "ALTER USER ${DB_USER} CREATEDB;" || true

echo "2. Setting up Application Virtual Environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt

# Create a local .env override if it doesn't exist
cat <<EOF > .env
DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}
UPLOAD_DIR=./uploads
APP_URL=http://localhost:8000
SECRET_KEY=local_secret_key_123
DEBUG=true
EOF

echo "3. Running Database Migrations..."
alembic upgrade head
deactivate

echo "4. Setting up pgAdmin4 natively..."
if [ ! -d "pgadmin_env" ]; then
    python3 -m venv pgadmin_env
    source pgadmin_env/bin/activate
    pip install pgadmin4

    # Setup local config to bind to a standard port
    config_path=$(find pgadmin_env -name "config_local.py" -o -path "*/pgadmin4/config_local.py" 2>/dev/null | head -n 1)
    if [ -z "$config_path" ]; then
        config_path="pgadmin_env/lib/python3.13/site-packages/pgadmin4/config_local.py"
    fi
    mkdir -p $(dirname "$config_path")
    
    cat <<EOF > "$config_path"
import os
DEFAULT_SERVER = '0.0.0.0'
DEFAULT_SERVER_PORT = 5050
EOF

    export PGADMIN_SETUP_EMAIL="admin@local"
    export PGADMIN_SETUP_PASSWORD="admin"
    yes "Y" | pgadmin4 setup
    deactivate
fi

echo ""
echo "================================================="
echo "Local Environment Setup Complete!"
echo "================================================="
echo "To run the app locally, open two terminals:"
echo ""
echo "Terminal 1 (Backend App):"
echo "  source venv/bin/activate"
echo "  uvicorn app.main:app --reload --port 8000"
echo ""
echo "Terminal 2 (pgAdmin GUI):"
echo "  source pgadmin_env/bin/activate"
echo "  pgadmin4"
echo ""
echo "App will be available at http://localhost:8000"
echo "pgAdmin will be available at http://localhost:5050"
echo "pgAdmin Credentials: admin@local / admin"
echo "================================================="
