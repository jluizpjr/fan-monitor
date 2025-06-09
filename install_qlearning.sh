
#!/bin/bash
echo "Installing..."
systemctl stop fan_monitor_qlearning.service
systemctl disable fan_monitor_qlearning.service
cp fan_monitor_qlearning.py /usr/local/bin/
chmod +x /usr/local/bin/fan_monitor_qlearning.py
cp fan_monitor_qlearning.service /etc/systemd/system/
systemctl daemon-reexec
systemctl daemon-reload
systemctl enable fan_monitor_qlearning.service
systemctl start fan_monitor_qlearning.service
echo "Done."
