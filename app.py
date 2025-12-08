import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
from datetime import datetime, timedelta
import os

# --- 1. KONFIGURATION ---
st.set_page_config(page_title="European Power Monitor", layout="wide")

# Länder-Definition
# 'ch' ist separat, wird bei Aggregation ausgeschlossen
COUNTRIES = {
    "de": "Deutschland 🇩🇪",
    "fr": "Frankreich 🇫🇷",
    "it": "Italien 🇮🇹",
    "es": "Spanien 🇪🇸",
    "pl": "Polen 🇵🇱",
    "nl": "Niederlande 🇳🇱",
    "be": "Belgien 🇧🇪",
    "at": "Österreich 🇦🇹",
    "cz": "Tschechien 🇨🇿",  # <--- NEU HINZUGEFÜGT
    "ch": "Schweiz 🇨🇭" 
}
# --- 2. SIDEBAR & AUSWAHL ---
st.sidebar.title("Einstellungen")

# Dropdown-Liste vorbereiten: Erst Aggregation, dann Länder
options_list = ["eu_agg"] + list(COUNTRIES.keys())

def format_option(option):
    if option == "eu_agg":
        return "🇪🇺 EU (Aggregiert - Top 8 ohne CH)"
    return COUNTRIES[option]

selected_code = st.sidebar.selectbox(
    "Daten auswählen:",
    options=options_list,
    format_func=format_option
)

# Variablen setzen je nach Auswahl
if selected_code == "eu_agg":
    st.title("⚡ Stromlast Monitor - EU Aggregiert")
    st.caption("Summe aus: DE, FR, IT, ES, PL, NL, BE, AT")
    CSV_FILE = None
else:
    country_name = COUNTRIES[selected_code]
    st.title(f"⚡ Stromlast Monitor - {country_name}")
    CSV_FILE = f"stromlast_historie_{selected_code}.csv"


# --- 3. FUNKTIONEN ---

def fetch_data_from_api(country_code, start_date, end_date):
    """Lädt Daten via API für ein spezifisches Land (für Updates)."""
    data_frames = []
    headers = {'User-Agent': 'Mozilla/5.0 PythonScript/1.0'}
    
    start_year = start_date.year
    end_year = end_date.year
    years_to_load = range(start_year, end_year + 1)
    
    prog_bar = st.sidebar.progress(0)
    
    for i, year in enumerate(years_to_load):
        current_start = start_date.strftime("%Y-%m-%d") if year == start_year else f"{year}-01-01"
        current_end = end_date.strftime("%Y-%m-%d") if year == end_year else f"{year}-12-31"
        
        try:
            url = f"https://api.energy-charts.info/public_power?country={country_code}&start={current_start}&end={current_end}&lang=en"
            r = requests.get(url, headers=headers, timeout=30)
            data_json = r.json()
            
            source = data_json.get('production_types', data_json.get('data', []))
            timestamps = data_json.get('unix_seconds', [])
            load_vals = []
            
            # Intelligente Suche nach "Load"
            for entry in source:
                name = entry.get('name', '').lower()
                if 'residual' in name or 'pumped' in name or 'share' in name: continue
                
                if name in ['load', 'last', 'consommation', 'total load', 'electricity consumption']:
                    load_vals = entry['data']
                    break
                if 'load' in name or 'consumption' in name:
                    if not load_vals: load_vals = entry['data']

            if timestamps and load_vals:
                min_len = min(len(timestamps), len(load_vals))
                df_temp = pd.DataFrame({
                    'Zeitstempel': pd.to_datetime(timestamps[:min_len], unit='s', utc=True),
                    'Last_GW': load_vals[:min_len]
                })
                data_frames.append(df_temp)
                
        except Exception:
            pass # Fehler ignorieren für sauberen UI Flow
            
        prog_bar.progress((i + 1) / len(years_to_load))

    prog_bar.empty()
    
    if data_frames:
        return pd.concat(data_frames, ignore_index=True)
    return pd.DataFrame()


