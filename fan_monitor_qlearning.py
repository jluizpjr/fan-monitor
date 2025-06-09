#!/usr/bin/env python3

import os
import time
import csv
import logging
import smtplib # Not directly used, can be removed if 'mail' command is preferred.
import numpy as np
from datetime import datetime
from liquidctl import find_liquidctl_devices
import subprocess
import argparse
import glob
import re # Added for more robust NVMe temperature parsing
import pickle # Added to save and load the Q-table

# --- Configuration Constants ---
LOG_FILE = '/var/log/fan_monitor_qlearning.log'
DATA_FILE = '/var/log/fan_monitor_data.csv'
Q_TABLE_FILE = '/var/lib/fan_monitor_q_table.pkl' # File to save/load the Q-table

# Q-learning and control parameters
ALPHA = 0.05
GAMMA = 0.9 # Not used in current implementation, but good to keep for future expansions
RAD_TARGET_TEMP = 40.0
NVME_TARGET_TEMP = 60.0
NOISE_PENALTY_FACTOR = 0.3
TEMP_HYSTERESIS = 3.0
RAD_FAN_MIN_SPEED = 30
RAD_FAN_MAX_SPEED = 100
CHS_FAN_MIN_SPEED = 30
CHS_FAN_MAX_SPEED = 100
FAN_SPEED_ADJUSTMENT_STEP = 5 # Fan speed adjustment step
TEMP_HISTORY_LENGTH = 6 # Temperature history length for averaging
BUCKET_STEP = 2 # Step for temperature discretization (bucketing)

# Critical temperature limits for override
CRITICAL_RAD_TEMP = 60
CRITICAL_NVME_TEMP = 75

# --- Argument Parsing and Logging Setup ---
parser = argparse.ArgumentParser(description="Fan monitor with Q-learning control.")
parser.add_argument("--debug", action="store_true", help="Enables debug logging.")
args = parser.parse_args()

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG if args.debug else logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# --- Auxiliary Functions ---
def notify_root(subject, message):
    """Notifies the 'root' user via the system's 'mail' command."""
    try:
        subprocess.run(['mail', '-s', subject, 'root'], input=message.encode(), check=True, timeout=10)
        logging.info(f"Notification sent: '{subject}'")
    except FileNotFoundError:
        logging.error("'mail' command not found. Ensure 'mailutils' package or similar is installed.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to send email (exit code: {e.returncode}): {e.stderr.decode().strip()}")
    except subprocess.TimeoutExpired:
        logging.error("Timeout exceeded when trying to send email.")
    except Exception as e:
        logging.error(f"Unexpected error when trying to send email: {e}")

def bucket(temp):
    """Divides temperature into 'buckets' for state discretization."""
    return int(temp // BUCKET_STEP)

def load_q_table(filename):
    """Loads the Q-table from a pickle file."""
    if os.path.exists(filename):
        try:
            with open(filename, 'rb') as f:
                q_table = pickle.load(f)
            logging.info(f"Q-table loaded from '{filename}'. Size: {len(q_table)} states.")
            return q_table
        except Exception as e:
            logging.error(f"Error loading Q-table from '{filename}': {e}. Starting with empty table.")
            return {}
    else:
        logging.info(f"Q-table file '{filename}' not found. Starting with empty table.")
        return {}

def save_q_table(q_table, filename):
    """Saves the Q-table to a pickle file."""
    try:
        # Ensures the directory exists
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, 'wb') as f:
            pickle.dump(q_table, f)
        logging.info(f"Q-table saved to '{filename}'. Size: {len(q_table)} states.")
    except Exception as e:
        logging.error(f"Error saving Q-table to '{filename}': {e}")

def get_liquidctl_temps(device):
    """
    Connects to the Liquidctl device and extracts radiator temperatures.
    Returns (temp_rad_in, temp_rad_out) or (None, None) on error.
    """
    temp_rad_in, temp_rad_out = None, None
    try:
        with device.connect():
            status = device.get_status()
            logging.debug(f"Device status for {device.description}: {status}")
            for key, value, unit in status:
                logging.debug(f"Parsing: key='{key}', value='{value}', unit='{unit}'") # Extra debug
                
                # If key contains "Temperature" AND unit is "°C"
                if "Temperature" in key and unit == '°C':
                    try:
                        # 'value' is already the numeric float, no regex needed
                        temp_val = float(value) 
                        if "Temperature 0" in key:
                            temp_rad_out = temp_val # Typically Radiator Out
                            logging.debug(f"Detected Temperature 0: {temp_rad_out}°C")
                        elif "Temperature 1" in key:
                            temp_rad_in = temp_val # Typically Radiator In
                            logging.debug(f"Detected Temperature 1: {temp_rad_in}°C")
                    except ValueError as e:
                        logging.warning(f"Failed to convert temperature value '{value}' to float: {e}")
            
            logging.info(f"Radiator IN: {temp_rad_in}°C, OUT: {temp_rad_out}°C")
            return temp_rad_in, temp_rad_out
    except Exception as e:
        logging.error(f"Error accessing liquidctl device ({device.description}): {e}")
        return None, None

