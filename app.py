import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
from datetime import datetime, timedelta
import os

# --- KONFIGURATION ---
st.set_page_config(page_title="European Power Monitor", layout="wide")

# 1. LÄNDER-KONFIGURATION
COUNTRIES = {
    "de": "Deutschland 🇩🇪",
    "fr": "Frankreich 🇫🇷",
    "at": "Österreich 🇦🇹",
    "ch": "Schweiz 🇨🇭",
    "it": "Italien 🇮🇹"
}

# --- SIDEBAR ---
st.sidebar.title("Einstellungen")
selected_country_code = st.sidebar.selectbox(
    "Land auswählen:",
    options=list(COUNTRIES.keys()),
    format_func=lambda x: COUNTRIES[x]
)

country_name = COUNTRIES[selected_country_code]
st.title(f"⚡ Stromlast Monitor - {country_name}")

CSV_FILE = f"stromlast_historie_{selected_country_code}.csv"


# --- FUNKTIONEN ---

def fetch_data_from_api(country_code, start_date, end_date):
    """Lädt Daten für ein spezifisches Land und Zeitraum."""
    data_frames = []
    headers = {'User-Agent': 'Mozilla/5.0 PythonScript/1.0'}
    
    start_year = start_date.year
    end_year = end_date.year
    
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    
    years_to_load = range(start_year, end_year + 1)
    
    for i, year in enumerate(years_to_load):
        current_start = start_date.strftime("%Y-%m-%d") if year == start_year else f"{year}-01-01"
        current_end = end_date.strftime("%Y-%m-%d") if year == end_year else f"{year}-12-31"
        
        status_text.text(f"Lade {country_code.upper()} Daten: {year}...")
        
        try:
            # Versuch 1: public_power (meistens korrekt für Last)
            url = f"https://api.energy-charts.info/public_power?country={country_code}&start={current_start}&end={current_end}&lang=en"
            r = requests.get(url, headers=headers, timeout=30)
            data_json = r.json()
            
            source = data_json.get('production_types', data_json.get('data', []))
            timestamps = data_json.get('unix_seconds', [])
            
            load_vals = []
            
            # --- VERBESSERTE SUCHE NACH DER RICHTIGEN LAST ---
            for entry in source:
                name = entry.get('name', '').lower()
                
                # Ausschlusskriterien: Wir wollen KEINE Residuallast und KEINEN Pumpspeicher-Verbrauch
                if 'residual' in name or 'pumped' in name or 'share' in name:
                    continue
                
                # Volltreffer Suche
                if name == 'load' or name == 'last' or name == 'consommation' or name == 'total load':
                    load_vals = entry['data']
                    break # Gefunden!
                
                # Fallback Suche (falls kein Volltreffer)
                if 'load' in name or 'consumption' in name:
                    if not load_vals: # Nur nehmen wenn wir noch nichts besseres haben
                        load_vals = entry['data']

            if timestamps and load_vals:
                min_len = min(len(timestamps), len(load_vals))
                df_temp = pd.DataFrame({
                    'Zeitstempel': pd.to_datetime(timestamps[:min_len], unit='s', utc=True),
                    'Last_GW': load_vals[:min_len]
                })
                data_frames.append(df_temp)
                
        except Exception as e:
            st.sidebar.warning(f"Fehler bei Jahr {year}: {e}")
            
        progress_bar.progress((i + 1) / len(years_to_load))

    progress_bar.empty()
    status_text.empty()
    
    if data_frames:
        return pd.concat(data_frames, ignore_index=True)
    return pd.DataFrame()

def load_and_update_data(country_code, csv_file_path):
    full_df = pd.DataFrame()
    last_stored_date = None
    
    # 1. VERSUCH: Bestehende CSV laden
    if os.path.exists(csv_file_path):
        try:
            full_df = pd.read_csv(csv_file_path)
            full_df['Zeitstempel'] = pd.to_datetime(full_df['Zeitstempel'], utc=True)
            
            if not full_df.empty:
                last_stored_date = full_df['Zeitstempel'].max()
                st.sidebar.success(f"Lokal: Daten bis {last_stored_date.date()}")
        except Exception as e:
            st.error(f"Konnte lokale CSV nicht lesen: {e}")

    # 2. PRÜFUNG: Was fehlt?
    today = pd.Timestamp.now(tz='UTC').normalize()
    
    if last_stored_date is None:
        st.info(f"Initialisiere Datenbank für {COUNTRIES[country_code]} (ab 2015)...")
        start_date = pd.Timestamp("2015-01-01", tz='UTC')
    else:
        start_date = last_stored_date + timedelta(days=1)

    # 3. UPDATE
    if start_date <= today:
        new_data = fetch_data_from_api(country_code, start_date, today)
        
        if not new_data.empty:
            full_df = pd.concat([full_df, new_data], ignore_index=True)
            full_df = full_df.drop_duplicates(subset=['Zeitstempel'])
            full_df = full_df.sort_values('Zeitstempel')
            
            full_df.to_csv(csv_file_path, index=False)
            st.toast(f"Update: {len(new_data)} Werte geladen.", icon="📥")
            
    return full_df

# --- HAUPTPROGRAMM ---

# Daten laden
df = load_and_update_data(selected_country_code, CSV_FILE)

if df.empty:
    st.warning(f"Keine Last-Daten für {country_name} gefunden. Möglicherweise liefert die API für dieses Land keine 'Load'-Daten unter 'public_power'.")
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

# --- CHART 1 ---
st.subheader(f"1. Saisonale Entwicklung ({country_name})")

fig1 = go.Figure()
years = pivot_table.columns
if len(years) > 0:
    current_year = years[-1]
    last_year = years[-2] if len(years) > 1 else current_year
    year_minus_2 = years[-3] if len(years) > 2 else current_year
    year_minus_3 = years[-4] if len(years) > 3 else current_year
else:
    current_year = last_year = year_minus_2 = year_minus_3 = None

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


# --- CHART 2 ---
st.subheader(f"2. Trend-Analyse: Veränderung zum Vorjahr ({country_name})")

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

# --- FUSSZEILE ---
if not df_daily.empty:
    last_val = df_daily['Last_GW_7d_Mean'].iloc[-1]
    last_change = df_daily['Veränderung_Vorjahr_Prozent'].iloc[-1]
    
    col1, col2 = st.columns(2)
    # HIER WAR DER FEHLER: country_code -> selected_country_code
    col1.metric(f"Aktueller 7-Tage-Schnitt ({selected_country_code.upper()})", f"{last_val:.2f} GW")
    col2.metric("Veränderung zum Vorjahr", f"{last_change:+.1f} %", delta_color="inverse")

st.divider()
st.caption("Datenquelle: Energy Charts (Fraunhofer ISE).")