# Q-Learning Fan Monitor for Corsair Commander Core XT

This project provides a systemd service to intelligently monitor and control fan speeds in a PC, specifically designed for systems using a Corsair Commander Core XT for fan control and NVMe drives for storage. It leverages Q-learning principles to evaluate the effectiveness of fan speed adjustments based on radiator and NVMe temperatures, aiming for an optimal balance between cooling performance and noise levels.

## Table of Contents

*   [Features](#features)
*   [Prerequisites](#prerequisites)
*   [Installation](#installation)
    *   [Manual Installation](#manual-installation)
    *   [Using the `install.sh` script](#using-the-installsh-script)
*   [Configuration](#configuration)
*   [How it Works (Q-Learning)](#how-it-works-q-learning)
*   [Usage](#usage)
*   [Logging and Data](#logging-and-data)
*   [Troubleshooting](#troubleshooting)
*   [Future Improvements](#future-improvements)
*   [Contributing](#contributing)
*   [License](#license)

## Features

*   **Temperature Monitoring:** Continuously monitors radiator (via Corsair Commander Core XT) and NVMe drive temperatures.
*   **Dynamic Fan Speed Control:** Adjusts fan speeds (radiator and chassis) based on temperature readings.
*   **Q-Learning Integration:** Evaluates the reward of fan speed actions based on a custom reward function (temperature deviation and estimated noise).
*   **Persistent Q-Table:** Saves the learned Q-values to a file, allowing the system to retain its "learning" across reboots.
*   **Critical Temperature Override:** Automatically sets fans to 100% in case of critical temperature thresholds for immediate cooling.
*   **Systemd Service:** Runs as a background service, starting automatically on boot.
*   **Root Notifications:** Sends email notifications to the `root` user for service start/stop and critical temperature events.
*   **CSV Data Logging:** Records temperature, fan speed, and reward data to a CSV file for analysis.

## Prerequisites

### Hardware

*   **Corsair Commander Core XT:** Required for radiator fan control.
*   **NVMe Drives:** The script queries NVMe drive temperatures.

### Software

*   **Linux Operating System:** Tested on Debian-based systems.
*   **Python 3:** The script is written in Python 3.
*   **`liquidctl`:** Python library for controlling liquid cooling devices.
    ```bash
    sudo pip3 install liquidctl
    ```
*   **`numpy`:** Python library for numerical operations.
    ```bash
    sudo pip3 install numpy
    ```
*   **`nvme-cli`:** Command-line tool for NVMe management.
    ```bash
    # For Debian/Ubuntu
    sudo apt install nvme-cli
    # For Fedora
    sudo dnf install nvme-cli
    # For Arch Linux
    sudo pacman -S nvme-cli
    ```
*   **`mailutils`:** For sending email notifications to `root`.
    ```bash
    # For Debian/Ubuntu
    sudo apt install mailutils
    # For Fedora
    sudo dnf install mailx # (mailx is often the package name for mail command)
    # For Arch Linux
    sudo pacman -S mailutils
    ```
*   **`systemd`:** Init system for managing the service (standard on most modern Linux distros).

## Installation

### Manual Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/your-repo-name.git # Replace with your repo details
    cd your-repo-name
    ```
2.  **Install Python dependencies:**
    ```bash
    sudo pip3 install liquidctl numpy
    ```
3.  **Install system utilities:**
    ```bash
    # Example for Debian/Ubuntu
    sudo apt update
    sudo apt install nvme-cli mailutils
    ```
4.  **Copy the main script:**
    ```bash
    sudo cp fan_monitor_qlearning.py /usr/local/bin/
    sudo chmod +x /usr/local/bin/fan_monitor_qlearning.py
    ```
5.  **Copy the systemd service file:**
    ```bash
    sudo cp fan_monitor_qlearning.service /etc/systemd/system/
    ```
6.  **Reload systemd, enable, and start the service:**
    ```bash
    sudo systemctl daemon-reexec
    sudo systemctl daemon-reload
    sudo systemctl enable fan_monitor_qlearning.service
    sudo systemctl start fan_monitor_qlearning.service
    ```
7.  **Verify the service status:**
    ```bash
    sudo systemctl status fan_monitor_qlearning.service
    ```

### Using the `install.sh` script

The repository includes a convenience script `install.sh` to automate the installation steps.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/your-repo-name.git # Replace with your repo details
    cd your-repo-name
    ```
2.  **Ensure necessary system utilities are installed (as mentioned in prerequisites):**
    ```bash
    # Example for Debian/Ubuntu
    sudo apt update
    sudo apt install nvme-cli mailutils
    ```
3.  **Run the installation script:**
    ```bash
    sudo bash install.sh
    ```
    This script will:
    *   Stop and disable any existing `fan_monitor_qlearning.service`.
    *   Copy `fan_monitor_qlearning.py` to `/usr/local/bin/` and make it executable.
    *   Copy `fan_monitor_qlearning.service` to `/etc/systemd/system/`.
    *   Reload systemd configurations.
    *   Enable and start the `fan_monitor_qlearning.service`.

## Configuration

The main configuration parameters are located at the beginning of the `fan_monitor_qlearning.py` script under the `--- Configuration Constants ---` section. You can adjust these values to suit your specific hardware and preferences.

```python
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
