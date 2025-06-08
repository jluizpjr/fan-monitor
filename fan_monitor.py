
#!/usr/bin/env python3
"""
Fan Monitor for Corsair Commander Core XT and NVMe SSDs

- Controls radiator and chassis fans
- Monitors radiator input/output and NVMe SSD temperatures
- Sends email alerts on start, stop (normal/exception), and critical overheating
"""

import time
import logging
import subprocess
import re
import sys
from liquidctl import find_liquidctl_devices

# ======================
# Configuration
# ======================

LOG_FILE = '/var/log/fan_monitor.log'

RADIATOR_TEMP_MAX = 45
RADIATOR_TEMP_MIN = 35
NVME_TEMP_MAX = 70
NVME_TEMP_MIN = 30

CRITICAL_RADIATOR_TEMP = 60
CRITICAL_NVME_TEMP = 75

FAN_HYSTERESIS = 2
FAN_SPEED_MAX = 100
FAN_SPEED_MIN = 30
FAN_SPEED_INITIAL = 40

CHECK_INTERVAL = 30

# ======================
# Logging
# ======================

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)

# ======================
# Email Notification
# ======================

def send_email(subject, message):
    try:
        subprocess.run(
            ['mail', '-s', subject, 'jluizpjr@gmail.com'],
            input=message,
            text=True,
            check=True
        )
    except Exception as e:
        logging.error(f"Failed to send email '{subject}': {e}")

def notify_start():
    send_email("✅ Fan Monitor Started", "Service started successfully. Monitoring temperatures.")

def notify_stop(reason="normal"):
    if reason == "normal":
        subject = "🛑 Fan Monitor Stopped"
        message = "Service was stopped normally."
    else:
        subject = "❌ Fan Monitor Crashed"
        message = f"Service stopped due to an error: {reason}"
    send_email(subject, message)

# ======================
# Temperature Functions
# ======================

def get_nvme_temperatures():
    temps = []
    try:
        output = subprocess.check_output(['lsblk', '-dno', 'NAME,TYPE'], text=True)
        devices = [line.split()[0] for line in output.splitlines() if 'nvme' in line and 'disk' in line]
        for dev in devices:
            try:
                data = subprocess.check_output(['smartctl', '-A', f'/dev/{dev}'], text=True)
                match = re.search(r'Temperature:\s+(\d+)', data)
                if match:
                    temps.append((dev, int(match.group(1))))
            except Exception as e:
                logging.warning(f"Error reading /dev/{dev}: {e}")
    except Exception as e:
        logging.error(f"Failed to detect NVMe devices: {e}")
    return temps

# ======================
# Main
# ======================

def main():
    logging.info("Fan monitor started.")
    notify_start()

    devices = find_liquidctl_devices()
    commander = next((d for d in devices if "Commander Core XT" in d.description), None)

    if not commander:
        logging.error("Commander Core XT not found.")
        notify_stop("Device not found")
        return 1

    rad_speed = FAN_SPEED_INITIAL
    chs_speed = FAN_SPEED_INITIAL
    last_rad = last_chs = None

    try:
        with commander.connect():
            logging.info("Initializing device.")
            commander.initialize()
    except Exception as e:
        notify_stop(str(e))
        return 1

    while True:
        try:
            time.sleep(CHECK_INTERVAL)
            nvme = get_nvme_temperatures()
            max_nvme = max((t for _, t in nvme), default=0)

            with commander.connect():
                status = commander.get_status()
                temp_in = temp_out = None

                for key, val, unit in status:
                    if key == "Temperature 1":
                        temp_in = val
                        logging.info(f"Radiator IN: {val}°{unit}")
                    elif key == "Temperature 0":
                        temp_out = val
                        logging.info(f"Radiator OUT: {val}°{unit}")

                # Critical temperature condition
                if (temp_in and temp_in > CRITICAL_RADIATOR_TEMP) or any(t > CRITICAL_NVME_TEMP for _, t in nvme):
                    reason = f"CRITICAL TEMP: Radiator={temp_in}°C, NVMe={max_nvme}°C"
                    logging.critical(reason)
                    for i in range(1, 6):
                        commander.set_fixed_speed(f"fan{i}", 100)
                    send_email("⚠️ CRITICAL TEMP ALERT", reason)
                    continue

                # Radiator fans logic
                if temp_in:
                    if temp_in > RADIATOR_TEMP_MAX:
                        rad_speed = min(rad_speed + 5, FAN_SPEED_MAX)
                    elif temp_in < RADIATOR_TEMP_MIN - FAN_HYSTERESIS:
                        rad_speed = max(rad_speed - 5, FAN_SPEED_MIN)

                # Chassis fans logic
                if max_nvme > NVME_TEMP_MAX:
                    chs_speed = min(chs_speed + 5, FAN_SPEED_MAX)
                elif max_nvme < NVME_TEMP_MIN - FAN_HYSTERESIS:
                    chs_speed = max(chs_speed - 5, FAN_SPEED_MIN)

                if rad_speed != last_rad:
                    for i in range(1, 4):
                        commander.set_fixed_speed(f"fan{i}", rad_speed)
                    last_rad = rad_speed
                    logging.info(f"Radiator fans set to {rad_speed}%")

                if chs_speed != last_chs:
                    for i in range(4, 6):
                        commander.set_fixed_speed(f"fan{i}", chs_speed)
                    last_chs = chs_speed
                    logging.info(f"Chassis fans set to {chs_speed}%")

        except KeyboardInterrupt:
            notify_stop("normal")
            logging.info("Stopped by user.")
            sys.exit(0)

        except Exception as e:
            notify_stop(str(e))
            logging.error(f"Unexpected error: {e}")
            sys.exit(1)

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        notify_stop(str(e))
        sys.exit(1)
