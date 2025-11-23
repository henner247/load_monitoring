import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
from datetime import datetime, timedelta
import os

# --- KONFIGURATION ---
st.set_page_config(page_title="Stromlast Monitor", layout="wide")
st.title("⚡ Deutscher Stromverbrauch - Dashboard")

# Dateiname für den lokalen Speicher
CSV_FILE = "stromlast_historie.csv"

# --- FUNKTIONEN ---

def fetch_data_from_api(start_date, end_date):
    """Lädt Daten für einen Zeitraum von der API."""
    data_frames = []
    headers = {'User-Agent': 'Mozilla/5.0 PythonScript/1.0'}
    
    start_year = start_date.year
    end_year = end_date.year
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    years_to_load = range(start_year, end_year + 1)
    
    for i, year in enumerate(years_to_load):
        current_start = start_date.strftime("%Y-%m-%d") if year == start_year else f"{year}-01-01"
        current_end = end_date.strftime("%Y-%m-%d") if year == end_year else f"{year}-12-31"
        
        status_text.text(f"Lade API Daten: {current_start} bis {current_end}...")
        
        try:
            url = f"https://api.energy-charts.info/public_power?country=de&start={current_start}&end={current_end}&lang=en"
            r = requests.get(url, headers=headers, timeout=30)
            data_json = r.json()
            
            source = data_json.get('production_types', data_json.get('data', []))
            timestamps = data_json.get('unix_seconds', [])
            
            load_vals = []
            for entry in source:
                if 'load' in entry.get('name', '').lower():
                    load_vals = entry['data']
                    break
            
            if timestamps and load_vals:
                min_len = min(len(timestamps), len(load_vals))
                df_temp = pd.DataFrame({
                    'Zeitstempel': pd.to_datetime(timestamps[:min_len], unit='s', utc=True),
                    'Last_GW': load_vals[:min_len]
                })
                data_frames.append(df_temp)
                
        except Exception as e:
            st.warning(f"Fehler bei Jahr {year}: {e}")
            
        progress_bar.progress((i + 1) / len(years_to_load))

    progress_bar.empty()
    status_text.empty()
    
    if data_frames:
        return pd.concat(data_frames, ignore_index=True)
    return pd.DataFrame()

def load_and_update_data():
    """Lädt lokale CSV und holt nur fehlende neue Daten."""
    full_df = pd.DataFrame()
    last_stored_date = None
    
    # 1. VERSUCH: Bestehende CSV laden
    if os.path.exists(CSV_FILE):
        try:
            full_df = pd.read_csv(CSV_FILE)
            full_df['Zeitstempel'] = pd.to_datetime(full_df['Zeitstempel'], utc=True)
            
            if not full_df.empty:
                last_stored_date = full_df['Zeitstempel'].max()
                st.toast(f"Historie geladen bis: {last_stored_date.date()}", icon="💾")
        except Exception as e:
            st.error(f"Konnte lokale CSV nicht lesen: {e}")

    # 2. PRÜFUNG: Was fehlt bis heute?
    today = pd.Timestamp.now(tz='UTC').normalize()
    
    if last_stored_date is None:
        start_date = pd.Timestamp("2015-01-01", tz='UTC')
    else:
        start_date = last_stored_date + timedelta(days=1)

    # 3. UPDATE
    if start_date <= today:
        new_data = fetch_data_from_api(start_date, today)
        
        if not new_data.empty:
            full_df = pd.concat([full_df, new_data], ignore_index=True)
            full_df = full_df.drop_duplicates(subset=['Zeitstempel'])
            full_df = full_df.sort_values('Zeitstempel')
            
            full_df.to_csv(CSV_FILE, index=False)
            st.toast(f"{len(new_data)} neue Datensätze geladen.", icon="📥")
            
    return full_df

# --- HAUPTPROGRAMM ---

# Daten laden
df = load_and_update_data()

if df.empty:
    st.error("Keine Daten verfügbar.")
    st.stop()

# Zeitzone anpassen
df['Zeitstempel'] = df['Zeitstempel'].dt.tz_convert('Europe/Berlin')

# --- DATENVERARBEITUNG ---
df_daily = df.set_index('Zeitstempel').resample('D')['Last_GW'].mean().to_frame(name='Last_GW_Tag')
df_daily['Last_GW_7d_Mean'] = df_daily['Last_GW_Tag'].rolling(window=7).mean()

