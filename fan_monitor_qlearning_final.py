
#!/usr/bin/env python3
"""
Fan Monitor with Q-learning (Final Version)

- Logs to file (/var/log) without ANSI codes
- Displays color-coded logs in terminal
- Fixes NVMe temperature readings
"""

import time
import logging
import subprocess
import csv
import os
import random
import signal
import sys
import re
from liquidctl import find_liquidctl_devices

DATA_FILE = "/var/log/fan_monitor_data.csv"
LOG_FILE = "/var/log/fan_monitor_qlearning.log"

ALPHA = 0.1
GAMMA = 0.9
EPSILON = 0.2

FAN_SPEEDS = [40, 50, 60, 70, 80, 100]
TEMP_WEIGHT = 1.0
NOISE_WEIGHT = 0.05

Q = {}

class TempColorFormatter(logging.Formatter):
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'

    def format(self, record):
        message = super().format(record)
        match = re.search(r'(\d+(\.\d+)?)\s*°C', message)
        if match:
            temp = float(match.group(1))
            if temp < 10:
                return f"{self.BLUE}{message}{self.RESET}"
            elif temp <= 40:
                return f"{self.GREEN}{message}{self.RESET}"
            elif temp <= 60:
                return f"{self.YELLOW}{message}{self.RESET}"
            else:
                return f"{self.RED}{message}{self.RESET}"
        return message

# Logging setup
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(TempColorFormatter('%(asctime)s [%(levelname)s] %(message)s'))

logging.getLogger().handlers = []
logging.getLogger().addHandler(file_handler)
logging.getLogger().addHandler(console_handler)
logging.getLogger().setLevel(logging.INFO)

def signal_handler(sig, frame):
    logging.info("Shutting down fan monitor.")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def get_temperatures(commander):
    radiator_in = 0
    try:
        with commander.connect():
            status = commander.get_status()
            for key, val, unit in status:
                if key == "Temperature 1":
                    radiator_in = float(val)
    except Exception as e:
        logging.error(f"Error getting radiator temp: {e}")

    nvme_max = 0
    try:
        result = subprocess.check_output(['lsblk', '-dno', 'NAME,TYPE'], text=True)
        devices = [line.split()[0] for line in result.splitlines() if 'nvme' in line and 'disk' in line]
        logging.info(f"Detected NVMe devices: {devices}")
        for dev in devices:
            try:
                smart = subprocess.check_output(['smartctl', '-A', f'/dev/{dev}'], text=True)
                for line in smart.splitlines():
                    if "Temperature" in line and "Sensor 2" not in line:
                        match = re.search(r'(\d+)[ °]*C', line)
                        if match:
                            temp = int(match.group(1))
                            nvme_max = max(nvme_max, temp)
            except subprocess.CalledProcessError as e:
                logging.warning(f"smartctl failed for /dev/{dev}: {e}")
            except Exception as e:
                logging.warning(f"Error parsing smartctl output for /dev/{dev}: {e}")
    except Exception as e:
        logging.error(f"Error listing NVMe devices: {e}")

    return radiator_in, nvme_max

def estimate_noise(fan_rad, fan_chs):
    return pow(fan_rad, 1.5) + pow(fan_chs, 1.5)

def get_state(temp_rad, temp_nvme):
    return (int(temp_rad // 5), int(temp_nvme // 5))

def choose_action(state):
    if state not in Q:
        Q[state] = {}
        for r in FAN_SPEEDS:
            for c in FAN_SPEEDS:
                Q[state][(r, c)] = 0.0
    if random.random() < EPSILON:
        return random.choice(list(Q[state].keys()))
    return max(Q[state], key=Q[state].get)

def update_q(state, action, reward, next_state):
    if next_state not in Q:
        Q[next_state] = {}
        for r in FAN_SPEEDS:
            for c in FAN_SPEEDS:
                Q[next_state][(r, c)] = 0.0
    max_future_q = max(Q[next_state].values())
    Q[state][action] += ALPHA * (reward + GAMMA * max_future_q - Q[state][action])

def log_data(timestamp, state, action, reward, temp_rad, temp_nvme, noise):
    exists = os.path.exists(DATA_FILE)
    with open(DATA_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(['timestamp', 'state_rad', 'state_nvme', 'fan_rad', 'fan_chs',
                             'temp_rad', 'temp_nvme', 'noise_est', 'reward'])
        writer.writerow([timestamp, state[0], state[1], action[0], action[1],
                         temp_rad, temp_nvme, noise, reward])

def main():
    logging.info("Starting Q-learning fan monitor...")
    devices = find_liquidctl_devices()
    commander = next((d for d in devices if "Commander Core XT" in d.description), None)

    if not commander:
        logging.error("Commander Core XT not found.")
        sys.exit(1)

    while True:
        temp_rad, temp_nvme = get_temperatures(commander)
        state = get_state(temp_rad, temp_nvme)

        action = choose_action(state)
        fan_rad, fan_chs = action

        try:
            with commander.connect():
                for i in range(1, 4):
                    commander.set_fixed_speed(f"fan{i}", fan_rad)
                for i in range(4, 6):
                    commander.set_fixed_speed(f"fan{i}", fan_chs)
        except Exception as e:
            logging.error(f"Failed to set fan speeds: {e}")

        time.sleep(10)

        temp_rad_new, temp_nvme_new = get_temperatures(commander)
        next_state = get_state(temp_rad_new, temp_nvme_new)

        noise = estimate_noise(fan_rad, fan_chs)
        temp_score = temp_rad_new + temp_nvme_new
        reward = - (TEMP_WEIGHT * temp_score + NOISE_WEIGHT * noise)

        update_q(state, action, reward, next_state)

        log_data(time.strftime('%Y-%m-%d %H:%M:%S'), state, action, reward,
                 temp_rad_new, temp_nvme_new, noise)

        logging.info(f"Radiator IN: {temp_rad_new:.1f}°C | NVMe MAX: {temp_nvme_new:.1f}°C | "
                     f"Fan R/C: {fan_rad}%/{fan_chs}% | Reward: {reward:.2f}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.critical(f"Fatal error: {e}")
        sys.exit(1)
