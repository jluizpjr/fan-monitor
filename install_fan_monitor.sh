#!/bin/bash

SCRIPT_PATH="/usr/local/bin/fan_monitor.py"
SERVICE_PATH="/etc/systemd/system/fan-monitor.service"
LOG_PATH="/var/log/fan_monitor.log"

echo "Installing Fan Monitor Service (English version)..."

# Copy the script
cp fan_monitor.py "$SCRIPT_PATH"
chmod +x "$SCRIPT_PATH"

# Create the log file if it doesn't exist
if [ ! -f "$LOG_PATH" ]; then
    touch "$LOG_PATH"
    chown root:root "$LOG_PATH"
    chmod 644 "$LOG_PATH"
fi

# Copy the systemd service file
cp fan-monitor.service "$SERVICE_PATH"

# Enable and start the service
systemctl daemon-reexec
systemctl daemon-reload
systemctl enable fan-monitor.service
systemctl restart fan-monitor.service

echo "Fan Monitor service installed and started successfully."
