import os
import time
import csv
import logging
import smtplib
import numpy as np
import json
from datetime import datetime
from liquidctl import find_liquidctl_devices
import subprocess
import argparse
import glob

LOG_FILE = '/var/log/fan_monitor_qlearning.log'
DATA_FILE = '/var/log/fan_monitor_data.csv'
Q_TABLE_FILE = '/var/log/q_table.json'

# Q-learning parameters
alpha = 0.1  # Learning rate (increased for faster learning)
gamma = 0.9  # Discount factor
epsilon = 0.15  # Exploration rate (epsilon-greedy)
epsilon_decay = 0.995  # Decay rate for epsilon
epsilon_min = 0.05  # Minimum epsilon

# Temperature targets and hysteresis
temp_target = 35.0  # Radiator target (closer to actual temps)
nvme_target = 60.0  # NVMe target
TEMP_HYSTERESIS = 2.0  # Reduced hysteresis for more responsiveness
NVME_HYSTERESIS = 3.0

# Fan speed limits
rad_min, rad_max = 30, 100
chs_min, chs_max = 30, 100
fan_step = 10  # Step size for fan adjustments

# Noise penalty (reduced to allow more aggressive cooling when needed)
noise_penalty = 0.2

parser = argparse.ArgumentParser()
parser.add_argument("--debug", action="store_true", help="Enable debug logging")
parser.add_argument("--reset-qtable", action="store_true", help="Reset Q-table")
args = parser.parse_args()

logging.basicConfig(
    filename=LOG_FILE, 
    level=logging.DEBUG if args.debug else logging.INFO, 
    format='%(asctime)s [%(levelname)s] %(message)s'
)

def notify_root(subject, message):
    try:
        subprocess.run(['mail', '-s', subject, 'root'], input=message.encode(), check=True)
    except Exception as e:
        logging.error(f"Failed to send email: {e}")

def save_q_table(q_table):
    """Save Q-table to disk for persistence"""
    try:
        # Convert tuple keys to strings for JSON serialization
        q_serializable = {}
        for state, actions in q_table.items():
            state_key = f"{state[0]}_{state[1]}"
            q_serializable[state_key] = {}
            for action, value in actions.items():
                action_key = f"{action[0]}_{action[1]}"
                q_serializable[state_key][action_key] = value
        
        with open(Q_TABLE_FILE, 'w') as f:
            json.dump(q_serializable, f, indent=2)
        logging.debug(f"Q-table saved with {len(q_table)} states")
    except Exception as e:
        logging.error(f"Failed to save Q-table: {e}")

def load_q_table():
    """Load Q-table from disk"""
    if not os.path.exists(Q_TABLE_FILE) or args.reset_qtable:
        logging.info("Initializing new Q-table")
        return {}
    
    try:
        with open(Q_TABLE_FILE, 'r') as f:
            q_serializable = json.load(f)
        
        # Convert string keys back to tuples
        q_table = {}
        for state_key, actions in q_serializable.items():
            state_parts = state_key.split('_')
            state = (int(state_parts[0]), int(state_parts[1]))
            q_table[state] = {}
            for action_key, value in actions.items():
                action_parts = action_key.split('_')
                action = (int(action_parts[0]), int(action_parts[1]))
                q_table[state][action] = value
        
        logging.info(f"Q-table loaded with {len(q_table)} states")
        return q_table
    except Exception as e:
        logging.error(f"Failed to load Q-table: {e}")
        return {}