df_daily['TagDesJahres'] = df_daily.index.dayofyear
df_daily['Jahr'] = df_daily.index.year
pivot_table = df_daily.pivot_table(index='TagDesJahres', columns='Jahr', values='Last_GW_7d_Mean')

df_daily['Veränderung_Vorjahr_Prozent'] = df_daily['Last_GW_7d_Mean'].pct_change(364) * 100

# --- CHART 1: SAISONALITÄT ---
st.subheader("1. Saisonale Entwicklung (Jahre im Vergleich)")

fig1 = go.Figure()
years = pivot_table.columns
current_year = years[-1]
last_year = years[-2] if len(years) > 1 else current_year
year_minus_2 = years[-3] if len(years) > 2 else current_year
year_minus_3 = years[-4] if len(years) > 3 else current_year

background_label_set = False

for year in years:
    color = '#708090'
    width = 1.2
    opacity = 0.65
    name = "2015-2021"
    showlegend = False
    
    if year < year_minus_3:
        if not background_label_set:
            showlegend = True
            background_label_set = True
    else:
        showlegend = True
        name = str(year)

    if year == year_minus_3: color, width, opacity = '#2ca02c', 2, 0.9
    elif year == year_minus_2: color, width, opacity = '#1f77b4', 2, 0.9
    elif year == last_year: color, width, opacity, name = 'black', 2, 0.85, f"{year} (Vorjahr)"
    elif year == current_year: color, width, opacity, name = 'red', 4, 1.0, f"{year} (Aktuell)"

    fig1.add_trace(go.Scatter(
        x=pivot_table.index, y=pivot_table[year], mode='lines', name=name,
        line=dict(color=color, width=width), opacity=opacity, showlegend=showlegend,
        hovertemplate=f"Jahr {year}: %{{y:.2f}} GW<extra></extra>"
    ))

fig1.update_layout(
    xaxis_title="Tag des Jahres", yaxis_title="Last (GW)",
    template="plotly_white", hovermode="x unified", height=500,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99)
)
st.plotly_chart(fig1, use_container_width=True)


# --- CHART 2: TREND ---
st.subheader("2. Trend-Analyse: Veränderung zum Vorjahr")
st.markdown("Zeigt, ob wir aktuell **mehr (Grün)** oder **weniger (Rot)** Strom verbrauchen als zur gleichen Zeit im Vorjahr.")

df_trend = df_daily.dropna(subset=['Veränderung_Vorjahr_Prozent'])
df_trend['pos'] = df_trend['Veränderung_Vorjahr_Prozent'].apply(lambda x: x if x > 0 else 0)
df_trend['neg'] = df_trend['Veränderung_Vorjahr_Prozent'].apply(lambda x: x if x < 0 else 0)

fig2 = go.Figure()

fig2.add_trace(go.Scatter(
    x=df_trend.index, y=df_trend['pos'], mode='none', fill='tozeroy',
    fillcolor='rgba(44, 160, 44, 0.5)', name='Mehr Verbrauch',
    hovertemplate="%{y:.1f}%<extra></extra>"
))

fig2.add_trace(go.Scatter(
    x=df_trend.index, y=df_trend['neg'], mode='none', fill='tozeroy',
    fillcolor='rgba(214, 39, 40, 0.5)', name='Weniger Verbrauch',
    hovertemplate="%{y:.1f}%<extra></extra>"
))

fig2.add_trace(go.Scatter(
    x=df_trend.index, y=df_trend['Veränderung_Vorjahr_Prozent'], mode='lines',
    line=dict(color='gray', width=1), name='Trend Linie', showlegend=False, hoverinfo='skip'
))

fig2.add_hline(y=0, line_width=1.5, line_color="black")

fig2.update_layout(
    xaxis_title="Datum", yaxis_title="Veränderung (%)",
    template="plotly_white", hovermode="x unified", height=400,
    showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)

st.plotly_chart(fig2, use_container_width=True)

# --- FUSSZEILE / METRIKEN ---
last_val = df_daily['Last_GW_7d_Mean'].iloc[-1]
last_change = df_daily['Veränderung_Vorjahr_Prozent'].iloc[-1]

col1, col2 = st.columns(2)
col1.metric("Aktueller 7-Tage-Schnitt", f"{last_val:.2f} GW")
col2.metric("Veränderung zum Vorjahr", f"{last_change:+.1f} %", delta_color="inverse")

# --- QUELLE ---
st.divider()
st.caption("Datenquelle: Energy Charts (Fraunhofer ISE) / Public Power Load Deutschland (Last + Importe - Exporte)")