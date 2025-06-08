
# 🌀 Intelligent Fan Control with Q-learning

A complete thermal management system for Linux servers using **Q-learning**, real-time sensor feedback (liquidctl + smartctl), and adaptive fan control to optimize for **cooling efficiency and low noise**.

## 🚀 Features

- ✅ **Q-learning AI** for adaptive fan speed control
- ✅ Monitors **radiator (Commander Core XT)** and **NVMe SSD temperatures**
- ✅ Controls radiator and chassis fans individually
- ✅ Automatically balances **temperature** and **noise**
- ✅ 📈 Web dashboard (Streamlit) to visualize performance
- ✅ 📁 Logs saved in `/var/log` for analysis
- ✅ 🎨 Color-coded logs in terminal
- ✅ 🛠 Installs as a systemd service

---

## 🧠 How It Works

The system collects temperature data and learns, over time, the best fan speed combination for:

- Reducing **radiator and SSD temperature**
- Minimizing **fan noise**
- Adapting to **dynamic workloads**

It stores all decisions, actions, and rewards in `/var/log/fan_monitor_data.csv`.

---

## 🖥 Dashboard (Streamlit)

Run this to visualize system performance:

```bash
streamlit run fan_monitor_dashboard.py
```

### Includes:
- Temperatures (Radiator + NVMe)
- Estimated noise
- Reward curve
- Fan speeds over time

---

## 📦 Included Files

| File | Description |
|------|-------------|
| `fan_monitor_qlearning_final.py` | Main script (Q-learning + sensors + fan control) |
| `fan_monitor_qlearning_final.service` | Systemd unit for autostart |
| `install_qlearning_final.sh` | Installer script |
| `fan_monitor_dashboard.py` | Real-time dashboard via Streamlit |
| `README.md` | This documentation |

---

## 🔧 Installation

### Step 1: Install dependencies

```bash
sudo apt install python3-pip smartmontools mailutils
pip3 install liquidctl streamlit pandas matplotlib
```

### Step 2: Install the fan monitor system

```bash
chmod +x install_qlearning_final.sh
sudo ./install_qlearning_final.sh
```

### Step 3: View logs

```bash
tail -f /var/log/fan_monitor_qlearning.log
```

---

## 🧼 Uninstall

```bash
sudo systemctl stop fan_monitor_qlearning_final.service
sudo systemctl disable fan_monitor_qlearning_final.service
sudo rm /usr/local/bin/fan_monitor_qlearning_final.py
sudo rm /etc/systemd/system/fan_monitor_qlearning_final.service
```

---

## 📧 Author

João Luiz Pereira  
📫 jluizpjr@gmail.com

---

Enjoy silent, intelligent cooling. ❄️🧠