def get_nvme_temp():
    """
    Reads the maximum temperature from all detected NVMe devices.
    Returns the maximum temperature or 0.0 if none is found.
    """
    nvme_devices = glob.glob('/dev/nvme*n1')
    logging.info(f"Detected NVMe devices: {[os.path.basename(dev) for dev in nvme_devices]}")
    nvme_temps = []
    
    # Flexible regex to capture temperature
    # Looks for "temperature", followed by anything (non-greedy),
    # then an optional ':', spaces, the number, and an optional unit ('C' or '°C')
    # The `(?:...)` creates a non-capturing group.
    temp_pattern = re.compile(r"(?:temperature|temp|current temp|composite temp|sensor \d+ temp)[\s:]*(\d+\.?\d*)\s*(?:°C|C)?", re.IGNORECASE)

    for dev in nvme_devices:
        try:
            result = subprocess.run(
                ['nvme', 'smart-log', dev],
                capture_output=True,
                text=True,
                check=True, # Raises CalledProcessError if command fails
                timeout=5
            )
            # Iterate line by line to find the temperature
            for line in result.stdout.splitlines():
                match = temp_pattern.search(line)
                if match:
                    nvme_temp = float(match.group(1))
                    if nvme_temp > 0: # Ignore invalid readings (e.g., 0.0)
                        nvme_temps.append(nvme_temp)
                        logging.debug(f"NVMe temperature '{nvme_temp}°C' found on '{dev}' in line: '{line.strip()}'")
                        break # Found temperature, can stop searching for this NVMe
            if not nvme_temps and "temperature" in result.stdout.lower(): # A fallback for debugging
                 logging.warning(f"NVMe temperature not found in output of {dev} despite containing the word 'temperature'. Content: \n{result.stdout}")
            elif not nvme_temps:
                logging.warning(f"NVMe temperature not found in output of {dev}.")
        except FileNotFoundError:
            logging.warning(f"'nvme' command not found. Ensure 'nvme-cli' package is installed.")
        except subprocess.CalledProcessError as e:
            logging.warning(f"Error executing 'nvme smart-log {dev}': {e.stderr.strip()}")
        except subprocess.TimeoutExpired:
            logging.warning(f"Timeout exceeded when reading NVMe from {dev}.")
        except Exception as e:
            logging.warning(f"Unexpected error when reading NVMe from {dev}: {e}")

    return max(nvme_temps) if nvme_temps else 0.0

# --- Initialization ---
# Checks and creates the data CSV file if it doesn't exist
if not os.path.exists(DATA_FILE):
    logging.info(f"Data file '{DATA_FILE}' not found, creating new one.")
    # Ensures the directory exists
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'temp_rad', 'temp_nvme', 'fan_rad', 'fan_chs', 'noise_est', 'reward'])

# Load the Q-table at script start
Q = load_q_table(Q_TABLE_FILE)

# Initial state variables
temp_rad_hist = []
temp_nvme_hist = []
fan_rad_speed = 50
fan_chs_speed = 50

notify_root("Fan Monitor Started", "Q-learning fan monitor is now active.")

