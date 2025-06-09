
#!/bin/bash
echo "Installing..."
cp fan_monitor_qlearning_final.py /usr/local/bin/
chmod +x /usr/local/bin/fan_monitor_qlearning_final.py
cp fan_monitor_qlearning_final.service /etc/systemd/system/
systemctl daemon-reexec
systemctl daemon-reload
systemctl enable fan_monitor_qlearning_final.service
systemctl start fan_monitor_qlearning_final.service
echo "Done."
