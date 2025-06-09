import os
import time
import csv
import logging
import json
import subprocess
import argparse
import glob
from datetime import datetime
from typing import Dict, Tuple, List, Optional, Any

import numpy as np
from liquidctl import find_liquidctl_devices

# --- Constants ---
LOG_FILE = '/var/log/fan_monitor_qlearning.log'
DATA_FILE = '/var/log/fan_monitor_data.csv'
Q_TABLE_FILE = '/var/log/q_table.json'
CONFIG_FILE = '/etc/fan_monitor.conf'

def setup_logging(debug: bool):
    """Configures the logging for the application."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        filename=LOG_FILE,
        level=level,
        format='%(asctime)s [%(levelname)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    # Also log to console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] - %(message)s')
    console_handler.setFormatter(formatter)
    logging.getLogger().addHandler(console_handler)

def notify_root(subject: str, message: str):
    """Sends a notification email to the root user."""
    try:
        subprocess.run(
            ['mail', '-s', subject, 'root'],
            input=message.encode(),
            check=True,
            capture_output=True
        )
        logging.info(f"Sent notification to root: '{subject}'")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logging.error(f"Failed to send email to root: {e}")

class QTableManager:
    """Handles loading and saving the Q-table."""

    def __init__(self, file_path: str):
        self.file_path = file_path

    @staticmethod
    def _key_to_str(key: Tuple[int, ...]) -> str:
        """Converts a tuple key to a string."""
        return '_'.join(map(str, key))

    @staticmethod
    def _str_to_key(key_str: str) -> Tuple[int, ...]:
        """Converts a string key back to a tuple of integers."""
        return tuple(map(int, key_str.split('_')))

    def save(self, q_table: Dict[Tuple[int, int], Dict[Tuple[int, int], float]]):
        """Saves the Q-table to a JSON file."""
        try:
            q_serializable = {
                self._key_to_str(state): {
                    self._key_to_str(action): value
                    for action, value in actions.items()
                }
                for state, actions in q_table.items()
            }
            with open(self.file_path, 'w') as f:
                json.dump(q_serializable, f, indent=2)
            logging.debug(f"Q-table with {len(q_table)} states saved successfully.")
        except IOError as e:
            logging.error(f"Failed to write Q-table to {self.file_path}: {e}")
        except Exception as e:
            logging.error(f"An unexpected error occurred while saving the Q-table: {e}")

    def load(self, reset: bool = False) -> Dict[Tuple[int, int], Dict[Tuple[int, int], float]]:
        """Loads the Q-table from a JSON file."""
        if reset or not os.path.exists(self.file_path):
            logging.info("Initializing a new Q-table." if not reset else "Resetting Q-table as requested.")
            return {}
        try:
            with open(self.file_path, 'r') as f:
                q_serializable = json.load(f)

            q_table = {
                self._str_to_key(state_str): {
                    self._str_to_key(action_str): value
                    for action_str, value in actions.items()
                }
                for state_str, actions in q_serializable.items()
            }
            logging.info(f"Q-table with {len(q_table)} states loaded successfully.")
            return q_table
        except (IOError, json.JSONDecodeError) as e:
            logging.error(f"Failed to load or parse Q-table from {self.file_path}: {e}. Starting with an empty table.")
            return {}
        except Exception as e:
            logging.error(f"An unexpected error occurred while loading the Q-table: {e}. Starting with an empty table.")
            return {}


class FanController:
    """
    Manages system fan speeds using a Q-learning algorithm to optimize temperatures.
    """

    def __init__(self, config: Dict[str, Any], reset_q_table: bool = False):
        self.config = config
        self.q_table_manager = QTableManager(Q_TABLE_FILE)
        self.q_table = self.q_table_manager.load(reset=reset_q_table)
        self.epsilon = self.config['q_learning']['epsilon_start']
        self.possible_actions = self._generate_possible_actions()
        self.temp_rad_hist: List[float] = []
        self.temp_nvme_hist: List[float] = []
        self._initialize_data_file()

    def _initialize_data_file(self):
        """Creates the data log file with headers if it doesn't exist."""
        if not os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        'timestamp', 'temp_rad_avg', 'temp_nvme_avg',
                        'fan_rad_speed', 'fan_chs_speed', 'reward',
                        'epsilon', 'q_states_count'
                    ])
            except IOError as e:
                logging.error(f"Failed to initialize data file {DATA_FILE}: {e}")

    def _generate_possible_actions(self) -> List[Tuple[int, int]]:
        """Generates all possible fan speed combinations based on config."""
        fan_cfg = self.config['fans']
        rad_speeds = range(fan_cfg['rad_min'], fan_cfg['rad_max'] + 1, fan_cfg['step'])
        chs_speeds = range(fan_cfg['chs_min'], fan_cfg['chs_max'] + 1, fan_cfg['step'])
        return [(rad, chs) for rad in rad_speeds for chs in chs_speeds]

    def _get_device(self) -> Optional[Any]:
        """Finds and returns the target liquidctl device."""
        try:
            devices = list(find_liquidctl_devices())
            if not devices:
                logging.warning("No liquidctl devices found.")
                return None
            
            device_name = self.config['liquidctl']['device_name']
            for dev in devices:
                if device_name in dev.description:
                    logging.debug(f"Found target device: {dev.description}")
                    return dev
            
            logging.error(f"Target device '{device_name}' not found.")
            return None
        except Exception as e:
            logging.error(f"Error finding liquidctl devices: {e}")
            return None

    def get_temperatures(self, device: Any) -> Tuple[Optional[float], Optional[float]]:
        """Reads temperatures from the radiator and NVMe drives."""
        # Radiator temperature
        temp_rad = None
        try:
            with device.connect():
                status = device.get_status()
                for key, value, _ in status:
                    if self.config['liquidctl']['temp_sensor_key'] in key:
                        temp_rad = float(str(value).replace("°C", "").strip())
                        break
            if temp_rad is None:
                 logging.warning("Could not read radiator temperature sensor.")
        except Exception as e:
            logging.error(f"Error reading radiator temperature: {e}")

        # NVMe temperature
        temp_nvme = None
        try:
            nvme_devices = glob.glob('/dev/nvme*n1')
            nvme_temps = []
            for dev_path in nvme_devices:
                result = subprocess.run(
                    ['nvme', 'smart-log', dev_path],
                    capture_output=True, text=True, check=True
                )
                for line in result.stdout.splitlines():
                    if "temperature" in line.lower() and "sensor" not in line.lower():
                        # FIX: Make parsing more robust to handle formats like "27°C"
                        parts = line.split(":")
                        if len(parts) > 1:
                            temp_str = parts[1].replace("°C", "").strip()
                            nvme_temps.append(float(temp_str))
            if nvme_temps:
                temp_nvme = max(nvme_temps)
            else:
                logging.warning("No NVMe temperatures found.")
        except (subprocess.CalledProcessError, FileNotFoundError, IndexError, ValueError) as e:
            logging.error(f"Error reading NVMe temperature: {e}")

        return temp_rad, temp_nvme

    def _bucket_temp(self, temp: float) -> int:
        """Converts a temperature into a discrete state bucket."""
        return int(temp // self.config['state_bucketing']['step'])

    def choose_action(self, state: Tuple[int, int]) -> Tuple[int, int]:
        """Chooses an action using an epsilon-greedy policy."""
        if state not in self.q_table or np.random.random() < self.epsilon:
            # Exploration
            action = self.possible_actions[np.random.randint(len(self.possible_actions))]
            logging.debug(f"Exploring: chose random action {action}")
            return action
        else:
            # Exploitation
            best_action = max(self.q_table[state], key=self.q_table[state].get)
            logging.debug(f"Exploiting: chose best action {best_action} for state {state}")
            return best_action

    def calculate_reward(self, temp_rad: float, temp_nvme: float, fan_rad: int, fan_chs: int) -> float:
        """
        Calculates a reward that incentivizes maintaining target temps with minimal fan speed.
        """
        reward = 0.0
        targets = self.config['targets']
        hysteresis = self.config['hysteresis']
        
        # --- Temperature Reward ---
        # Goal: Be as close to the target as possible.
        rad_error = abs(temp_rad - targets['temp_rad'])
        nvme_error = abs(temp_nvme - targets['nvme'])

        # Strong reward for being in the "sweet spot" (within hysteresis)
        if rad_error <= hysteresis['temp']:
            reward += 25
        else:
            # Penalize deviation exponentially to discourage being far off
            reward -= (rad_error ** 1.5) 

        if nvme_error <= hysteresis['nvme']:
            reward += 15
        else:
            reward -= (nvme_error ** 1.2)

        # --- Efficiency Score ---
        # Goal: Use the least amount of fan speed to achieve the target temperature.
        # This bonus is highest when temps are perfect and fans are low.
        total_fan_speed = fan_rad + fan_chs
        efficiency_bonus = 0
        
        # Only grant an efficiency bonus if temperatures are under control
        if temp_rad < targets['temp_rad'] + hysteresis['temp'] and temp_nvme < targets['nvme'] + hysteresis['nvme']:
            # Max bonus is 20, scaled by how low the fans are.
            efficiency_bonus = (200 - total_fan_speed) / 200.0 * 20.0
            reward += efficiency_bonus
        
        # --- Noise/Power Penalty ---
        # Goal: Discourage high fan speeds regardless of temperature.
        # This acts as a constant downward pressure on fan speeds.
        noise_penalty = (total_fan_speed / 200.0) * self.config['q_learning']['noise_penalty']
        reward -= noise_penalty
        
        return reward


    def update_q_table(self, state: Tuple, action: Tuple, reward: float, next_state: Tuple):
        """Updates the Q-table based on the Bellman equation."""
        q_cfg = self.config['q_learning']
        old_value = self.q_table.get(state, {}).get(action, 0.0)

        next_max = 0.0
        if next_state in self.q_table and self.q_table[next_state]:
            next_max = max(self.q_table[next_state].values())

        new_value = old_value + q_cfg['alpha'] * (reward + q_cfg['gamma'] * next_max - old_value)
        
        if state not in self.q_table:
            self.q_table[state] = {}
        self.q_table[state][action] = new_value

    def set_fan_speeds(self, device: Any, rad_speed: int, chs_speed: int):
        """Applies the chosen fan speeds to the hardware."""
        try:
            with device.connect():
                for i in self.config['liquidctl']['rad_fan_ids']:
                    device.set_fixed_speed(f"fan{i}", rad_speed)
                for i in self.config['liquidctl']['chs_fan_ids']:
                    device.set_fixed_speed(f"fan{i}", chs_speed)
            logging.debug(f"Set fan speeds: Radiator={rad_speed}%, Chassis={chs_speed}%")
        except Exception as e:
            logging.error(f"Failed to set fan speeds: {e}")

    def log_data(self, rad_avg: float, nvme_avg: float, rad_speed: int, chs_speed: int, reward: float):
        """Logs the current cycle's data to a CSV file."""
        try:
            with open(DATA_FILE, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().isoformat(),
                    f"{rad_avg:.2f}",
                    f"{nvme_avg:.2f}",
                    rad_speed,
                    chs_speed,
                    f"{reward:.2f}",
                    f"{self.epsilon:.4f}",
                    len(self.q_table)
                ])
        except IOError as e:
            logging.error(f"Failed to write to data file {DATA_FILE}: {e}")

    def run(self):
        """The main control loop for the fan controller."""
        notify_root("Fan Monitor Started", "Q-learning fan monitor is now active.")
        logging.info(f"Starting fan controller with targets: RAD={self.config['targets']['temp_rad']}°C, NVMe={self.config['targets']['nvme']}°C")

        save_counter = 0
        while True:
            device = self._get_device()
            if not device:
                time.sleep(self.config['main_loop']['interval_seconds'])
                continue
                
            temp_rad, temp_nvme = self.get_temperatures(device)

            if temp_rad is None or temp_nvme is None:
                logging.warning("Incomplete temperature data. Skipping cycle.")
                time.sleep(self.config['main_loop']['interval_seconds'])
                continue

            # Update history and calculate moving average
            history_len = self.config['state_bucketing']['history_length']
            self.temp_rad_hist.append(temp_rad)
            self.temp_nvme_hist.append(temp_nvme)
            if len(self.temp_rad_hist) > history_len:
                self.temp_rad_hist.pop(0)
                self.temp_nvme_hist.pop(0)
            
            rad_avg = np.mean(self.temp_rad_hist)
            nvme_avg = np.mean(self.temp_nvme_hist)

            # Define state and choose action
            current_state = (self._bucket_temp(rad_avg), self._bucket_temp(nvme_avg))
            
            # Emergency override
            emergency_cfg = self.config['emergency_override']
            if rad_avg > emergency_cfg['rad_temp'] or nvme_avg > emergency_cfg['nvme_temp']:
                action = (100, 100)
                notify_root("🔥 Critical Temperature Alert", f"Emergency cooling activated! RAD: {rad_avg:.1f}°C, NVMe: {nvme_avg:.1f}°C")
                logging.warning(f"Emergency override activated at RAD={rad_avg:.1f}, NVME={nvme_avg:.1f}")
            else:
                action = self.choose_action(current_state)

            rad_speed, chs_speed = action
            self.set_fan_speeds(device, rad_speed, chs_speed)

            # Calculate reward and update Q-table
            reward = self.calculate_reward(rad_avg, nvme_avg, rad_speed, chs_speed)
            self.update_q_table(current_state, action, reward, current_state) # next_state is current_state for simplicity

            # Decay epsilon
            q_cfg = self.config['q_learning']
            self.epsilon = max(q_cfg['epsilon_min'], self.epsilon * q_cfg['epsilon_decay'])

            # Logging and saving
            log_msg = (
                f"State: {current_state}, Temps: RAD={rad_avg:.1f}°C, NVMe={nvme_avg:.1f}°C | "
                f"Action: R/C={rad_speed}/{chs_speed} | Reward: {reward:.2f} | "
                f"Epsilon: {self.epsilon:.3f} | Q-States: {len(self.q_table)}"
            )
            logging.info(log_msg)
            self.log_data(rad_avg, nvme_avg, rad_speed, chs_speed, reward)

            save_counter += 1
            if save_counter >= self.config['main_loop']['save_q_table_interval_cycles']:
                self.q_table_manager.save(self.q_table)
                save_counter = 0

            time.sleep(self.config['main_loop']['interval_seconds'])

def main():
    """Main function to parse arguments and run the controller."""
    parser = argparse.ArgumentParser(description="Q-Learning Fan Speed Monitor")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    parser.add_argument("--reset-qtable", action="store_true", help="Reset the Q-table on start.")
    args = parser.parse_args()

    setup_logging(args.debug)

    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.critical(f"Error loading {CONFIG_FILE}: {e}. Please ensure it exists and is valid.")
        return

    try:
        controller = FanController(config, args.reset_qtable)
        controller.run()
    except KeyboardInterrupt:
        logging.info("Service interrupted by user. Shutting down.")
        if 'controller' in locals():
            controller.q_table_manager.save(controller.q_table)
            notify_root("Fan Monitor Stopped", "Fan monitor script was stopped manually.")
    except Exception as e:
        logging.critical("An unhandled exception occurred.", exc_info=True)
        if 'controller' in locals():
            controller.q_table_manager.save(controller.q_table)
        notify_root("Fan Monitor Crashed", f"The fan monitor script crashed due to an error: {e}")

if __name__ == "__main__":
    main()
