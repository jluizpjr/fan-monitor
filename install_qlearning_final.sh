#!/bin/bash

echo "Installing Fan Monitor Q-learning (Final)..."

# Copy script
cp fan_monitor_qlearning_final.py /usr/local/bin/
chmod +x /usr/local/bin/fan_monitor_qlearning_final.py

# Install service
cp fan_monitor_qlearning_final.service /etc/systemd/system/
systemctl daemon-reexec
systemctl daemon-reload
systemctl enable fan_monitor_qlearning_final.service
systemctl start fan_monitor_qlearning_final.service

echo "Service installed and started successfully."