def bucket(temp, step=3):
    """Bucket temperatures for state representation"""
    return int(temp // step)

def get_possible_actions():
    """Generate all possible fan speed combinations"""
    actions = []
    for rad_speed in range(rad_min, rad_max + 1, fan_step):
        for chs_speed in range(chs_min, chs_max + 1, fan_step):
            actions.append((rad_speed, chs_speed))
    return actions

def choose_action(state, q_table, epsilon_current):
    """Epsilon-greedy action selection"""
    if state not in q_table or np.random.random() < epsilon_current:
        # Exploration: random action
        possible_actions = get_possible_actions()
        action = possible_actions[np.random.randint(len(possible_actions))]
        logging.debug(f"Exploration: chose random action {action}")
        return action
    
    # Exploitation: best known action
    best_action = max(q_table[state], key=q_table[state].get)
    logging.debug(f"Exploitation: chose best action {best_action}")
    return best_action

def calculate_reward(temp_rad, temp_nvme, fan_rad, fan_chs):
    """Optimized reward function for current excellent temperature ranges"""
    reward = 0
    
    # Radiator temperature reward/penalty (much more generous)
    rad_error = abs(temp_rad - temp_target)
    if rad_error <= TEMP_HYSTERESIS:
        # Perfect zone
        reward += 30 - rad_error * 1  
    elif rad_error <= 6:  # Excellent zone (covers current 30.3°C vs 35°C)
        reward += 20 - rad_error * 0.5  # Still very positive
    elif rad_error <= 10:
        # Good zone
        reward += 10 - rad_error * 1
    else:
        # Too far from target
        reward -= rad_error * 2
    
    # NVMe temperature reward/penalty (much more generous)
    nvme_error = abs(temp_nvme - nvme_target)
    if nvme_error <= NVME_HYSTERESIS:
        # Perfect zone
        reward += 25 - nvme_error * 1
    elif nvme_error <= 10:  # Excellent zone (covers current 52°C vs 60°C)
        reward += 18 - nvme_error * 0.3  # Still very positive
    elif nvme_error <= 15:
        # Good zone
        reward += 8 - nvme_error * 0.8
    else:
        # Too far from target
        reward -= nvme_error * 1.5
    
    # Minimal noise penalty
    noise_factor = (fan_rad + fan_chs) / 200.0
    reward -= noise_factor * 3  # Very low noise penalty
    
    # Big efficiency bonus when temps are great
    if rad_error <= 6 and nvme_error <= 10:
        # Both temps excellent, big efficiency reward
        efficiency_bonus = (200 - fan_rad - fan_chs) / 200.0 * 12
        reward += efficiency_bonus
        
        # Extra bonus for being below targets (like current situation)
        if temp_rad <= temp_target and temp_nvme <= nvme_target:
            cool_bonus = 8
            reward += cool_bonus
    
    return reward

# Initialize data file if it doesn't exist
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'temp_rad', 'temp_nvme', 'fan_rad', 'fan_chs', 
                        'noise_est', 'reward', 'epsilon', 'q_states'])

# Load Q-table
Q = load_q_table()

# Initialize variables
temp_rad_hist = []
temp_nvme_hist = []
fan_rad_speed = 50
fan_chs_speed = 50
epsilon_current = epsilon
save_counter = 0

notify_root("Fan Monitor Started", "Improved Q-learning fan monitor is now active.")
logging.info(f"Starting with epsilon={epsilon}, targets: RAD={temp_target}°C, NVMe={nvme_target}°C")

