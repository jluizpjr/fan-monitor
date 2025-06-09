Q-Learning Fan Monitor for Corsair Commander Core XT
This project provides a systemd service to intelligently monitor and control fan speeds in a PC, specifically designed for systems using a Corsair Commander Core XT for fan control and NVMe drives for storage. It leverages Q-learning principles to evaluate the effectiveness of fan speed adjustments based on radiator and NVMe temperatures, aiming for an optimal balance between cooling performance and noise levels.

Table of Contents
Features
Prerequisites
Installation
Manual Installation
Using the install.sh script
Configuration
How it Works (Q-Learning)
Usage
Logging and Data
Troubleshooting
Future Improvements
Contributing
License
Features
Temperature Monitoring: Continuously monitors radiator (via Corsair Commander Core XT) and NVMe drive temperatures.
Dynamic Fan Speed Control: Adjusts fan speeds (radiator and chassis) based on temperature readings.
Q-Learning Integration: Evaluates the reward of fan speed actions based on a custom reward function (temperature deviation and estimated noise).
Persistent Q-Table: Saves the learned Q-values to a file, allowing the system to retain its "learning" across reboots.
Critical Temperature Override: Automatically sets fans to 100% in case of critical temperature thresholds for immediate cooling.
Systemd Service: Runs as a background service, starting automatically on boot.
Root Notifications: Sends email notifications to the root user for service start/stop and critical temperature events.
CSV Data Logging: Records temperature, fan speed, and reward data to a CSV file for analysis.
Prerequisites
Hardware
Corsair Commander Core XT: Required for radiator fan control.
NVMe Drives: The script queries NVMe drive temperatures.
Software
Linux Operating System: Tested on Debian-based systems.
Python 3: The script is written in Python 3.
liquidctl: Python library for controlling liquid cooling devices.
bash
Copiar

sudo pip3 install liquidctl
numpy: Python library for numerical operations.
bash
Copiar

sudo pip3 install numpy
nvme-cli: Command-line tool for NVMe management.
bash
Copiar

# For Debian/Ubuntu
sudo apt install nvme-cli
# For Fedora
sudo dnf install nvme-cli
# For Arch Linux
sudo pacman -S nvme-cli
mailutils: For sending email notifications to root.
bash
Copiar

# For Debian/Ubuntu
sudo apt install mailutils
# For Fedora
sudo dnf install mailx # (mailx is often the package name for mail command)
# For Arch Linux
sudo pacman -S mailutils
systemd: Init system for managing the service (standard on most modern Linux distros).
Installation
Manual Installation
Clone the repository:
bash
Copiar

git clone https://github.com/your-username/your-repo-name.git # Replace with your repo details
cd your-repo-name
Install Python dependencies:
bash
Copiar

sudo pip3 install liquidctl numpy
Install system utilities:
bash
Copiar

# Example for Debian/Ubuntu
sudo apt update
sudo apt install nvme-cli mailutils
Copy the main script:
bash
Copiar

sudo cp fan_monitor_qlearning.py /usr/local/bin/
sudo chmod +x /usr/local/bin/fan_monitor_qlearning.py
Copy the systemd service file:
bash
Copiar

sudo cp fan_monitor_qlearning.service /etc/systemd/system/
Reload systemd, enable, and start the service:
bash
Copiar

sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable fan_monitor_qlearning.service
sudo systemctl start fan_monitor_qlearning.service
Verify the service status:
bash
Copiar

sudo systemctl status fan_monitor_qlearning.service
Using the install.sh script
The repository includes a convenience script install.sh to automate the installation steps.

Clone the repository:
bash
Copiar

git clone https://github.com/your-username/your-repo-name.git # Replace with your repo details
cd your-repo-name
Ensure necessary system utilities are installed (as mentioned in prerequisites):
bash
Copiar

# Example for Debian/Ubuntu
sudo apt update
sudo apt install nvme-cli mailutils
Run the installation script:
bash
Copiar

