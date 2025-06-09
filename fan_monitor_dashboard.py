import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
from datetime import datetime, time
from streamlit_autorefresh import st_autorefresh

DATA_FILE = '/var/log/fan_monitor_data.csv'

st.set_page_config(page_title='Fan Monitor Dashboard', layout='wide')
st.title('🌀 Fan Monitor with Q-learning')
st.markdown('Visualização dos dados térmicos e de aprendizado do sistema.')

# 🔄 Auto-refresh a cada 30 segundos (mantém estado)
st_autorefresh(interval=30 * 1000, key="data_refresh")

if not os.path.exists(DATA_FILE):
    st.warning(f'Data file not found: {DATA_FILE}')
    st.stop()

try:
    df = pd.read_csv(DATA_FILE, parse_dates=['timestamp'])
except Exception as e:
    st.error(f'Error reading CSV: {e}')
    st.stop()

if df.empty:
    st.warning("O arquivo CSV está vazio.")
    st.stop()

df['timestamp'] = pd.to_datetime(df['timestamp'])

# 🎛️ Filtros na barra lateral com session_state
st.sidebar.header("🔍 Filtros")

# Inicializa session_state
if "start_time" not in st.session_state:
    st.session_state.start_time = df['timestamp'].iloc[0].time()
if "end_time" not in st.session_state:
    st.session_state.end_time = df['timestamp'].iloc[-1].time()

# Controles com valores persistentes
st.session_state.start_time = st.sidebar.time_input("Hora inicial", value=st.session_state.start_time)
st.session_state.end_time = st.sidebar.time_input("Hora final", value=st.session_state.end_time)

# Aplicar filtros
df = df[df['timestamp'].dt.time.between(st.session_state.start_time, st.session_state.end_time)]

if df.empty:
    st.warning("Nenhum dado disponível no intervalo selecionado.")
    st.stop()

# 📉 Downsample e suavização
df = df.iloc[::6]
df['fan_rad_avg'] = df['fan_rad'].rolling(window=6, min_periods=1).mean()
df['fan_chs_avg'] = df['fan_chs'].rolling(window=6, min_periods=1).mean()

# 📊 Últimos valores
st.markdown("### 📊 Últimos valores")
latest = df.iloc[-1]
col1, col2, col3, col4 = st.columns(4)
col1.metric("Radiator Temp (°C)", f"{latest['temp_rad']:.1f}")
col2.metric("NVMe Temp (°C)", f"{latest['temp_nvme']:.1f}")
col3.metric("Fan Radiator (%)", int(latest['fan_rad']))
col4.metric("Fan Chassis (%)", int(latest['fan_chs']))

# 📈 Temperaturas
st.markdown("### 📈 Temperaturas")
fig_temp = px.line(df, x='timestamp', y=['temp_rad', 'temp_nvme'],
                   labels={'value': '°C', 'timestamp': 'Horário'}, 
                   title='Temperaturas Radiador / NVMe')
fig_temp.update_layout(paper_bgcolor='white', plot_bgcolor='white')
st.plotly_chart(fig_temp, use_container_width=True)

# 🔊 Ruído e recompensa
st.markdown("### 🔊 Ruído e Recompensa")
fig_nr = go.Figure()
fig_nr.add_trace(go.Scatter(x=df['timestamp'], y=df['noise_est'],
                            mode='lines', name='Ruído Estimado', line=dict(color='orange')))
fig_nr.add_trace(go.Scatter(x=df['timestamp'], y=df['reward'],
                            mode='lines', name='Recompensa', yaxis='y2', line=dict(color='green')))
fig_nr.update_layout(
    xaxis=dict(domain=[0.1, 0.9]),
    yaxis=dict(title='Ruído'),
    yaxis2=dict(title='Recompensa', overlaying='y', side='right'),
    legend=dict(x=0.01, y=1.1, orientation="h"),
    margin=dict(t=40),
    paper_bgcolor='white',
    plot_bgcolor='white'
)
st.plotly_chart(fig_nr, use_container_width=True)

# 🌀 Fans
st.markdown("### 🌀 Velocidade dos Fans")
fig_fan = px.line(df, x='timestamp', y=['fan_rad_avg', 'fan_chs_avg'],
                  labels={'value': 'Fan %', 'timestamp': 'Horário'},
                  title='Velocidade Média dos Fans')
fig_fan.update_layout(paper_bgcolor='white', plot_bgcolor='white')
st.plotly_chart(fig_fan, use_container_width=True)