try:
    while True:
        timestamp = datetime.now().isoformat()
        save_counter += 1

        # Find and connect to liquidctl device
        devices = list(find_liquidctl_devices())
        logging.debug(f"Found {len(devices)} liquidctl devices.")
        if not devices:
            logging.warning("No liquidctl devices found.")
            time.sleep(10)
            continue

        target_device = None
        for dev in devices:
            if "Commander Core XT" in dev.description:
                target_device = dev
                break

        if not target_device:
            logging.error("Commander Core XT not found among devices.")
            time.sleep(10)
            continue

        # Read radiator temperatures
        temp_rad_in = None
        temp_rad_out = None

        try:
            with target_device.connect():
                status = target_device.get_status()
                logging.debug(f"Connected to device: {target_device.description}")
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
                logging.debug(f"Radiator IN: {temp_rad_in}°C, OUT: {temp_rad_out}°C")
        except Exception as e:
            logging.error(f"Error accessing liquidctl device: {e}")
            time.sleep(10)
            continue

        # Read NVMe temperatures
        nvme_devices = glob.glob('/dev/nvme*n1')
        logging.debug(f"Detected NVMe devices: {[os.path.basename(dev) for dev in nvme_devices]}")
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

        # Update temperature history
        temp_rad_hist.append(temp_rad_in)
        temp_nvme_hist.append(temp_nvme)
        if len(temp_rad_hist) > 5:  # Reduced history for faster response
            temp_rad_hist.pop(0)
            temp_nvme_hist.pop(0)

        temp_rad_avg = np.mean(temp_rad_hist)
        temp_nvme_avg = np.mean(temp_nvme_hist)

        # Define current state
        current_state = (bucket(temp_rad_avg), bucket(temp_nvme_avg))
        
        # Emergency override for critical temperatures
        if temp_rad_in > 65 or temp_nvme > 80:
            fan_rad_speed = 100
            fan_chs_speed = 100
            notify_root("🔥 Critical Temperature", 
                       f"Emergency cooling activated! RAD: {temp_rad_avg:.1f}°C, NVMe: {temp_nvme_avg:.1f}°C at {timestamp}")
            logging.warning("Emergency cooling activated!")
        else:
            # Q-learning action selection
            action = choose_action(current_state, Q, epsilon_current)
            fan_rad_speed, fan_chs_speed = action

        # Calculate reward for the previous state-action pair
        reward = calculate_reward(temp_rad_avg, temp_nvme_avg, fan_rad_speed, fan_chs_speed)

        # Update Q-table
        if current_state not in Q:
            Q[current_state] = {}
        current_action = (fan_rad_speed, fan_chs_speed)
        if current_action not in Q[current_state]:
            Q[current_state][current_action] = 0.0

        # Q-learning update rule
        max_future_q = 0
        if current_state in Q and Q[current_state]:
            max_future_q = max(Q[current_state].values())
        
        Q[current_state][current_action] += alpha * (reward + gamma * max_future_q - Q[current_state][current_action])

        # Apply fan speeds
        try:
            with target_device.connect():
                # Radiator cooling fans (1, 2, 3)
                target_device.set_fixed_speed("fan1", fan_rad_speed)
                target_device.set_fixed_speed("fan2", fan_rad_speed)
                target_device.set_fixed_speed("fan3", fan_rad_speed)
                # NVMe cooling fans (4, 5, 6)
                target_device.set_fixed_speed("fan4", fan_chs_speed)
                target_device.set_fixed_speed("fan5", fan_chs_speed)
                target_device.set_fixed_speed("fan6", fan_chs_speed)
        except Exception as e:
            logging.error(f"Failed to set fan speeds: {e}")
            time.sleep(10)
            continue

        # Decay epsilon
        epsilon_current = max(epsilon_min, epsilon_current * epsilon_decay)

        # Logging
        log_msg = (f"RAD: {temp_rad_avg:.1f}°C | NVMe: {temp_nvme_avg:.1f}°C | "
                  f"Fan R/C: {fan_rad_speed}%/{fan_chs_speed}% | Reward: {reward:.2f} | "
                  f"ε: {epsilon_current:.3f} | Q-states: {len(Q)}")
        logging.info(log_msg)
        print(log_msg)

        # Save data to CSV
        with open(DATA_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, temp_rad_avg, temp_nvme_avg, fan_rad_speed, 
                           fan_chs_speed, (fan_rad_speed+fan_chs_speed)/2, reward, 
                           epsilon_current, len(Q)])

        # Save Q-table periodically
        if save_counter % 30 == 0:  # Save every 5 minutes
            save_q_table(Q)
            logging.debug("Q-table saved to disk")

        time.sleep(10)

except KeyboardInterrupt:
    save_q_table(Q)
    notify_root("Fan Monitor Stopped", "Fan monitor script exited via KeyboardInterrupt.")
    logging.info("Service interrupted by user. Q-table saved.")

except Exception as e:
    save_q_table(Q)
    notify_root("Fan Monitor Crashed", f"Unexpected error: {e}")
    logging.exception("Unhandled exception. Q-table saved.")