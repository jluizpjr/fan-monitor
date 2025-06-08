
# Fan Monitor for Corsair Commander Core XT and NVMe SSDs

This project provides a robust and fully-featured fan monitoring and control service designed for systems using the Corsair Commander Core XT and NVMe SSDs. It includes real-time temperature monitoring, smart fan speed regulation, emergency response for critical temperatures, and email alerts for system events.

## Features

- ✅ Continuous monitoring of radiator temperatures (input and output)
- ✅ Monitoring of all installed NVMe SSD temperatures
- ✅ Smart control of radiator fans (1–3) and chassis fans (4–5)
- ✅ Automatic hysteresis control to avoid fan speed oscillation
- ✅ Emergency override: all fans set to 100% on critical temperature detection
- ✅ Email alerts on:
  - Service startup
  - Normal shutdown or manual stop
  - Crash or unexpected termination
  - Critical temperature events

## System Requirements

- Python 3.x
- `liquidctl` installed and working
- `smartctl` (from `smartmontools`)
- Mail system installed and configured (e.g., `mailutils`)
- Linux OS (tested on Debian/Ubuntu)

## Installation

### Step 1: Install Dependencies

```bash
sudo apt update
sudo apt install python3 pip smartmontools mailutils
pip3 install liquidctl
```

### Step 2: Clone the Repository and Run Installer

```bash
git clone https://github.com/YOUR_USERNAME/fan-monitor.git
cd fan-monitor
sudo ./install_fan_monitor.sh
```

> Note: Make sure `fan_monitor.py`, `install_fan_monitor.sh`, and `fan-monitor.service` are in the same directory.

### Step 3: Check Service Status

```bash
sudo systemctl status fan-monitor.service
```

## Fan Mapping

- **Fan 1–3**: Top, middle, and bottom radiator fans
- **Fan 4–5**: General chassis cooling fans

## Temperature Thresholds

| Component        | Normal Range | Max Threshold | Critical Shutdown |
|------------------|---------------|----------------|-------------------|
| Radiator IN      | 35–45°C       | >45°C          | >60°C             |
| NVMe SSDs        | 30–70°C       | >70°C          | >75°C             |

## Logging

- Log file location: `/var/log/fan_monitor.log`
- Includes detailed temperature readings, fan speed changes, and event logs

## Email Alerts

- Uses the system's mail utility to send notifications to `root`
- You can forward root's mail to your personal email using `aliases` or `mail forwarding`

## Uninstallation

```bash
sudo systemctl disable --now fan-monitor.service
sudo rm /usr/local/bin/fan_monitor.py
sudo rm /etc/systemd/system/fan-monitor.service
sudo rm /var/log/fan_monitor.log
sudo systemctl daemon-reload
```

## Contributing

Contributions and improvements are welcome! Feel free to submit a pull request or open an issue.

## License

This project is licensed under the MIT License.

## Author

João Luiz Pereira Junior  
📧 Email: [jluizpjr@gmail.com](mailto:jluizpjr@gmail.com)