sudo bash install.sh
This script will:
Stop and disable any existing fan_monitor_qlearning.service.
Copy fan_monitor_qlearning.py to /usr/local/bin/ and make it executable.
Copy fan_monitor_qlearning.service to /etc/systemd/system/.
Reload systemd configurations.
Enable and start the fan_monitor_qlearning.service.
Configuration
The main configuration parameters are located at the beginning of the fan_monitor_qlearning.py script under the --- Configuration Constants --- section. You can adjust these values to suit your specific hardware and preferences.

python
Copiar

# --- Configuration Constants ---
LOG_FILE = '/var/log/fan_monitor_qlearning.log'
DATA_FILE = '/var/log/fan_monitor_data.csv'
Q_TABLE_FILE = '/var/lib/fan_monitor_q_table.pkl' # File to save/load the Q-table

# Q-learning and control parameters
ALPHA = 0.05
GAMMA = 0.9 # Not used in current implementation, but good to keep for future expansions
RAD_TARGET_TEMP = 40.0 # Desired radiator temperature in Celsius
NVME_TARGET_TEMP = 60.0 # Desired NVMe temperature in Celsius
NOISE_PENALTY_FACTOR = 0.3 # Factor to penalize higher fan speeds (noise)
TEMP_HYSTERESIS = 3.0 # Temperature dead zone before fan speed adjustment
RAD_FAN_MIN_SPEED = 30 # Minimum radiator fan speed percentage
RAD_FAN_MAX_SPEED = 100 # Maximum radiator fan speed percentage
CHS_FAN_MIN_SPEED = 30 # Minimum chassis fan speed percentage
CHS_FAN_MAX_SPEED = 100 # Maximum chassis fan speed percentage
FAN_SPEED_ADJUSTMENT_STEP = 5 # Increment/decrement step for fan speed adjustment
TEMP_HISTORY_LENGTH = 6 # Number of past readings to average for stable temperature
BUCKET_STEP = 2 # Step for discretizing temperature into buckets for Q-table states

# Critical temperature limits for override
CRITICAL_RAD_TEMP = 60 # Radiator temperature above which fans go to 100%
CRITICAL_NVME_TEMP = 75 # NVMe temperature above which fans go to 100%
Important: After modifying fan_monitor_qlearning.py, you must copy it again and restart the service:

bash
Copiar

sudo cp fan_monitor_qlearning.py /usr/local/bin/
sudo systemctl restart fan_monitor_qlearning.service
How it Works (Q-Learning)
This project implements a simplified form of Q-learning to aid in fan control:

States: The system defines a "state" based on the bucketed average radiator and NVMe temperatures (e.g., (RadiatorTempBucket, NVMeTempBucket)).
Actions: The "action" taken by the system is the combination of the current radiator fan speed and chassis fan speed (e.g., (RadFanSpeed, ChsFanSpeed)).
Reward Function: After an action is taken and new temperatures are read, a "reward" is calculated.
Positive Reward (Implicit): No explicit positive reward is given.
Negative Reward (Penalties):
Temperature Deviation: A penalty is applied if current temperatures deviate significantly from RAD_TARGET_TEMP or NVME_TARGET_TEMP (outside TEMP_HYSTERESIS). The larger the deviation, the higher the penalty.
Noise Penalty: A penalty is applied based on the fan speeds (representing noise), scaled by NOISE_PENALTY_FACTOR. Higher fan speeds incur a greater penalty.
Q-Value Update: The system updates the Q-value for the (state, action) pair using a simplified Q-learning update rule: Q(s,a) = Q(s,a) + ALPHA * (reward - Q(s,a)). This essentially makes the Q-value for a given state-action pair reflect the long-term desirability of that action in that state.
Action Selection: Crucially, this implementation currently uses a rule-based heuristic for fan speed adjustment, not directly selecting actions based on the Q-table. The Q-learning component is primarily used to evaluate the rewards of the chosen heuristic actions, building up a knowledge base over time. This can be seen as a form of "learning to evaluate" rather than "learning to act" in a fully autonomous reinforcement learning sense.
Usage
Check Service Status:
bash
Copiar

