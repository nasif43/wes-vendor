#!/bin/bash
# VPS Deployment Script (Run this on the VPS whenever you want to update the app to the latest code)

echo "Starting Production Deployment..."

# Ensure we are in the right directory
cd /var/www/wes-vendor || exit

# 1. Pull latest code
sudo -u www-data git pull origin vps-deployment

# 2. Update dependencies
sudo -u www-data bash -c "source venv/bin/activate && pip install -r requirements.txt"

# 3. Restart the Application Service gracefully
sudo systemctl restart wes-vendor

# 4. Check status
sudo systemctl status wes-vendor --no-pager

echo "Deployment Successful!"