# --- Main Loop ---
try:
    while True:
        timestamp = datetime.now().isoformat()

        # 1. Liquidctl Device Discovery
        devices = list(find_liquidctl_devices())
        if not devices:
            logging.warning("No liquidctl devices found. Retrying in 10s.")
            time.sleep(10)
            continue

        target_device = None
        for dev in devices:
            if "Commander Core XT" in dev.description:
                target_device = dev
                break

        if not target_device:
            logging.error("Commander Core XT not found among devices. Retrying in 10s.")
            time.sleep(10)
            continue

        # 2. Temperature Readings
        temp_rad_in, temp_rad_out = get_liquidctl_temps(target_device)
        if temp_rad_in is None: # If radiator reading failed
            time.sleep(10)
            continue

        temp_nvme = get_nvme_temp()

        # 3. Update Temperature History
        temp_rad_hist.append(temp_rad_in)
        temp_nvme_hist.append(temp_nvme)
        # Keep history at TEMP_HISTORY_LENGTH items
        if len(temp_rad_hist) > TEMP_HISTORY_LENGTH:
            temp_rad_hist.pop(0)
            temp_nvme_hist.pop(0)

        temp_rad_avg = np.mean(temp_rad_hist)
        temp_nvme_avg = np.mean(temp_nvme_hist)

        # 4. Q-Learning Logic
        state = (bucket(temp_rad_avg), bucket(temp_nvme_avg))
        action = (fan_rad_speed, fan_chs_speed)

        rad_error = abs(temp_rad_avg - RAD_TARGET_TEMP)
        nvme_error = abs(temp_nvme_avg - NVME_TARGET_TEMP)

        reward = 0
        if rad_error > TEMP_HYSTERESIS or nvme_error > TEMP_HYSTERESIS:
            reward = -(rad_error + nvme_error) # Penalize temperature deviation
        reward -= NOISE_PENALTY_FACTOR * (fan_rad_speed + fan_chs_speed) / 200.0 # Penalize noise (higher speed = more noise)

        # Q-value update
        if state not in Q:
            Q[state] = {}
        if action not in Q[state]:
            Q[state][action] = 0.0
        # Simplified Q-learning update formula: Q(s,a) = Q(s,a) + alpha * (reward - Q(s,a))
        Q[state][action] += ALPHA * (reward - Q[state][action])

        # 5. Fan Speed Adjustment (Based on Simple Heuristic)
        # This adjustment is a rule-based control, not directly from the Q-table
        # Q-learning here mostly evaluates actions rather than choosing them.
        if temp_rad_avg > RAD_TARGET_TEMP + TEMP_HYSTERESIS:
            fan_rad_speed = min(fan_rad_speed + FAN_SPEED_ADJUSTMENT_STEP, RAD_FAN_MAX_SPEED)
        elif temp_rad_avg < RAD_TARGET_TEMP - TEMP_HYSTERESIS:
            fan_rad_speed = max(fan_rad_speed - FAN_SPEED_ADJUSTMENT_STEP, RAD_FAN_MIN_SPEED)

        if temp_nvme_avg > NVME_TARGET_TEMP + TEMP_HYSTERESIS:
            fan_chs_speed = min(fan_chs_speed + FAN_SPEED_ADJUSTMENT_STEP, CHS_FAN_MAX_SPEED)
        elif temp_nvme_avg < NVME_TARGET_TEMP - TEMP_HYSTERESIS:
            fan_chs_speed = max(fan_chs_speed - FAN_SPEED_ADJUSTMENT_STEP, CHS_FAN_MIN_SPEED)

        # 6. Critical Temperature Check and Override
        if temp_rad_in > CRITICAL_RAD_TEMP or temp_nvme > CRITICAL_NVME_TEMP:
            logging.critical(f"🔥 Critical temperature detected! Radiator: {temp_rad_in}°C, NVMe: {temp_nvme}°C. Setting fans to 100%.")
            fan_rad_speed = 100
            fan_chs_speed = 100
            notify_root("🔥 Critical Temperature", f"Radiator or NVMe overheat detected at {timestamp}! Radiator: {temp_rad_in}°C, NVMe: {temp_nvme}°C.")

        # 7. Apply Fan Speeds
        try:
            with target_device.connect():
                # Assuming fan1, fan2, fan3 are for the radiator and fan4, fan5, fan6 are for the chassis
                target_device.set_fixed_speed("fan1", fan_rad_speed)
                target_device.set_fixed_speed("fan2", fan_rad_speed)
                target_device.set_fixed_speed("fan3", fan_rad_speed)
                target_device.set_fixed_speed("fan4", fan_chs_speed)
                target_device.set_fixed_speed("fan5", fan_chs_speed)
                target_device.set_fixed_speed("fan6", fan_chs_speed)
                logging.info(f"Fan speeds adjusted: Radiator {fan_rad_speed}%, Chassis {fan_chs_speed}%.")
        except Exception as e:
            logging.error(f"Failed to set fan speeds: {e}. Retrying in 10s.")
            time.sleep(10) # Longer pause in case of critical fan control error
            continue

        # 8. Logging and Data Storage
        log_msg = (
            f"Radiator IN: {temp_rad_avg:.1f}°C | NVMe MAX: {temp_nvme_avg:.1f}°C | "
            f"Fan R/C: {fan_rad_speed}%/{fan_chs_speed}% | Reward: {reward:.2f}"
        )
        # No longer prints to console by default, logging handles it.
        # print(log_msg) # Uncomment if you want console output

        with open(DATA_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                timestamp, temp_rad_avg, temp_nvme_avg,
                fan_rad_speed, fan_chs_speed,
                (fan_rad_speed + fan_chs_speed) / 2, # Noise estimate
                reward
            ])

        time.sleep(10) # Interval between readings

except KeyboardInterrupt:
    notify_root("Fan Monitor Interrupted", "The fan monitor script was terminated via KeyboardInterrupt.")
    logging.info("Service interrupted by user.")
except Exception as e:
    notify_root("Fan Monitor Crashed", f"Unexpected error: {e}")
    logging.exception("Unhandled exception in main loop.")
finally:
    # Ensures the Q-table is saved under any exit circumstance
    save_q_table(Q, Q_TABLE_FILE)
    logging.info("Script finished.")