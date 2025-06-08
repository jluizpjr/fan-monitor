
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import os
from datetime import datetime

DATA_FILE = '/var/log/fan_monitor_data.csv'

st.set_page_config(page_title='Fan Monitor Dashboard', layout='wide')
st.title('🌀 Fan Monitor with Q-learning')
st.markdown('Visualização dos dados térmicos e de aprendizado do sistema.')

if not os.path.exists(DATA_FILE):
    st.warning(f'Data file not found: {DATA_FILE}')
    st.stop()

# Load CSV
try:
    df = pd.read_csv(DATA_FILE, parse_dates=['timestamp'])
except Exception as e:
    st.error(f'Error reading CSV: {e}')
    st.stop()

# Sidebar filters
st.sidebar.header("🔍 Filtros")
start_time = st.sidebar.time_input("Hora inicial", value=df['timestamp'].iloc[0].time())
end_time = st.sidebar.time_input("Hora final", value=df['timestamp'].iloc[-1].time())

df['timestamp'] = pd.to_datetime(df['timestamp'])
df = df[df['timestamp'].dt.time.between(start_time, end_time)]

# Metrics
st.markdown("### 📊 Últimos valores")
latest = df.iloc[-1]
col1, col2, col3, col4 = st.columns(4)
col1.metric("Radiator Temp (°C)", f"{latest['temp_rad']:.1f}")
col2.metric("NVMe Temp (°C)", f"{latest['temp_nvme']:.1f}")
col3.metric("Fan Radiator (%)", int(latest['fan_rad']))
col4.metric("Fan Chassis (%)", int(latest['fan_chs']))

# Time series plots
st.markdown("### 📈 Temperaturas")
fig1, ax1 = plt.subplots()
ax1.plot(df['timestamp'], df['temp_rad'], label='Radiator Temp', color='blue')
ax1.plot(df['timestamp'], df['temp_nvme'], label='NVMe Temp', color='red')
ax1.set_ylabel("°C")
ax1.legend()
st.pyplot(fig1)

st.markdown("### 🔊 Ruído estimado e recompensa")
fig2, ax2 = plt.subplots()
ax2.plot(df['timestamp'], df['noise_est'], label='Noise Est.', color='orange')
ax2.set_ylabel("Noise Estimate", color='orange')
ax2.tick_params(axis='y', labelcolor='orange')

ax3 = ax2.twinx()
ax3.plot(df['timestamp'], df['reward'], label='Reward', color='green')
ax3.set_ylabel("Reward", color='green')
ax3.tick_params(axis='y', labelcolor='green')

fig2.tight_layout()
st.pyplot(fig2)

st.markdown("### 🌀 Velocidade dos Fans")
fig3, ax4 = plt.subplots()
ax4.plot(df['timestamp'], df['fan_rad'], label='Radiator Fan %', color='purple')
ax4.plot(df['timestamp'], df['fan_chs'], label='Chassis Fan %', color='teal')
ax4.set_ylabel("Fan Speed (%)")
ax4.legend()
st.pyplot(fig3)
