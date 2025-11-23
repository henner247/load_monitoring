import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
from datetime import datetime
import numpy as np

# --- KONFIGURATION DER SEITE ---
st.set_page_config(page_title="Stromlast Monitor", layout="wide")

st.title("⚡ Deutscher Stromverbrauch - Live Monitor")
st.markdown("Diese App zeigt die tägliche Stromlast (geglättet) im Vergleich der letzten Jahre.")

# --- 1. DATEN LADEN (MIT CACHING) ---
# @st.cache_data sorgt dafür, dass die Daten nicht bei jedem Neuladen der Seite
# neu heruntergeladen werden, sondern nur alle 24 Stunden (ttl=86400 Sekunden).
@st.cache_data(ttl=86400)
def load_data():
    # Dein Download-Loop von vorhin (hier kompakt zusammengefasst)
    current_year = datetime.now().year
    start_year = current_year - 10
    years = range(start_year, current_year + 1)
    
    all_dataframes = []
    headers = {'User-Agent': 'Mozilla/5.0 PythonScript/1.0'}

    # Progress Bar für den User anzeigen
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, year in enumerate(years):
        status_text.text(f"Lade Daten für {year}...")
        try:
            url = f"https://api.energy-charts.info/public_power?country=de&start={year}-01-01&end={year}-12-31&lang=en"
            response = requests.get(url, headers=headers, timeout=30)
            data_json = response.json()
            
            data_source = data_json.get('production_types', data_json.get('data', []))
            timestamps = data_json.get('unix_seconds', [])
            
            load_values = []
            if timestamps:
                for entry in data_source:
                    if 'load' in entry.get('name', '').lower():
                        load_values = entry['data']
                        break
            
            if load_values:
                min_len = min(len(timestamps), len(load_values))
                df_year = pd.DataFrame({'timestamp_unix': timestamps[:min_len], 'Last_GW': load_values[:min_len]})
                all_dataframes.append(df_year)
        except:
            pass
        
        # Update Progress Bar
        progress_bar.progress((i + 1) / len(years))

    status_text.empty()
    progress_bar.empty()

    if all_dataframes:
        full_df = pd.concat(all_dataframes, ignore_index=True)
        full_df['Zeitstempel'] = pd.to_datetime(full_df['timestamp_unix'], unit='s', utc=True)
        full_df['Zeitstempel'] = full_df['Zeitstempel'].dt.tz_convert('Europe/Berlin')
        return full_df.drop(columns=['timestamp_unix']).sort_values('Zeitstempel')
    return pd.DataFrame()

# Daten abrufen
df = load_data()

if df.empty:
    st.error("Keine Daten geladen.")
    st.stop()

# --- 2. DATENVERARBEITUNG ---
df = df.set_index('Zeitstempel')
df_daily = df.resample('D')['Last_GW'].mean().to_frame(name='Last_GW_Tag')
df_daily['Last_GW_7d_Mean'] = df_daily['Last_GW_Tag'].rolling(window=7).mean()

df_daily['TagDesJahres'] = df_daily.index.dayofyear
df_daily['Jahr'] = df_daily.index.year
pivot_table = df_daily.pivot_table(index='TagDesJahres', columns='Jahr', values='Last_GW_7d_Mean')

# --- 3. INTERAKTIVER PLOT MIT PLOTLY ---
fig = go.Figure()

years = pivot_table.columns
current_year = years[-1]
last_year = years[-2]
year_minus_2 = years[-3]
year_minus_3 = years[-4]

background_label_set = False

for year in years:
    # Standard Stil (Hintergrund)
    color = '#708090'
    width = 1
    opacity = 0.5
    name = "2015-2021"
    showlegend = False
    
    # Legende nur 1x anzeigen für Hintergrund
    if year < year_minus_3:
        if not background_label_set:
            showlegend = True
            background_label_set = True
        else:
            showlegend = False
    else:
        showlegend = True
        name = str(year)

    # Highlight Jahre
    if year == year_minus_3: # 2022
        color = '#2ca02c'
        width = 2
        opacity = 0.8
    elif year == year_minus_2: # 2023
        color = '#1f77b4'
        width = 2
        opacity = 0.9
    elif year == last_year: # 2024
        color = 'black'
        width = 2
        opacity = 0.85
        name = f"{year} (Vorjahr)"
    elif year == current_year: # Aktuell
        color = 'red'
        width = 4
        opacity = 1.0
        name = f"{year} (Aktuell)"

    # Linie hinzufügen
    fig.add_trace(go.Scatter(
        x=pivot_table.index,
        y=pivot_table[year],
        mode='lines',
        name=name,
        line=dict(color=color, width=width),
        opacity=opacity,
        showlegend=showlegend,
        hovertemplate=f"Jahr {year}: %{{y:.2f}} GW<extra></extra>" # Tooltip Formatierung
    ))

# Layout aufhübschen
fig.update_layout(
    title="Stromlast im Jahresvergleich (Interaktiv)",
    xaxis_title="Tag des Jahres",
    yaxis_title="Last (GW)",
    template="plotly_white",
    hovermode="x unified", # Zeigt alle Werte an einer vertikalen Linie
    height=600,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99)
)

st.plotly_chart(fig, use_container_width=True)

# Kleines Extra: Aktuelle Kennzahlen
last_val = df_daily['Last_GW_7d_Mean'].iloc[-1]
last_date = df_daily.index[-1].strftime('%d.%m.%Y')
st.metric(label=f"Aktueller 7-Tage-Schnitt ({last_date})", value=f"{last_val:.2f} GW")