def load_and_update_single_country(country_code, csv_file_path):
    """Lädt CSV und holt fehlende aktuelle Daten nach."""
    full_df = pd.DataFrame()
    last_stored_date = None
    
    # 1. CSV laden
    if os.path.exists(csv_file_path):
        try:
            full_df = pd.read_csv(csv_file_path)
            full_df['Zeitstempel'] = pd.to_datetime(full_df['Zeitstempel'], utc=True)
            if not full_df.empty:
                last_stored_date = full_df['Zeitstempel'].max()
        except Exception as e:
            st.error(f"Fehler beim Lesen der CSV: {e}")

    # 2. Update prüfen
    today = pd.Timestamp.now(tz='UTC').normalize()
    if last_stored_date is None:
        start_date = pd.Timestamp("2015-01-01", tz='UTC')
    else:
        start_date = last_stored_date + timedelta(days=1)

    if start_date <= today:
        with st.spinner(f"Lade neue Daten für {country_code.upper()}..."):
            new_data = fetch_data_from_api(country_code, start_date, today)
            if not new_data.empty:
                full_df = pd.concat([full_df, new_data], ignore_index=True)
                full_df = full_df.drop_duplicates(subset=['Zeitstempel'])
                full_df = full_df.sort_values('Zeitstempel')
                full_df.to_csv(csv_file_path, index=False)
                st.toast("Daten aktualisiert!", icon="✅")
                
    return full_df


def load_eu_aggregated_data():
    """Lädt ALLE Länder-CSVs (außer Schweiz) und summiert sie."""
    df_list = []
    
    # Alle Keys außer 'ch'
    eu_codes = [c for c in COUNTRIES.keys() if c != 'ch']
    
    progress_text = st.sidebar.empty()
    progress_bar = st.sidebar.progress(0)
    
    for i, code in enumerate(eu_codes):
        filename = f"stromlast_historie_{code}.csv"
        progress_text.text(f"Lade {COUNTRIES[code]}...")
        
        if os.path.exists(filename):
            try:
                # Nur relevante Spalten laden
                temp_df = pd.read_csv(filename, usecols=['Zeitstempel', 'Last_GW'])
                temp_df['Zeitstempel'] = pd.to_datetime(temp_df['Zeitstempel'], utc=True)
                
                # Index setzen und auf 1h resamplen (wichtig für saubere Addition)
                temp_df.set_index('Zeitstempel', inplace=True)
                temp_df = temp_df.resample('1h').mean()
                
                df_list.append(temp_df)
            except Exception:
                st.sidebar.warning(f"Datei defekt: {filename}")
        
        progress_bar.progress((i + 1) / len(eu_codes))
    
    progress_text.empty()
    progress_bar.empty()

    if not df_list:
        return pd.DataFrame()

    # Pandas 'Sum' addiert DataFrames basierend auf dem Index (Zeitstempel)
    # min_count=1 sorgt dafür, dass wir NaN bekommen, wenn Daten ganz fehlen, statt 0
    st.sidebar.text("Berechne Summe...")
    total_df = sum(df_list)
    
    # Index wieder zur Spalte machen
    total_df = total_df.reset_index()
    
    return total_df


# --- 4. HAUPTPROGRAMM (DATEN LADEN) ---

df = pd.DataFrame()

if selected_code == "eu_agg":
    # Fall A: Aggregation
    if st.sidebar.button("Neu berechnen"):
        st.cache_data.clear()
        
    df = load_eu_aggregated_data()
    
    if df.empty:
        st.error("Konnte keine aggregierten Daten erstellen. Bitte stellen Sie sicher, dass Sie den 'Downloader' ausgeführt haben, damit die CSV-Dateien existieren.")
        st.stop()
else:
    # Fall B: Einzelnes Land
    df = load_and_update_single_country(selected_code, CSV_FILE)
    
    if df.empty:
        st.warning(f"Keine Daten für {COUNTRIES[selected_code]} gefunden. Bitte Downloader starten oder warten.")
        st.stop()


# --- 5. DATENVERARBEITUNG (Gleich für beide Fälle) ---

# Zeitzone
df['Zeitstempel'] = df['Zeitstempel'].dt.tz_convert('Europe/Berlin')

# Resampling auf Tage (Mean) und 7-Tage-Schnitt
df_daily = df.set_index('Zeitstempel').resample('D')['Last_GW'].mean().to_frame(name='Last_GW_Tag')
df_daily['Last_GW_7d_Mean'] = df_daily['Last_GW_Tag'].rolling(window=7).mean()

# Pivot Tabelle für Jahresvergleich
df_daily['TagDesJahres'] = df_daily.index.dayofyear
df_daily['Jahr'] = df_daily.index.year
pivot_table = df_daily.pivot_table(index='TagDesJahres', columns='Jahr', values='Last_GW_7d_Mean')

# YoY Veränderung (364 Tage = 52 Wochen Vergleich für Wochentagskonsistenz)
df_daily['Veränderung_Vorjahr_Prozent'] = df_daily['Last_GW_7d_Mean'].pct_change(364) * 100

# X-Achse Formatierung (Dummy Datum 2024 für Monate)
x_axis_dates = [datetime(2024, 1, 1) + timedelta(days=d-1) for d in pivot_table.index]


