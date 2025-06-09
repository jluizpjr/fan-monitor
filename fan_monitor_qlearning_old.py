import os
import time
import csv
import logging
import smtplib
import numpy as np
from datetime import datetime
from liquidctl import find_liquidctl_devices
import subprocess
import argparse
import glob

LOG_FILE = '/var/log/fan_monitor_qlearning.log'
DATA_FILE = '/var/log/fan_monitor_data.csv'

alpha = 0.05
gamma = 0.9
rad_target = 40.0
nvme_target = 60.0
noise_penalty = 0.3
TEMP_HYSTERESIS = 3.0
rad_min, rad_max = 30, 100
chs_min, chs_max = 30, 100

parser = argparse.ArgumentParser()
parser.add_argument("--debug", action="store_true", help="Enable debug logging")
args = parser.parse_args()

logging.basicConfig(filename=LOG_FILE, level=logging.DEBUG if args.debug else logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def notify_root(subject, message):
    try:
        subprocess.run(['mail', '-s', subject, 'root'], input=message.encode(), check=True)
    except Exception as e:
        logging.error(f"Failed to send email: {e}")

if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'temp_rad', 'temp_nvme', 'fan_rad', 'fan_chs', 'noise_est', 'reward'])

Q = {}
def bucket(temp, step=2):
    return int(temp // step)

temp_rad_hist = []
temp_nvme_hist = []
fan_rad_speed = 50
fan_chs_speed = 50

notify_root("Fan Monitor Started", "Q-learning fan monitor is now active.")

try:
    while True:
        timestamp = datetime.now().isoformat()

        devices = list(find_liquidctl_devices())
        logging.info(f"Found {len(devices)} liquidctl devices.")
        if not devices:
            logging.warning("No liquidctl devices found.")
            time.sleep(10)
            continue

        temp_rad_in = None
        temp_rad_out = None

        target_device = None
        for dev in devices:
            if "Commander Core XT" in dev.description:
                target_device = dev
                break

        if not target_device:
            logging.error("Commander Core XT not found among devices.")
            time.sleep(10)
            continue

        try:
            with target_device.connect():
                status = target_device.get_status()
                logging.info(f"Connected to device: {target_device.description}")
                for key, value, unit in status:
                    logging.debug(f"{key}: {value} {unit}")
                    if "Temperature" in key and "0" in key:
                        try:
                            temp_rad_out = float(str(value).replace("°C", "").strip())
                        except Exception as e:
                            logging.warning(f"Failed to parse temp_rad_out: {value} - {e}")
                    elif "Temperature" in key and "1" in key:
                        try:
                            temp_rad_in = float(str(value).replace("°C", "").strip())
                        except Exception as e:
                            logging.warning(f"Failed to parse temp_rad_in: {value} - {e}")
                logging.info(f"Radiator IN: {temp_rad_in}°C, OUT: {temp_rad_out}°C")
        except Exception as e:
            logging.error(f"Error accessing liquidctl device: {e}")
            time.sleep(10)
            continue

        nvme_devices = glob.glob('/dev/nvme*n1')
        logging.info(f"Detected NVMe devices: {[os.path.basename(dev) for dev in nvme_devices]}")
        nvme_temps = []
        for dev in nvme_devices:
            try:
                result = subprocess.run(['nvme', 'smart-log', dev], capture_output=True, text=True)
                for line in result.stdout.splitlines():
                    if "temperature" in line.lower() and "sensor" not in line.lower():
                        parts = line.split(":")
                        if len(parts) == 2:
                            temp_str = parts[1].strip().split(" ")[0].replace("°C", "")
                            nvme_temp = float(temp_str)
                            if nvme_temp > 0:
                                nvme_temps.append(nvme_temp)
            except Exception as e:
                logging.warning(f"Could not read NVMe temp from {dev}: {e}")

        temp_nvme = max(nvme_temps) if nvme_temps else 0.0

        if temp_rad_in is None:
            logging.warning("No radiator temperature read.")
            time.sleep(10)
            continue

        temp_rad_hist.append(temp_rad_in)
        temp_nvme_hist.append(temp_nvme)
        if len(temp_rad_hist) > 6:
            temp_rad_hist.pop(0)
            temp_nvme_hist.pop(0)

        temp_rad_avg = np.mean(temp_rad_hist)
        temp_nvme_avg = np.mean(temp_nvme_hist)
        state = (bucket(temp_rad_avg), bucket(temp_nvme_avg))
        action = (fan_rad_speed, fan_chs_speed)

        rad_error = abs(temp_rad_avg - rad_target)
        nvme_error = abs(temp_nvme_avg - nvme_target)
        reward = 0 if rad_error < TEMP_HYSTERESIS and nvme_error < TEMP_HYSTERESIS else -(rad_error + nvme_error)
        reward -= noise_penalty * (fan_rad_speed + fan_chs_speed) / 200.0

        if state not in Q:
            Q[state] = {}
        if action not in Q[state]:
            Q[state][action] = 0.0
        Q[state][action] += alpha * (reward - Q[state][action])

        if temp_rad_avg > rad_target + TEMP_HYSTERESIS:
            fan_rad_speed = min(fan_rad_speed + 5, rad_max)
        elif temp_rad_avg < rad_target - TEMP_HYSTERESIS:
            fan_rad_speed = max(fan_rad_speed - 5, rad_min)

        if temp_nvme_avg > nvme_target + TEMP_HYSTERESIS:
            fan_chs_speed = min(fan_chs_speed + 5, chs_max)
        elif temp_nvme_avg < nvme_target - TEMP_HYSTERESIS:
            fan_chs_speed = max(fan_chs_speed - 5, chs_min)

        if temp_rad_in > 60 or temp_nvme > 75:
            fan_rad_speed = 100
            fan_chs_speed = 100
            notify_root("🔥 Critical Temperature", f"Radiator or NVMe overheat detected at {timestamp}!")

        try:
            with target_device.connect():
                target_device.set_fixed_speed("fan1", fan_rad_speed)
                target_device.set_fixed_speed("fan2", fan_rad_speed)
                target_device.set_fixed_speed("fan3", fan_rad_speed)
                target_device.set_fixed_speed("fan4", fan_chs_speed)
                target_device.set_fixed_speed("fan5", fan_chs_speed)
                target_device.set_fixed_speed("fan6", fan_chs_speed)

        except Exception as e:
            logging.error(f"Failed to set fan speeds: {e}")
            time.sleep(10)
            continue

        log_msg = f"[INFO] Radiator IN: {temp_rad_avg:.1f}°C | NVMe MAX: {temp_nvme_avg:.1f}°C | Fan R/C: {fan_rad_speed}%/{fan_chs_speed}% | Reward: {reward:.2f}"
        logging.info(log_msg)
        print(log_msg)

        with open(DATA_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, temp_rad_avg, temp_nvme_avg, fan_rad_speed, fan_chs_speed, (fan_rad_speed+fan_chs_speed)/2, reward])

        time.sleep(10)

except KeyboardInterrupt:
    notify_root("Fan Monitor Stopped", "Fan monitor script exited via KeyboardInterrupt.")
    logging.info("Service interrupted by user.")

except Exception as e:
    notify_root("Fan Monitor Crashed", f"Unexpected error: {e}")
    logging.exception("Unhandled exception")