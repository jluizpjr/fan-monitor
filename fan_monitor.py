
#!/usr/bin/env python3
"""
Fan Monitor with Correct Temperature Logging and Color Output

- Accurate °C formatting
- Color-coded logs:
    * Blue: <10°C
    * Green: 10–40°C
    * Yellow: 41–60°C
    * Red: >60°C
"""

import time
import logging
import subprocess
import re
import sys
from liquidctl import find_liquidctl_devices

# Configuration
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

# Color formatter based on temperature
class TempColorFormatter(logging.Formatter):
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'

    def format(self, record):
        message = super().format(record)
        temp_match = re.search(r'(\d+(?:\.\d+)?)\s*°C', message)
        if temp_match:
            temp = float(temp_match.group(1))
            if temp < 10:
                return f"{self.BLUE}{message}{self.RESET}"
            elif temp <= 40:
                return f"{self.GREEN}{message}{self.RESET}"
            elif 41 <= temp <= 60:
                return f"{self.YELLOW}{message}{self.RESET}"
            else:
                return f"{self.RED}{message}{self.RESET}"
        return message

# Setup logger
handler = logging.FileHandler(LOG_FILE)
handler.setFormatter(TempColorFormatter('%(asctime)s [%(levelname)s] %(message)s'))
logging.getLogger().handlers = []
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)

# Email alerts
def send_email(subject, message):
    try:
        subprocess.run(['mail', '-s', subject, 'root'], input=message, text=True, check=True)
    except Exception as e:
        logging.error(f"Failed to send email '{subject}': {e}")

def notify_start():
    send_email("✅ Fan Monitor Started", "Monitoring started successfully.")

def notify_stop(reason="normal"):
    if reason == "normal":
        send_email("🛑 Fan Monitor Stopped", "Service stopped normally.")
    else:
        send_email("❌ Fan Monitor Crashed", f"Error: {reason}")

# Read NVMe temperatures (excluding Sensor 2)
def get_nvme_temperatures():
    temps = []
    try:
        output = subprocess.check_output(['lsblk', '-dno', 'NAME,TYPE'], text=True)
        devices = [line.split()[0] for line in output.splitlines() if 'nvme' in line and 'disk' in line]
        for dev in devices:
            try:
                data = subprocess.check_output(['smartctl', '-A', f'/dev/{dev}'], text=True).splitlines()
                for line in data:
                    match = re.match(r'(Temperature.*?)\s*:\s*(\d+)', line)
                    if match:
                        label = match.group(1).strip()
                        temp = int(match.group(2))
                        if "Sensor 2" not in label and temp > 0:
                            temps.append((f"{dev} ({label})", temp))
            except Exception as e:
                logging.warning(f"Failed to read /dev/{dev}: {e}")
    except Exception as e:
        logging.error(f"Failed to list NVMe devices: {e}")
    return temps

# Main function
def main():
    logging.info("Fan monitor service starting...")
    notify_start()

    devices = find_liquidctl_devices()
    commander = next((d for d in devices if "Commander Core XT" in d.description), None)

    if not commander:
        logging.error("Commander Core XT not found.")
        notify_stop("Commander Core XT not found")
        return 1

    rad_speed = FAN_SPEED_INITIAL
    chs_speed = FAN_SPEED_INITIAL
    last_rad = last_chs = None

    try:
        with commander.connect():
            logging.info("Initializing device...")
            commander.initialize()
    except Exception as e:
        notify_stop(f"Initialization error: {e}")
        return 1

    while True:
        try:
            time.sleep(CHECK_INTERVAL)
            nvme_temps = get_nvme_temperatures()
            max_nvme = max((t for _, t in nvme_temps), default=0)
            for label, temp in nvme_temps:
                logging.info(f"NVMe {label}: {temp:.1f}°C")

            with commander.connect():
                status = commander.get_status()
                temp_in = temp_out = None
                for key, val, unit in status:
                    if key == "Temperature 1":
                        temp_in = float(val)
                        logging.info(f"Radiator IN: {temp_in:.1f}°C")
                    elif key == "Temperature 0":
                        temp_out = float(val)
                        logging.info(f"Radiator OUT: {temp_out:.1f}°C")
                if temp_in is not None and temp_out is not None:
                    delta = round(temp_in - temp_out, 2)
                    logging.info(f"Radiator ΔT: {delta:.2f}°C")

                # Emergency trigger
                if (temp_in and temp_in > CRITICAL_RADIATOR_TEMP) or any(t > CRITICAL_NVME_TEMP for _, t in nvme_temps):
                    reason = f"CRITICAL TEMP — Radiator IN: {temp_in:.1f}°C, NVMe MAX: {max_nvme:.1f}°C"
                    logging.critical(reason)
                    for i in range(1, 6):
                        commander.set_fixed_speed(f"fan{i}", 100)
                    send_email("⚠️ CRITICAL TEMPERATURE", reason)
                    continue

                # Radiator fan control
                if temp_in:
                    if temp_in > RADIATOR_TEMP_MAX:
                        rad_speed = min(rad_speed + 5, FAN_SPEED_MAX)
                    elif temp_in < (RADIATOR_TEMP_MIN - FAN_HYSTERESIS):
                        rad_speed = max(rad_speed - 5, FAN_SPEED_MIN)

                # Chassis fan control
                if max_nvme > NVME_TEMP_MAX:
                    chs_speed = min(chs_speed + 5, FAN_SPEED_MAX)
                elif max_nvme < (NVME_TEMP_MIN - FAN_HYSTERESIS):
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
            logging.info("Service interrupted by user.")
            notify_stop("normal")
            sys.exit(0)
        except Exception as e:
            logging.error(f"Unhandled exception: {e}")
            notify_stop(str(e))
            sys.exit(1)

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        logging.critical(f"Fatal error: {e}")
        notify_stop(str(e))
        sys.exit(1)