# --- 6. VISUALISIERUNG ---

# --- CHART 1: Saisonale Kurven ---
st.subheader("1. Saisonale Entwicklung (Jahresvergleich)")

fig1 = go.Figure()
years = pivot_table.columns

if len(years) > 0:
    current_year = years[-1]
    last_year = years[-2] if len(years) > 1 else current_year
    year_minus_2 = years[-3] if len(years) > 2 else current_year
    year_minus_3 = years[-4] if len(years) > 3 else current_year
else:
    current_year = None

background_label_set = False

for year in years:
    color = '#708090'
    width = 1.2
    opacity = 0.5
    name = "2015-2021"
    showlegend = False
    
    if current_year and year < year_minus_3:
        if not background_label_set:
            showlegend = True
            background_label_set = True
    else:
        showlegend = True
        name = str(year)

    if year == year_minus_3: color, width, opacity = '#2ca02c', 2, 0.8
    elif year == year_minus_2: color, width, opacity = '#1f77b4', 2, 0.8
    elif year == last_year: color, width, opacity, name = 'black', 2, 0.85, f"{year} (Vorjahr)"
    elif year == current_year: color, width, opacity, name = 'red', 4, 1.0, f"{year} (Aktuell)"

    fig1.add_trace(go.Scatter(
        x=x_axis_dates, 
        y=pivot_table[year], 
        mode='lines', 
        name=name,
        line=dict(color=color, width=width), 
        opacity=opacity, 
        showlegend=showlegend,
        hovertemplate=f"{year}: %{{y:.2f}} GW<extra></extra>"
    ))

fig1.update_layout(
    xaxis=dict(tickformat="%b", dtick="M1"),
    yaxis_title="Last (GW)",
    template="plotly_white", 
    hovermode="x unified", 
    height=550,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
    margin=dict(t=50)
)
st.plotly_chart(fig1, use_container_width=True)


# --- CHART 2: Trend ---
st.subheader("2. Trend-Analyse: Veränderung zum Vorjahr")

df_trend = df_daily.dropna(subset=['Veränderung_Vorjahr_Prozent'])
# Filter für Plot: Erst ab 2018 zeigen, sonst wird es zu unübersichtlich
df_trend = df_trend[df_trend.index.year >= 2018]

if not df_trend.empty:
    df_trend['pos'] = df_trend['Veränderung_Vorjahr_Prozent'].apply(lambda x: x if x > 0 else 0)
    df_trend['neg'] = df_trend['Veränderung_Vorjahr_Prozent'].apply(lambda x: x if x < 0 else 0)

    fig2 = go.Figure()

    fig2.add_trace(go.Scatter(
        x=df_trend.index, y=df_trend['pos'], mode='none', fill='tozeroy',
        fillcolor='rgba(255, 0, 0, 0.5)', name='Mehr Verbrauch', # Rot = Schlecht/Mehr
        hovertemplate="%{y:.1f}%<extra></extra>"
    ))

    fig2.add_trace(go.Scatter(
        x=df_trend.index, y=df_trend['neg'], mode='none', fill='tozeroy',
        fillcolor='rgba(0, 128, 0, 0.5)', name='Weniger Verbrauch', # Grün = Gut/Sparsam
        hovertemplate="%{y:.1f}%<extra></extra>"
    ))

    fig2.add_trace(go.Scatter(
        x=df_trend.index, y=df_trend['Veränderung_Vorjahr_Prozent'], mode='lines',
        line=dict(color='gray', width=1), name='Trend', showlegend=False, hoverinfo='skip'
    ))

    fig2.add_hline(y=0, line_width=1.5, line_color="black")

    fig2.update_layout(
        xaxis_title="Datum", yaxis_title="Veränderung (%)",
        template="plotly_white", hovermode="x unified", height=400,
        showlegend=True, 
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("Nicht genügend Daten für Trend-Analyse verfügbar.")

# --- FUSSZEILE ---
if not df_daily.empty:
    last_val = df_daily['Last_GW_7d_Mean'].iloc[-1]
    last_change = df_daily['Veränderung_Vorjahr_Prozent'].iloc[-1]
    
    col1, col2 = st.columns(2)
    label_country = "EU (Aggregiert)" if selected_code == "eu_agg" else selected_code.upper()
    col1.metric(f"Aktueller 7-Tage-Schnitt ({label_country})", f"{last_val:.2f} GW")
    col2.metric("Veränderung zum Vorjahr", f"{last_change:+.1f} %", delta_color="inverse")

st.divider()
st.caption("Datenquelle: Energy Charts (Fraunhofer ISE). Aggregation basiert auf lokalen CSV-Dateien.")