sudo systemctl status fan_monitor_qlearning.service
Start the Service:
bash
Copiar

sudo systemctl start fan_monitor_qlearning.service
Stop the Service:
bash
Copiar

sudo systemctl stop fan_monitor_qlearning.service
Restart the Service:
bash
Copiar

sudo systemctl restart fan_monitor_qlearning.service
Disable Autostart on Boot:
bash
Copiar

sudo systemctl disable fan_monitor_qlearning.service
Re-enable Autostart on Boot:
bash
Copiar

sudo systemctl enable fan_monitor_qlearning.service
Logging and Data
Log File: All operational messages, warnings, and errors are logged to:
/var/log/fan_monitor_qlearning.log
You can view it using tail -f /var/log/fan_monitor_qlearning.log. To enable debug logging, start the service with --debug:
bash
Copiar

sudo cp fan_monitor_qlearning.py /usr/local/bin/fan_monitor_qlearning.py # Make sure script is up-to-date
sudo systemctl stop fan_monitor_qlearning.service
# Temporarily modify the service file to add --debug (or use the argparse option directly if running manually)
# Edit /etc/systemd/system/fan_monitor_qlearning.service
# Change: ExecStart=/usr/bin/python3 /usr/local/bin/fan_monitor_qlearning.py
# To:     ExecStart=/usr/bin/python3 /usr/local/bin/fan_monitor_qlearning.py --debug
# Then:
sudo systemctl daemon-reload
sudo systemctl start fan_monitor_qlearning.service
Data File: Historical sensor readings, fan speeds, and rewards are saved in CSV format to:
/var/log/fan_monitor_data.csv
This file can be opened with spreadsheet software for analysis.
Q-Table File: The learned Q-values are persisted in a binary file:
/var/lib/fan_monitor_q_table.pkl
This file should not be manually edited.
Troubleshooting
"No liquidctl devices found" or "Commander Core XT not found":
Ensure your Commander Core XT is properly connected to a USB header.
Run sudo liquidctl status to confirm liquidctl can detect and communicate with your device. If sudo liquidctl status doesn't work, follow liquidctl's troubleshooting guide for your OS.
"NVMe temperature not found":
Run sudo nvme smart-log /dev/nvme0n1 (replace /dev/nvme0n1 with your actual NVMe device path) and inspect the output. The script uses a regular expression to parse the temperature. If the output format differs, the regex in get_nvme_temp() might need adjustment.
"mail command not found" or email errors:
Ensure mailutils (or mailx on some systems) is installed.
Check your system's mail configuration (/etc/ssmtp/ssmtp.conf or similar) if mail isn't being delivered.
Permission Denied Errors:
Ensure the script is being run as root (which it is, via the systemd service configuration).
Check permissions for /var/log/ and /var/lib/ directories. The script needs write access.
Verify liquidctl udev rules are correctly set up (usually handled by liquidctl installation).
Service not starting:
Check sudo journalctl -u fan_monitor_qlearning.service for detailed startup errors.
Future Improvements
True Q-Learning Action Selection: Implement an epsilon-greedy policy or similar to allow the Q-learning algorithm to choose fan speeds based on the learned Q-values, rather than just evaluating heuristic actions.
More Sophisticated Reward Function: Incorporate other factors like historical temperature stability, specific noise profiles, or power consumption into the reward.
Web UI/API: Develop a simple web interface or API for real-time monitoring and configuration adjustments.
Multiple Device Support: Extend support for multiple liquidctl devices or different types of fan controllers.
Adaptive Bucketing: Dynamically adjust temperature bucket sizes based on the range of observed temperatures.
Configuration File: Move configuration constants to a separate config.ini or YAML file for easier management without editing the Python script directly.
Better Error Handling: More specific error handling for liquidctl communications (e.g., retry logic for temporary disconnections).
Contributing
Contributions are welcome! If you have suggestions, bug reports, or want to contribute code, please open an issue or submit a pull request.

License
This project is licensed under the MIT License - see the LICENSE file for details.
