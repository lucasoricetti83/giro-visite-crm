import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from datetime import datetime, timedelta, time
from math import radians, cos, sin, asin, sqrt
import io
import re
import time as time_module
import requests
from supabase import create_client, Client

# --- 1. CONFIGURAZIONE ---
st.set_page_config(page_title="Giro Visite CRM Pro", layout="wide", page_icon="🚀")

# Supabase credentials
SUPABASE_URL = "https://ectezeclocjfbpbxdhyk.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVjdGV6ZWNsb2NqZmJwYnhkaHlrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njk2Mzg4NzcsImV4cCI6MjA4NTIxNDg3N30.k_i6vZBmVXhQs6NFSi_IiH6HSiN7O6tG3WwGViw7PIs"

# LocationIQ API Key
LOCATIONIQ_KEY = "pk.eb703bb4dbacec20df9f83c1a6a807e3"

@st.cache_resource
def get_supabase_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = get_supabase_client()

# --- 2. AUTENTICAZIONE ---
def init_auth_state():
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'session' not in st.session_state:
        st.session_state.session = None

def login_page():
    st.title("🚀 Giro Visite CRM Pro")
    st.markdown("### Accedi o Registrati")
    
    tab_login, tab_register = st.tabs(["🔐 Accedi", "📝 Registrati"])
    
    with tab_login:
        with st.form("login_form"):
            email = st.text_input("📧 Email")
            password = st.text_input("🔑 Password", type="password")
            submitted = st.form_submit_button("🚀 Accedi", use_container_width=True, type="primary")
            
            if submitted:
                if email and password:
                    try:
                        response = supabase.auth.sign_in_with_password({
                            "email": email,
                            "password": password
                        })
                        st.session_state.user = response.user
                        st.session_state.session = response.session
                        st.success("✅ Accesso effettuato!")
                        time_module.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Errore: {str(e)}")
                else:
                    st.warning("⚠️ Inserisci email e password")
    
    with tab_register:
        with st.form("register_form"):
            new_email = st.text_input("📧 Email")
            new_password = st.text_input("🔑 Password", type="password")
            confirm_password = st.text_input("🔑 Conferma Password", type="password")
            submitted = st.form_submit_button("📝 Registrati", use_container_width=True, type="primary")
            
            if submitted:
                if new_email and new_password:
                    if new_password != confirm_password:
                        st.error("❌ Le password non coincidono")
                    elif len(new_password) < 6:
                        st.error("❌ La password deve avere almeno 6 caratteri")
                    else:
                        try:
                            response = supabase.auth.sign_up({
                                "email": new_email,
                                "password": new_password
                            })
                            st.success("✅ Registrazione completata! Controlla la tua email per confermare l'account.")
                        except Exception as e:
                            st.error(f"❌ Errore: {str(e)}")
                else:
                    st.warning("⚠️ Compila tutti i campi")
    
    st.divider()
    st.caption("© 2025 Giro Visite CRM Pro - Versione SaaS")

def logout():
    try:
        supabase.auth.sign_out()
    except:
        pass
    st.session_state.user = None
    st.session_state.session = None
    st.session_state.clear()
    st.rerun()

# --- 3. DATABASE FUNCTIONS ---
def get_user_id():
    if st.session_state.user:
        return st.session_state.user.id
    return None

def fetch_clienti():
    """Carica tutti i clienti dell'utente corrente"""
    try:
        user_id = get_user_id()
        if not user_id:
            return pd.DataFrame()
        
        response = supabase.table('clienti').select('*').eq('user_id', user_id).execute()
        
        if response.data:
            df = pd.DataFrame(response.data)
            # Converti colonne
            df['ultima_visita'] = pd.to_datetime(df['ultima_visita'], errors='coerce')
            df['appuntamento'] = pd.to_datetime(df['appuntamento'], errors='coerce')
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            df['frequenza_giorni'] = pd.to_numeric(df['frequenza_giorni'], errors='coerce').fillna(30).astype(int)
            df['visitare'] = df['visitare'].fillna('SI').str.upper()
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"❌ Errore caricamento clienti: {str(e)}")
        return pd.DataFrame()

def save_cliente(cliente_data):
    """Salva un nuovo cliente"""
    try:
        user_id = get_user_id()
        cliente_data['user_id'] = user_id
        response = supabase.table('clienti').insert(cliente_data).execute()
        return True
    except Exception as e:
        st.error(f"❌ Errore salvataggio: {str(e)}")
        return False

def update_cliente(cliente_id, update_data):
    """Aggiorna un cliente esistente"""
    try:
        response = supabase.table('clienti').update(update_data).eq('id', cliente_id).execute()
        return True
    except Exception as e:
        st.error(f"❌ Errore aggiornamento: {str(e)}")
        return False

def delete_cliente(cliente_id):
    """Elimina un cliente"""
    try:
        response = supabase.table('clienti').delete().eq('id', cliente_id).execute()
        return True
    except Exception as e:
        st.error(f"❌ Errore eliminazione: {str(e)}")
        return False

def fetch_config():
    """Carica la configurazione dell'utente"""
    try:
        user_id = get_user_id()
        if not user_id:
            return None
        
        response = supabase.table('config_utente').select('*').eq('user_id', user_id).execute()
        
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        return None

def save_config(config_data):
    """Salva o aggiorna la configurazione utente"""
    try:
        user_id = get_user_id()
        config_data['user_id'] = user_id
        
        # Prova a fare upsert
        existing = fetch_config()
        if existing:
            response = supabase.table('config_utente').update(config_data).eq('user_id', user_id).execute()
        else:
            response = supabase.table('config_utente').insert(config_data).execute()
        return True
    except Exception as e:
        st.error(f"❌ Errore salvataggio config: {str(e)}")
        return False

# --- 4. UTILITY FUNCTIONS ---
ora_italiana = datetime.now() + timedelta(hours=1)

def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    return 2 * 6371 * asin(sqrt(a))

def calcola_km_tempo_giro(tappe, start_lat, start_lon, durata_visita_min=45, velocita_media_kmh=50):
    if not tappe:
        return 0, 0, 0
    
    km_totale = 0
    pos_corrente = (start_lat, start_lon)
    
    for tappa in tappe:
        dist = haversine(pos_corrente[0], pos_corrente[1], tappa['latitude'], tappa['longitude'])
        km_totale += dist
        pos_corrente = (tappa['latitude'], tappa['longitude'])
    
    km_ritorno = haversine(pos_corrente[0], pos_corrente[1], start_lat, start_lon)
    km_totale += km_ritorno
    
    tempo_guida_min = (km_totale / velocita_media_kmh) * 60
    tempo_visite_min = len(tappe) * durata_visita_min
    tempo_totale_min = tempo_guida_min + tempo_visite_min
    
    return round(km_totale, 1), round(tempo_guida_min), round(tempo_totale_min)

def get_clienti_trascurati(df, soglia_warning_giorni=7, soglia_critico_giorni=14):
    oggi = ora_italiana.date()
    clienti_alert = []
    
    for _, row in df.iterrows():
        if row.get('visitare', 'SI') != 'SI':
            continue
        
        ultima = row.get('ultima_visita')
        if pd.isnull(ultima) or (hasattr(ultima, 'year') and ultima.year < 2001):
            clienti_alert.append({
                'nome': row['nome_cliente'],
                'id': row['id'],
                'indirizzo': row.get('indirizzo', ''),
                'giorni_ritardo': 999,
                'livello': 'critico',
                'messaggio': 'Mai visitato'
            })
        else:
            frequenza = int(row.get('frequenza_giorni', 30))
            ultima_date = ultima.date() if hasattr(ultima, 'date') else ultima
            prossima = ultima_date + timedelta(days=frequenza)
            giorni_ritardo = (oggi - prossima).days
            
            if giorni_ritardo > soglia_critico_giorni:
                livello = 'critico'
            elif giorni_ritardo > soglia_warning_giorni:
                livello = 'warning'
            elif giorni_ritardo >= 0:
                livello = 'scaduto'
            else:
                continue
            
            clienti_alert.append({
                'nome': row['nome_cliente'],
                'id': row['id'],
                'indirizzo': row.get('indirizzo', ''),
                'giorni_ritardo': giorni_ritardo,
                'livello': livello,
                'messaggio': f'Scaduto da {giorni_ritardo} giorni' if giorni_ritardo > 0 else 'Scade oggi'
            })
    
    clienti_alert.sort(key=lambda x: x['giorni_ritardo'], reverse=True)
    return clienti_alert

def get_coords(address):
    """Geocodifica indirizzo -> coordinate usando LocationIQ (veloce!)"""
    try:
        url = "https://us1.locationiq.com/v1/search.php"
        params = {
            'key': LOCATIONIQ_KEY,
            'q': f"{address}, Italia",
            'format': 'json',
            'limit': 1
        }
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data:
                return (float(data[0]['lat']), float(data[0]['lon']))
        return None
    except Exception as e:
        return None

def reverse_geocode(lat, lon):
    """Coordinate -> indirizzo usando LocationIQ (veloce!)"""
    try:
        url = "https://us1.locationiq.com/v1/reverse.php"
        params = {
            'key': LOCATIONIQ_KEY,
            'lat': lat,
            'lon': lon,
            'format': 'json',
            'accept-language': 'it'
        }
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            addr = data.get('address', {})
            return {
                'via': f"{addr.get('road', '')} {addr.get('house_number', '')}".strip(),
                'cap': addr.get('postcode', ''),
                'citta': addr.get('city') or addr.get('town') or addr.get('village', ''),
                'provincia': addr.get('county', '') or addr.get('state', ''),
                'indirizzo_completo': data.get('display_name', '')
            }
        return None
    except:
        return None

def batch_geocode(addresses, progress_callback=None):
    """Geocodifica multipla veloce"""
    results = []
    for i, addr in enumerate(addresses):
        coords = get_coords(addr)
        results.append(coords)
        if progress_callback:
            progress_callback(i + 1, len(addresses))
        time_module.sleep(0.2)  # Rate limit LocationIQ free: 2 req/sec
    return results

# --- GPS COMPONENT ---
def render_gps_button(button_id):
    html_code = f"""
    <div id="gps-container-{button_id}" style="width:100%;">
        <button onclick="getLocation_{button_id}()" 
                style="padding:12px 24px; background:#FF4B4B; color:white; border:none; 
                       border-radius:8px; cursor:pointer; font-size:16px; width:100%; 
                       font-weight:600; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            🎯 Usa GPS Attuale
        </button>
        <div id="status-{button_id}" style="margin-top:12px; font-size:14px; padding:8px; 
                                            border-radius:4px; text-align:center;"></div>
    </div>
    
    <script>
    function getLocation_{button_id}() {{
        const status = document.getElementById('status-{button_id}');
        
        if (!navigator.geolocation) {{
            status.innerHTML = '❌ Geolocalizzazione non supportata';
            status.style.backgroundColor = '#ffebee';
            status.style.color = '#c62828';
            return;
        }}
        
        status.innerHTML = '🔄 Acquisizione GPS...';
        status.style.backgroundColor = '#fff3e0';
        status.style.color = '#e65100';
        
        navigator.geolocation.getCurrentPosition(
            function(position) {{
                const lat = position.coords.latitude;
                const lon = position.coords.longitude;
                
                status.innerHTML = '✅ GPS: ' + lat.toFixed(6) + ', ' + lon.toFixed(6);
                status.style.backgroundColor = '#e8f5e9';
                status.style.color = '#2e7d32';
                
                sessionStorage.setItem('gps_data_{button_id}', JSON.stringify({{
                    latitude: lat,
                    longitude: lon
                }}));
            }},
            function(error) {{
                status.innerHTML = '❌ Errore GPS';
                status.style.backgroundColor = '#ffebee';
                status.style.color = '#c62828';
            }},
            {{ enableHighAccuracy: true, timeout: 20000, maximumAge: 0 }}
        );
    }}
    </script>
    """
    return st.components.v1.html(html_code, height=100)

# --- 5. CALCOLO GIRO ---
def calcola_piano_giornaliero(df, giorno_settimana, config, esclusi=[]):
    """Calcola il piano visite per un giorno specifico"""
    if df.empty:
        return []
    
    oggi = ora_italiana.date()
    tappe = []
    
    # Filtra clienti da visitare CON COORDINATE VALIDE
    df_attivi = df[
        (df['visitare'] == 'SI') & 
        (df['latitude'].notna()) & 
        (df['longitude'].notna()) &
        (df['latitude'] != 0) &
        (df['longitude'] != 0)
    ].copy()
    
    if df_attivi.empty:
        return []
    
    # Trova appuntamenti del giorno
    try:
        appuntamenti = df_attivi[df_attivi['appuntamento'].dt.date == oggi].copy()
    except:
        appuntamenti = pd.DataFrame()
    
    # Calcola giorni passati dall'ultima visita
    df_attivi['giorni_passati'] = df_attivi['ultima_visita'].apply(
        lambda x: (oggi - x.date()).days if pd.notnull(x) and hasattr(x, 'date') else 999
    )
    
    # Clienti urgenti (scaduti)
    urgenti = df_attivi[
        (df_attivi['giorni_passati'] >= df_attivi['frequenza_giorni']) &
        (~df_attivi['nome_cliente'].isin(esclusi)) &
        (~df_attivi['nome_cliente'].isin(appuntamenti['nome_cliente'].tolist() if not appuntamenti.empty else []))
    ].copy()
    
    # Aggiungi appuntamenti
    if not appuntamenti.empty:
        for _, row in appuntamenti.iterrows():
            if row['nome_cliente'] not in esclusi:
                tappe.append({
                    'id': row['id'],
                    'nome_cliente': row['nome_cliente'],
                    'latitude': float(row['latitude']),
                    'longitude': float(row['longitude']),
                    'indirizzo': row.get('indirizzo', ''),
                    'cellulare': row.get('cellulare', ''),
                    'ora_arrivo': row['appuntamento'].strftime("%H:%M") if pd.notnull(row['appuntamento']) else "09:00",
                    'tipo_tappa': "📌 APPUNTAMENTO"
                })
    
    # Aggiungi urgenti ordinati per distanza
    start_lat = float(config.get('lat_base', 41.9028))
    start_lon = float(config.get('lon_base', 12.4964))
    pos_corrente = (start_lat, start_lon)
    
    # Converti urgenti in lista di dict con coordinate float valide
    urgenti_list = []
    for _, row in urgenti.iterrows():
        try:
            lat = float(row['latitude'])
            lon = float(row['longitude'])
            if lat != 0 and lon != 0:
                urgenti_list.append({
                    'id': row['id'],
                    'nome_cliente': row['nome_cliente'],
                    'latitude': lat,
                    'longitude': lon,
                    'indirizzo': row.get('indirizzo', ''),
                    'cellulare': row.get('cellulare', ''),
                    'frequenza_giorni': row['frequenza_giorni'],
                    'giorni_passati': row['giorni_passati']
                })
        except:
            continue
    
    ora_corrente = datetime.combine(oggi, time(9, 0))
    durata_visita = config.get('durata_visita', 45)
    
    while urgenti_list and len(tappe) < 15:  # Max 15 visite al giorno
        # Trova il più vicino
        try:
            piu_vicino = min(urgenti_list, key=lambda x: haversine(pos_corrente[0], pos_corrente[1], x['latitude'], x['longitude']))
        except Exception as e:
            break
        
        dist = haversine(pos_corrente[0], pos_corrente[1], piu_vicino['latitude'], piu_vicino['longitude'])
        tempo_viaggio = (dist / 50) * 60  # minuti
        ora_arrivo = ora_corrente + timedelta(minutes=tempo_viaggio)
        
        # Pausa pranzo
        if ora_arrivo.hour >= 13 and ora_arrivo.hour < 14:
            ora_corrente = datetime.combine(oggi, time(14, 0))
            continue
        
        # Fine giornata
        if ora_arrivo.hour >= 18:
            break
        
        tappe.append({
            'id': piu_vicino['id'],
            'nome_cliente': piu_vicino['nome_cliente'],
            'latitude': piu_vicino['latitude'],
            'longitude': piu_vicino['longitude'],
            'indirizzo': piu_vicino.get('indirizzo', ''),
            'cellulare': piu_vicino.get('cellulare', ''),
            'ora_arrivo': ora_arrivo.strftime("%H:%M"),
            'tipo_tappa': "🚗 Giro"
        })
        
        pos_corrente = (piu_vicino['latitude'], piu_vicino['longitude'])
        ora_corrente = ora_arrivo + timedelta(minutes=durata_visita)
        urgenti_list.remove(piu_vicino)
    
    return tappe
    
    return tappe

# --- 6. MAIN APP ---
def main_app():
    # Sidebar con info utente
    with st.sidebar:
        st.markdown(f"### 👤 {st.session_state.user.email}")
        if st.button("🚪 Logout", use_container_width=True):
            logout()
        st.divider()
    
    # Carica dati
    if 'df_clienti' not in st.session_state or st.session_state.get('reload_data', False):
        st.session_state.df_clienti = fetch_clienti()
        st.session_state.reload_data = False
    
    if 'config' not in st.session_state:
        config = fetch_config()
        if config:
            st.session_state.config = config
        else:
            st.session_state.config = {
                'citta_base': 'Roma',
                'lat_base': 41.9028,
                'lon_base': 12.4964,
                'h_inizio': '09:00',
                'h_fine': '18:00',
                'pausa_inizio': '13:00',
                'pausa_fine': '14:00',
                'durata_visita': 45,
                'giorni_lavorativi': [0, 1, 2, 3, 4],
                'attiva_ferie': False,
                'ferie_inizio': None,
                'ferie_fine': None
            }
    
    if 'esclusi_oggi' not in st.session_state:
        st.session_state.esclusi_oggi = []
    if 'visitati_oggi' not in st.session_state:
        st.session_state.visitati_oggi = []
    if 'cliente_selezionato' not in st.session_state:
        st.session_state.cliente_selezionato = None
    
    # Carica visitati oggi dal database
    df = st.session_state.df_clienti
    oggi_str = ora_italiana.strftime('%Y-%m-%d')
    for _, row in df.iterrows():
        if pd.notnull(row.get('ultima_visita')):
            if hasattr(row['ultima_visita'], 'strftime'):
                if row['ultima_visita'].strftime('%Y-%m-%d') == oggi_str:
                    if row['nome_cliente'] not in st.session_state.visitati_oggi:
                        st.session_state.visitati_oggi.append(row['nome_cliente'])
    
    # Menu navigazione
    if 'active_tab' not in st.session_state:
        st.session_state.active_tab = "🚀 Giro Oggi"
    
    nav = st.columns(7)
    menu = ["🚀 Giro Oggi", "📊 Dashboard", "📅 Agenda", "🗺️ Mappa", "👤 Anagrafica", "➕ Nuovo", "⚙️ Config"]
    for i, m in enumerate(menu):
        if nav[i].button(m, key=f"nav_{m}", use_container_width=True, type="primary" if st.session_state.active_tab == m else "secondary"):
            st.session_state.active_tab = m
            st.rerun()
    
    st.divider()
    
    config = st.session_state.config
    giorni_lavorativi = config.get('giorni_lavorativi', [0, 1, 2, 3, 4])
    if isinstance(giorni_lavorativi, str):
        giorni_lavorativi = [int(x) for x in giorni_lavorativi.strip('{}').split(',')]
    
    # --- TAB: GIRO OGGI ---
    if st.session_state.active_tab == "🚀 Giro Oggi":
        col_header, col_refresh = st.columns([5, 1])
        with col_header:
            st.header(f"📍 Giro di Oggi ({ora_italiana.strftime('%d/%m/%Y')})")
        with col_refresh:
            if st.button("🔄", use_container_width=True, help="Aggiorna"):
                st.session_state.reload_data = True
                st.rerun()
        
        idx_g = ora_italiana.weekday()
        giorni_nomi = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
        
        if idx_g in giorni_lavorativi:
            # Alert critici
            critici = [c for c in get_clienti_trascurati(df) if c['livello'] == 'critico']
            if critici:
                st.error(f"🚨 **{len(critici)} clienti critici** da visitare urgentemente!")
            
            # Calcola tappe
            tappe_oggi = calcola_piano_giornaliero(df, idx_g, config, st.session_state.esclusi_oggi)
            
            # Trova visitati fuori giro
            nomi_nel_giro = [t['nome_cliente'] for t in tappe_oggi]
            visitati_fuori_giro = [v for v in st.session_state.visitati_oggi if v not in nomi_nel_giro]
            
            if tappe_oggi or visitati_fuori_giro:
                # Statistiche
                km_tot, tempo_guida, tempo_tot = calcola_km_tempo_giro(
                    tappe_oggi, 
                    config.get('lat_base', 41.9028), 
                    config.get('lon_base', 12.4964),
                    config.get('durata_visita', 45)
                )
                
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("📊 Visite", len(tappe_oggi))
                col2.metric("✅ Fatte", len(st.session_state.visitati_oggi))
                col3.metric("🛣️ Km", f"{km_tot}")
                col4.metric("⏱️ Tempo", f"{tempo_tot//60}h {tempo_tot%60}m")
                
                st.divider()
                
                # Mappa
                if tappe_oggi:
                    st.subheader("🗺️ Percorso")
                    m = folium.Map(location=[config.get('lat_base', 41.9028), config.get('lon_base', 12.4964)], zoom_start=10)
                    
                    # Marker partenza
                    folium.Marker(
                        [config.get('lat_base', 41.9028), config.get('lon_base', 12.4964)],
                        popup="🏠 Partenza",
                        icon=folium.Icon(color="blue", icon="home")
                    ).add_to(m)
                    
                    route = [(config.get('lat_base', 41.9028), config.get('lon_base', 12.4964))]
                    
                    for i, t in enumerate(tappe_oggi, 1):
                        visitato = t['nome_cliente'] in st.session_state.visitati_oggi
                        color = "green" if visitato else ("red" if "APPUNTAMENTO" in t['tipo_tappa'] else "orange")
                        
                        folium.Marker(
                            [t['latitude'], t['longitude']],
                            popup=f"{i}. {t['nome_cliente']}<br>⏰ {t['ora_arrivo']}",
                            icon=folium.Icon(color=color, icon="ok" if visitato else "user")
                        ).add_to(m)
                        route.append((t['latitude'], t['longitude']))
                    
                    folium.PolyLine(route, weight=3, color='#3498db', opacity=0.8).add_to(m)
                    m.fit_bounds(route)
                    st_folium(m, width="100%", height=350, key="map_oggi")
                
                st.divider()
                st.subheader("📋 Tappe")
                
                for i, t in enumerate(tappe_oggi, 1):
                    visitato = t['nome_cliente'] in st.session_state.visitati_oggi
                    
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([3, 2, 1])
                        
                        with c1:
                            if visitato:
                                st.markdown(f"### ✅ {i}. {t['nome_cliente']}")
                            else:
                                st.markdown(f"### {t['tipo_tappa'].split()[0]} {i}. {t['nome_cliente']}")
                                st.caption(f"⏰ {t['ora_arrivo']}")
                            if t.get('indirizzo'):
                                st.caption(f"📍 {t['indirizzo']}")
                        
                        with c2:
                            st.link_button("🚗 Naviga", f"https://www.google.com/maps/dir/?api=1&destination={t['latitude']},{t['longitude']}", use_container_width=True)
                            if t.get('cellulare'):
                                st.link_button(f"📱 Chiama", f"tel:{t['cellulare']}", use_container_width=True)
                        
                        with c3:
                            if st.button("👤", key=f"scheda_{t['id']}", help="Scheda"):
                                st.session_state.cliente_selezionato = t['nome_cliente']
                                st.session_state.active_tab = "👤 Anagrafica"
                                st.rerun()
                
                # Navigazione completa
                if tappe_oggi:
                    st.divider()
                    tappe_rimanenti = [t for t in tappe_oggi if t['nome_cliente'] not in st.session_state.visitati_oggi]
                    if tappe_rimanenti:
                        waypoints = "|".join([f"{t['latitude']},{t['longitude']}" for t in tappe_rimanenti[:-1]])
                        dest = f"{tappe_rimanenti[-1]['latitude']},{tappe_rimanenti[-1]['longitude']}"
                        origin = f"{config.get('lat_base', 41.9028)},{config.get('lon_base', 12.4964)}"
                        url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={dest}&waypoints={waypoints}&travelmode=driving"
                        st.link_button(f"🗺️ NAVIGA ({len(tappe_rimanenti)} tappe)", url, use_container_width=True, type="primary")
                    else:
                        st.success("🎉 Hai completato tutte le visite!")
            else:
                st.info("📭 Nessuna visita pianificata per oggi")
        else:
            st.warning(f"🏖️ Oggi è {giorni_nomi[idx_g]} - non lavorativo")
    
    # --- TAB: DASHBOARD ---
    elif st.session_state.active_tab == "📊 Dashboard":
        st.header("📊 Dashboard")
        
        # Alert
        alert = get_clienti_trascurati(df)
        critici = [c for c in alert if c['livello'] == 'critico']
        warning = [c for c in alert if c['livello'] == 'warning']
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("👥 Totale Clienti", len(df))
        clienti_attivi = len(df[df['visitare'] == 'SI']) if not df.empty and 'visitare' in df.columns else 0
        c2.metric("✅ Attivi", clienti_attivi)
        c3.metric("🔴 Critici", len(critici))
        c4.metric("🟠 Warning", len(warning))
        
        if critici:
            st.divider()
            st.subheader("🚨 Clienti Critici")
            for c in critici[:10]:
                col1, col2 = st.columns([4, 1])
                col1.error(f"**{c['nome']}** - {c['messaggio']}")
                if col2.button("👤", key=f"dash_{c['id']}"):
                    st.session_state.cliente_selezionato = c['nome']
                    st.session_state.active_tab = "👤 Anagrafica"
                    st.rerun()
    
    # --- TAB: AGENDA ---
    elif st.session_state.active_tab == "📅 Agenda":
        st.header("📅 Agenda Settimanale")
        
        # Navigazione settimane
        if 'current_week_index' not in st.session_state:
            st.session_state.current_week_index = 0  # 0 = settimana corrente
        
        col_nav1, col_nav2, col_nav3 = st.columns([1, 3, 1])
        
        with col_nav1:
            if st.button("⬅️ Sett. Prec.", use_container_width=True):
                st.session_state.current_week_index -= 1
                st.rerun()
        
        with col_nav3:
            if st.button("Sett. Succ. ➡️", use_container_width=True):
                st.session_state.current_week_index += 1
                st.rerun()
        
        # Calcola date della settimana selezionata
        oggi = ora_italiana.date()
        lunedi_corrente = oggi - timedelta(days=oggi.weekday())
        lunedi_selezionato = lunedi_corrente + timedelta(weeks=st.session_state.current_week_index)
        domenica_selezionata = lunedi_selezionato + timedelta(days=6)
        
        with col_nav2:
            if st.session_state.current_week_index == 0:
                st.markdown(f"### 📆 Settimana Corrente")
            elif st.session_state.current_week_index > 0:
                st.markdown(f"### 📆 +{st.session_state.current_week_index} Settimana/e")
            else:
                st.markdown(f"### 📆 {st.session_state.current_week_index} Settimana/e")
            st.caption(f"Dal {lunedi_selezionato.strftime('%d/%m/%Y')} al {domenica_selezionata.strftime('%d/%m/%Y')}")
        
        st.divider()
        
        # Giorni lavorativi configurati
        giorni_nomi_full = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
        giorni_attivi = config.get('giorni_lavorativi', [0, 1, 2, 3, 4])
        if isinstance(giorni_attivi, str):
            giorni_attivi = [int(x) for x in giorni_attivi.strip('{}').split(',')]
        
        # Crea colonne per i giorni lavorativi
        if giorni_attivi:
            cols_giorni = st.columns(len(giorni_attivi))
            
            totale_visite_settimana = 0
            
            for col_idx, giorno_idx in enumerate(giorni_attivi):
                data_giorno = lunedi_selezionato + timedelta(days=giorno_idx)
                
                with cols_giorni[col_idx]:
                    st.subheader(f"{giorni_nomi_full[giorno_idx][:3]}")
                    st.caption(f"{data_giorno.strftime('%d/%m')}")
                    
                    # Calcola visite per questo giorno
                    tappe_giorno = []
                    
                    if not df.empty:
                        # Appuntamenti del giorno
                        for _, row in df.iterrows():
                            if pd.notnull(row.get('appuntamento')):
                                if hasattr(row['appuntamento'], 'date'):
                                    if row['appuntamento'].date() == data_giorno:
                                        tappe_giorno.append({
                                            'nome': row['nome_cliente'],
                                            'tipo': '📌',
                                            'ora': row['appuntamento'].strftime('%H:%M')
                                        })
                        
                        # Clienti scaduti (solo per settimana corrente e future)
                        if st.session_state.current_week_index >= 0:
                            for _, row in df.iterrows():
                                if row.get('visitare') == 'SI':
                                    ultima = row.get('ultima_visita')
                                    freq = int(row.get('frequenza_giorni', 30))
                                    
                                    if pd.isnull(ultima) or (hasattr(ultima, 'year') and ultima.year < 2001):
                                        # Mai visitato - aggiungi se non già in lista
                                        if len(tappe_giorno) < 8 and row['nome_cliente'] not in [t['nome'] for t in tappe_giorno]:
                                            tappe_giorno.append({
                                                'nome': row['nome_cliente'],
                                                'tipo': '🚗',
                                                'ora': '--:--'
                                            })
                                    else:
                                        prossima_visita = ultima.date() + timedelta(days=freq) if hasattr(ultima, 'date') else ultima + timedelta(days=freq)
                                        if prossima_visita <= data_giorno:
                                            if len(tappe_giorno) < 8 and row['nome_cliente'] not in [t['nome'] for t in tappe_giorno]:
                                                tappe_giorno.append({
                                                    'nome': row['nome_cliente'],
                                                    'tipo': '🚗',
                                                    'ora': '--:--'
                                                })
                    
                    # Mostra tappe
                    if tappe_giorno:
                        num_app = sum(1 for t in tappe_giorno if t['tipo'] == '📌')
                        num_giro = len(tappe_giorno) - num_app
                        
                        if num_app > 0:
                            st.info(f"📌 {num_app}")
                        if num_giro > 0:
                            st.success(f"🚗 {num_giro}")
                        
                        totale_visite_settimana += len(tappe_giorno)
                        
                        st.divider()
                        
                        for tappa in tappe_giorno[:6]:  # Max 6 per colonna
                            with st.container(border=True):
                                st.caption(f"{tappa['tipo']} {tappa['ora']}")
                                if st.button(tappa['nome'][:15], key=f"ag_{data_giorno}_{tappa['nome']}", use_container_width=True):
                                    st.session_state.cliente_selezionato = tappa['nome']
                                    st.session_state.active_tab = "👤 Anagrafica"
                                    st.rerun()
                        
                        if len(tappe_giorno) > 6:
                            st.caption(f"... +{len(tappe_giorno) - 6} altre")
                    else:
                        st.info("📭 Nessuna visita")
            
            # Statistiche settimana
            st.divider()
            st.subheader("📊 Riepilogo Settimana")
            
            col_stat1, col_stat2, col_stat3 = st.columns(3)
            col_stat1.metric("📊 Visite Totali", totale_visite_settimana)
            col_stat2.metric("📅 Giorni Lavorativi", len(giorni_attivi))
            media = totale_visite_settimana / len(giorni_attivi) if giorni_attivi else 0
            col_stat3.metric("📈 Media/Giorno", f"{media:.1f}")
        else:
            st.warning("⚠️ Nessun giorno lavorativo configurato. Vai su ⚙️ Config per impostare i giorni.")
    
    # --- TAB: MAPPA ---
    elif st.session_state.active_tab == "🗺️ Mappa":
        st.header("🗺️ Mappa Clienti")
        
        if not df.empty:
            # Filtri
            col_filtri1, col_filtri2, col_filtri3 = st.columns(3)
            
            with col_filtri1:
                filtro_stato = st.selectbox("📊 Stato:", ["Tutti", "Solo Attivi", "Solo Inattivi"], key="filtro_stato_mappa")
            
            with col_filtri2:
                usa_posizione = st.checkbox("📍 Filtra per distanza dalla mia posizione", key="usa_pos_mappa")
            
            with col_filtri3:
                if usa_posizione:
                    raggio_km = st.slider("🎯 Raggio (km)", 5, 100, 30, key="raggio_mappa")
            
            # Se usa posizione, mostra input coordinate
            if usa_posizione:
                st.divider()
                col_pos1, col_pos2, col_pos3 = st.columns([2, 2, 1])
                
                # Default: usa punto di partenza
                default_lat = config.get('lat_base', 41.9028)
                default_lon = config.get('lon_base', 12.4964)
                
                with col_pos1:
                    mia_lat = st.number_input("📍 Mia Latitudine", value=float(default_lat), format="%.6f", key="mia_lat_mappa")
                with col_pos2:
                    mia_lon = st.number_input("📍 Mia Longitudine", value=float(default_lon), format="%.6f", key="mia_lon_mappa")
                with col_pos3:
                    st.write("")
                    st.write("")
                    if st.button("🏠 Usa Partenza", key="usa_partenza_mappa"):
                        st.session_state.mia_lat_mappa = default_lat
                        st.session_state.mia_lon_mappa = default_lon
                        st.rerun()
                
                st.caption("💡 Apri Google Maps sul telefono, tieni premuto sulla tua posizione, e copia le coordinate qui")
            
            st.divider()
            
            # Filtra dataframe
            df_filtered = df.copy()
            
            # Filtra per stato
            if filtro_stato == "Solo Attivi":
                df_filtered = df_filtered[df_filtered['visitare'] == 'SI']
            elif filtro_stato == "Solo Inattivi":
                df_filtered = df_filtered[df_filtered['visitare'] != 'SI']
            
            # Filtra solo con coordinate valide
            df_filtered = df_filtered[
                (df_filtered['latitude'].notna()) & 
                (df_filtered['longitude'].notna()) &
                (df_filtered['latitude'] != 0) &
                (df_filtered['longitude'] != 0)
            ]
            
            # Se usa posizione, calcola distanza e filtra
            if usa_posizione and mia_lat != 0 and mia_lon != 0:
                df_filtered['distanza_km'] = df_filtered.apply(
                    lambda row: haversine(mia_lat, mia_lon, row['latitude'], row['longitude']), axis=1
                )
                df_filtered = df_filtered[df_filtered['distanza_km'] <= raggio_km]
                df_filtered = df_filtered.sort_values('distanza_km')
                
                st.success(f"🎯 **{len(df_filtered)} clienti** nel raggio di {raggio_km} km dalla tua posizione")
            
            if not df_filtered.empty:
                # Centro mappa
                if usa_posizione and mia_lat != 0:
                    center_lat, center_lon = mia_lat, mia_lon
                    zoom = 10
                else:
                    center_lat = df_filtered['latitude'].mean()
                    center_lon = df_filtered['longitude'].mean()
                    zoom = 8
                
                m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom)
                
                # Marker posizione utente
                if usa_posizione and mia_lat != 0:
                    folium.Marker(
                        [mia_lat, mia_lon],
                        popup="📍 La mia posizione",
                        icon=folium.Icon(color="blue", icon="user")
                    ).add_to(m)
                    
                    # Cerchio del raggio
                    folium.Circle(
                        [mia_lat, mia_lon],
                        radius=raggio_km * 1000,
                        color='blue',
                        fill=True,
                        fillOpacity=0.1
                    ).add_to(m)
                
                # Marker clienti
                for _, row in df_filtered.iterrows():
                    color = "green" if row['visitare'] == "SI" else "red"
                    
                    popup_text = f"<b>{row['nome_cliente']}</b><br>"
                    if row.get('indirizzo'):
                        popup_text += f"📍 {row['indirizzo']}<br>"
                    if usa_posizione and 'distanza_km' in row:
                        popup_text += f"🚗 {row['distanza_km']:.1f} km"
                    
                    folium.Marker(
                        [row['latitude'], row['longitude']],
                        popup=popup_text,
                        icon=folium.Icon(color=color)
                    ).add_to(m)
                
                st_folium(m, width="100%", height=450, key="mappa_clienti")
                
                # Lista clienti vicini
                if usa_posizione and 'distanza_km' in df_filtered.columns:
                    st.divider()
                    st.subheader(f"📋 Clienti più vicini ({len(df_filtered)})")
                    
                    for _, row in df_filtered.head(10).iterrows():
                        col1, col2, col3 = st.columns([3, 1, 1])
                        col1.write(f"**{row['nome_cliente']}** - {row['distanza_km']:.1f} km")
                        col2.link_button("🚗", f"https://www.google.com/maps/dir/?api=1&destination={row['latitude']},{row['longitude']}", use_container_width=True)
                        if col3.button("👤", key=f"mappa_cliente_{row['id']}"):
                            st.session_state.cliente_selezionato = row['nome_cliente']
                            st.session_state.active_tab = "👤 Anagrafica"
                            st.rerun()
            else:
                st.warning("⚠️ Nessun cliente trovato con i filtri selezionati")
        else:
            st.info("Nessun cliente da mostrare")
    
    # --- TAB: ANAGRAFICA ---
    elif st.session_state.active_tab == "👤 Anagrafica":
        st.header("👤 Anagrafica Cliente")
        
        if not df.empty:
            nomi = [""] + sorted(df['nome_cliente'].tolist())
            idx = nomi.index(st.session_state.cliente_selezionato) if st.session_state.cliente_selezionato in nomi else 0
            scelto = st.selectbox("Seleziona cliente:", nomi, index=idx)
            
            if scelto:
                st.session_state.cliente_selezionato = scelto
                cliente = df[df['nome_cliente'] == scelto].iloc[0]
                
                # Azioni rapide
                ca = st.columns(5)
                if pd.notnull(cliente.get('latitude')) and cliente.get('latitude') != 0:
                    ca[0].link_button("🚗 Naviga", f"https://www.google.com/maps/dir/?api=1&destination={cliente['latitude']},{cliente['longitude']}")
                if cliente.get('cellulare'):
                    ca[1].link_button("📱 Chiama", f"tel:{cliente['cellulare']}")
                if cliente.get('mail'):
                    ca[2].link_button("📧 Email", f"mailto:{cliente['mail']}")
                
                st.divider()
                
                # Sezione GPS - Sono qui dal cliente
                with st.container(border=True):
                    st.subheader("📍 Aggiorna Posizione Cliente")
                    st.caption("Usa questa funzione quando sei fisicamente dal cliente per salvare la posizione esatta")
                    
                    # Input manuale coordinate (nascosto di default)
                    with st.expander("🎯 Inserisci coordinate GPS manualmente"):
                        col_gps1, col_gps2 = st.columns(2)
                        new_lat = col_gps1.number_input("Latitudine", value=0.0, format="%.6f", key="new_lat_input")
                        new_lon = col_gps2.number_input("Longitudine", value=0.0, format="%.6f", key="new_lon_input")
                        
                        if st.button("📍 SALVA QUESTA POSIZIONE", type="primary", use_container_width=True):
                            if new_lat != 0 and new_lon != 0:
                                # Ottieni indirizzo dalle coordinate
                                addr_info = reverse_geocode(new_lat, new_lon)
                                update_data = {
                                    'latitude': new_lat,
                                    'longitude': new_lon
                                }
                                if addr_info:
                                    update_data['indirizzo'] = addr_info['indirizzo_completo']
                                    if addr_info['cap']:
                                        update_data['cap'] = addr_info['cap']
                                    if addr_info['provincia']:
                                        update_data['provincia'] = addr_info['provincia']
                                
                                update_cliente(cliente['id'], update_data)
                                st.session_state.reload_data = True
                                st.success(f"✅ Posizione aggiornata! ({new_lat:.6f}, {new_lon:.6f})")
                                st.rerun()
                            else:
                                st.error("❌ Inserisci coordinate valide")
                    
                    st.info("💡 **Suggerimento:** Apri Google Maps sul telefono, tieni premuto sulla tua posizione, e copia le coordinate")
                
                st.divider()
                
                # Pulsante visita rapida
                with st.container(border=True):
                    st.subheader("🏁 Registra Visita")
                    if st.button("✅ APPENA VISITATO", type="primary", use_container_width=True):
                        st.session_state.show_report = True
                    
                    if st.session_state.get('show_report', False):
                        dv = st.date_input("Data:", value=ora_italiana.date())
                        report = st.text_area("Report:", placeholder="Note sulla visita...")
                        
                        c1, c2 = st.columns(2)
                        if c1.button("💾 Salva", use_container_width=True):
                            nuovo_report = f"[{dv.strftime('%d/%m/%Y')}] {report}"
                            vecchio = str(cliente.get('storico_report', '') or '')
                            storico = nuovo_report + "\n\n" + vecchio if vecchio.strip() else nuovo_report
                            
                            update_cliente(cliente['id'], {
                                'ultima_visita': dv.isoformat(),
                                'storico_report': storico
                            })
                            
                            if scelto not in st.session_state.visitati_oggi:
                                st.session_state.visitati_oggi.append(scelto)
                            
                            st.session_state.show_report = False
                            st.session_state.reload_data = True
                            st.success("✅ Salvato!")
                            st.rerun()
                        
                        if c2.button("❌ Annulla", use_container_width=True):
                            st.session_state.show_report = False
                            st.rerun()
                
                st.divider()
                
                # Form modifica
                with st.form("edit_cliente"):
                    st.subheader("✏️ Modifica Dati")
                    c1, c2 = st.columns(2)
                    
                    nome = c1.text_input("Nome", cliente['nome_cliente'])
                    indirizzo = c1.text_input("Indirizzo", cliente.get('indirizzo', ''))
                    cap = c1.text_input("CAP", cliente.get('cap', ''))
                    provincia = c1.text_input("Provincia", cliente.get('provincia', ''))
                    frequenza = c1.number_input("Frequenza (gg)", value=int(cliente.get('frequenza_giorni', 30)))
                    visitare = c1.selectbox("Attivo?", ["SI", "NO"], index=0 if cliente.get('visitare') == 'SI' else 1)
                    
                    telefono = c2.text_input("Telefono", cliente.get('telefono', ''))
                    cellulare = c2.text_input("Cellulare", cliente.get('cellulare', ''))
                    mail = c2.text_input("Email", cliente.get('mail', ''))
                    contatto = c2.text_input("Referente", cliente.get('contatto', ''))
                    
                    # Coordinate GPS
                    st.divider()
                    st.write("**📍 Coordinate GPS**")
                    coord_c1, coord_c2 = st.columns(2)
                    lat_attuale = cliente.get('latitude') if pd.notnull(cliente.get('latitude')) else 0.0
                    lon_attuale = cliente.get('longitude') if pd.notnull(cliente.get('longitude')) else 0.0
                    latitudine = coord_c1.number_input("Latitudine", value=float(lat_attuale), format="%.6f")
                    longitudine = coord_c2.number_input("Longitudine", value=float(lon_attuale), format="%.6f")
                    
                    if lat_attuale == 0 or lon_attuale == 0:
                        st.warning("⚠️ Coordinate mancanti! Il cliente non apparirà nel giro ottimizzato.")
                    
                    note = st.text_area("Note", cliente.get('note', ''), height=100)
                    storico = st.text_area("Storico Report", cliente.get('storico_report', ''), height=150)
                    
                    col_save1, col_save2 = st.columns(2)
                    
                    if col_save1.form_submit_button("💾 Salva Modifiche", use_container_width=True):
                        update_cliente(cliente['id'], {
                            'nome_cliente': nome,
                            'indirizzo': indirizzo,
                            'cap': cap,
                            'provincia': provincia,
                            'frequenza_giorni': frequenza,
                            'visitare': visitare,
                            'telefono': telefono,
                            'cellulare': cellulare,
                            'mail': mail,
                            'contatto': contatto,
                            'latitude': latitudine,
                            'longitude': longitudine,
                            'note': note,
                            'storico_report': storico
                        })
                        st.session_state.reload_data = True
                        st.success("✅ Salvato!")
                        st.rerun()
                    
                    if col_save2.form_submit_button("🌍 Rigenera Coordinate da Indirizzo", use_container_width=True):
                        if indirizzo:
                            new_coords = get_coords(indirizzo)
                            if new_coords:
                                update_cliente(cliente['id'], {
                                    'latitude': new_coords[0],
                                    'longitude': new_coords[1]
                                })
                                st.session_state.reload_data = True
                                st.success(f"✅ Coordinate aggiornate: {new_coords[0]:.6f}, {new_coords[1]:.6f}")
                                st.rerun()
                            else:
                                st.error("❌ Impossibile trovare le coordinate per questo indirizzo")
                        else:
                            st.error("❌ Inserisci un indirizzo prima")
                
                # Elimina
                with st.expander("🗑️ Elimina Cliente"):
                    st.warning(f"⚠️ Eliminazione di **{scelto}** è DEFINITIVA")
                    if st.checkbox("Confermo"):
                        if st.button("❌ ELIMINA", type="primary"):
                            delete_cliente(cliente['id'])
                            st.session_state.cliente_selezionato = None
                            st.session_state.reload_data = True
                            st.rerun()
        else:
            st.info("Nessun cliente presente")
    
    # --- TAB: NUOVO CLIENTE ---
    elif st.session_state.active_tab == "➕ Nuovo":
        st.header("➕ Nuovo Cliente")
        
        render_gps_button("nuovo_cliente")
        
        st.divider()
        
        with st.form("nuovo_cliente_form"):
            c1, c2 = st.columns(2)
            
            nome = c1.text_input("Nome Cliente *")
            indirizzo = c1.text_input("Indirizzo")
            cap = c1.text_input("CAP")
            citta = c1.text_input("Città *")
            provincia = c1.text_input("Provincia")
            frequenza = c1.number_input("Frequenza visite (gg)", value=30)
            
            telefono = c2.text_input("Telefono")
            cellulare = c2.text_input("Cellulare")
            mail = c2.text_input("Email")
            contatto = c2.text_input("Referente")
            note = c2.text_area("Note")
            
            if st.form_submit_button("✅ Crea Cliente", use_container_width=True, type="primary"):
                if nome and citta:
                    coords = get_coords(f"{indirizzo}, {citta}, {provincia}")
                    if not coords:
                        coords = get_coords(citta)
                    
                    if coords:
                        save_cliente({
                            'nome_cliente': nome,
                            'indirizzo': indirizzo,
                            'cap': cap,
                            'provincia': provincia,
                            'contatto': contatto,
                            'telefono': telefono,
                            'cellulare': cellulare,
                            'mail': mail,
                            'note': note,
                            'frequenza_giorni': frequenza,
                            'latitude': coords[0],
                            'longitude': coords[1],
                            'visitare': 'SI'
                        })
                        st.session_state.reload_data = True
                        st.success(f"✅ Cliente {nome} creato!")
                        st.rerun()
                    else:
                        st.error("❌ Impossibile trovare le coordinate")
                else:
                    st.error("❌ Nome e Città sono obbligatori")
    
    # --- TAB: CONFIGURAZIONE ---
    elif st.session_state.active_tab == "⚙️ Config":
        st.header("⚙️ Configurazione")
        
        st.subheader("📍 Punto di Partenza")
        st.caption("Questo è il punto da cui parti ogni mattina (casa, ufficio, ecc.)")
        
        # Mostra coordinate attuali
        lat_attuale = config.get('lat_base', 41.9028)
        lon_attuale = config.get('lon_base', 12.4964)
        citta_attuale = config.get('citta_base', 'Roma')
        
        st.info(f"📍 **Posizione attuale:** {citta_attuale} ({lat_attuale:.6f}, {lon_attuale:.6f})")
        
        # Opzione 1: Inserisci città
        col_part1, col_part2 = st.columns(2)
        with col_part1:
            citta = st.text_input("🏙️ Cerca per città:", value=citta_attuale, key="citta_partenza")
            if st.button("🔍 Cerca", use_container_width=True):
                if citta:
                    coords = get_coords(citta)
                    if coords:
                        config['citta_base'] = citta
                        config['lat_base'] = coords[0]
                        config['lon_base'] = coords[1]
                        save_config(config)
                        st.session_state.config = config
                        st.success(f"✅ Posizione aggiornata: {coords[0]:.6f}, {coords[1]:.6f}")
                        st.rerun()
                    else:
                        st.error("❌ Città non trovata")
        
        # Opzione 2: Inserisci coordinate manualmente
        with col_part2:
            st.write("**🎯 Oppure inserisci coordinate:**")
            new_lat_base = st.number_input("Latitudine", value=float(lat_attuale), format="%.6f", key="lat_base_input")
            new_lon_base = st.number_input("Longitudine", value=float(lon_attuale), format="%.6f", key="lon_base_input")
            
            if st.button("📍 Salva Coordinate", use_container_width=True):
                if new_lat_base != 0 and new_lon_base != 0:
                    # Ottieni nome città dalle coordinate
                    addr_info = reverse_geocode(new_lat_base, new_lon_base)
                    citta_nome = addr_info['citta'] if addr_info and addr_info.get('citta') else "Posizione GPS"
                    
                    config['citta_base'] = citta_nome
                    config['lat_base'] = new_lat_base
                    config['lon_base'] = new_lon_base
                    save_config(config)
                    st.session_state.config = config
                    st.success(f"✅ Posizione salvata: {citta_nome}")
                    st.rerun()
        
        st.caption("💡 **Suggerimento:** Apri Google Maps, tieni premuto sulla tua posizione, e copia le coordinate")
        
        st.divider()
        st.subheader("📅 Giorni Lavorativi")
        st.caption("Seleziona i giorni in cui effettui le visite")
        
        giorni_nomi = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
        cols = st.columns(7)
        nuovi_giorni = []
        
        for i, g in enumerate(giorni_nomi):
            with cols[i]:
                if st.checkbox(g, value=i in giorni_lavorativi, key=f"giorno_{i}"):
                    nuovi_giorni.append(i)
        
        if nuovi_giorni and nuovi_giorni != giorni_lavorativi:
            config['giorni_lavorativi'] = nuovi_giorni
            save_config(config)
            st.session_state.config = config
        
        # Mostra riepilogo giorni
        giorni_nomi_full = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
        giorni_selezionati = [giorni_nomi_full[i] for i in giorni_lavorativi]
        st.info(f"📅 Giorni attivi: **{', '.join(giorni_selezionati)}**")
        
        st.divider()
        st.subheader("⏰ Orari di Lavoro")
        
        col_orari1, col_orari2 = st.columns(2)
        
        # Funzione helper per convertire orari in vari formati
        def parse_time(val, default='09:00'):
            if val is None:
                return datetime.strptime(default, '%H:%M').time()
            if isinstance(val, time):
                return val
            if hasattr(val, 'time'):  # datetime object
                return val.time()
            try:
                # Prova formato HH:MM:SS
                return datetime.strptime(str(val)[:8], '%H:%M:%S').time()
            except:
                try:
                    # Prova formato HH:MM
                    return datetime.strptime(str(val)[:5], '%H:%M').time()
                except:
                    return datetime.strptime(default, '%H:%M').time()
        
        h_inizio_default = parse_time(config.get('h_inizio'), '09:00')
        h_fine_default = parse_time(config.get('h_fine'), '18:00')
        pausa_inizio_default = parse_time(config.get('pausa_inizio'), '13:00')
        pausa_fine_default = parse_time(config.get('pausa_fine'), '14:00')
        
        with col_orari1:
            h_inizio = st.time_input("🌅 Inizio Lavoro", value=h_inizio_default, key="h_inizio_input")
            pausa_inizio = st.time_input("🍽️ Inizio Pausa", value=pausa_inizio_default, key="pausa_inizio_input")
        
        with col_orari2:
            h_fine = st.time_input("🌆 Fine Lavoro", value=h_fine_default, key="h_fine_input")
            pausa_fine = st.time_input("🍽️ Fine Pausa", value=pausa_fine_default, key="pausa_fine_input")
        
        # Salva orari se cambiati
        if st.button("💾 Salva Orari", key="salva_orari"):
            config['h_inizio'] = h_inizio.strftime('%H:%M')
            config['h_fine'] = h_fine.strftime('%H:%M')
            config['pausa_inizio'] = pausa_inizio.strftime('%H:%M')
            config['pausa_fine'] = pausa_fine.strftime('%H:%M')
            save_config(config)
            st.session_state.config = config
            st.success("✅ Orari salvati!")
        
        st.divider()
        st.subheader("⏱️ Durata Visita")
        
        durata = st.slider("Minuti per visita", 15, 120, config.get('durata_visita', 45))
        if durata != config.get('durata_visita'):
            config['durata_visita'] = durata
            save_config(config)
            st.session_state.config = config
        
        st.divider()
        st.subheader("🏖️ Ferie / Giorni di Chiusura")
        
        attiva_ferie = st.checkbox("Attiva periodo di ferie", value=config.get('attiva_ferie', False), key="attiva_ferie")
        
        if attiva_ferie:
            col_ferie1, col_ferie2 = st.columns(2)
            
            ferie_inizio_default = config.get('ferie_inizio', datetime.now().date())
            ferie_fine_default = config.get('ferie_fine', datetime.now().date() + timedelta(days=7))
            
            if isinstance(ferie_inizio_default, str):
                ferie_inizio_default = datetime.strptime(ferie_inizio_default, '%Y-%m-%d').date()
            if isinstance(ferie_fine_default, str):
                ferie_fine_default = datetime.strptime(ferie_fine_default, '%Y-%m-%d').date()
            
            with col_ferie1:
                ferie_inizio = st.date_input("📅 Data Inizio Ferie", value=ferie_inizio_default, key="ferie_inizio")
            with col_ferie2:
                ferie_fine = st.date_input("📅 Data Fine Ferie", value=ferie_fine_default, key="ferie_fine")
            
            if st.button("💾 Salva Ferie", key="salva_ferie"):
                config['attiva_ferie'] = True
                config['ferie_inizio'] = ferie_inizio.isoformat()
                config['ferie_fine'] = ferie_fine.isoformat()
                save_config(config)
                st.session_state.config = config
                st.success(f"✅ Ferie salvate: {ferie_inizio.strftime('%d/%m/%Y')} - {ferie_fine.strftime('%d/%m/%Y')}")
        else:
            if config.get('attiva_ferie', False):
                config['attiva_ferie'] = False
                save_config(config)
                st.session_state.config = config
        
        st.divider()
        st.subheader("📊 Info Account")
        st.write(f"**Email:** {st.session_state.user.email}")
        st.write(f"**Clienti totali:** {len(df)}")
        if not df.empty and 'visitare' in df.columns:
            st.write(f"**Clienti attivi:** {len(df[df['visitare'] == 'SI'])}")
            # Conta clienti senza coordinate
            senza_coord = df[(df['latitude'].isna()) | (df['longitude'].isna()) | (df['latitude'] == 0) | (df['longitude'] == 0)]
            if len(senza_coord) > 0:
                st.warning(f"⚠️ **{len(senza_coord)} clienti senza coordinate GPS!**")
        else:
            st.write(f"**Clienti attivi:** 0")
        
        st.divider()
        st.subheader("🌍 Rigenera Coordinate GPS")
        st.info("Se le coordinate non sono state importate correttamente, puoi rigenerarle dagli indirizzi.")
        
        if not df.empty:
            # Mostra clienti senza coordinate
            senza_coord = df[(df['latitude'].isna()) | (df['longitude'].isna()) | (df['latitude'] == 0) | (df['longitude'] == 0)]
            
            if len(senza_coord) > 0:
                st.error(f"🚨 **{len(senza_coord)} clienti** non hanno coordinate valide!")
                
                with st.expander(f"👀 Vedi clienti senza coordinate ({len(senza_coord)})"):
                    for _, row in senza_coord.head(20).iterrows():
                        st.write(f"- **{row['nome_cliente']}**: {row.get('indirizzo', 'N/A')}")
                    if len(senza_coord) > 20:
                        st.write(f"... e altri {len(senza_coord) - 20}")
                
                if st.button("🌍 RIGENERA TUTTE LE COORDINATE", type="primary", use_container_width=True):
                    progress = st.progress(0)
                    status = st.empty()
                    
                    successi = 0
                    errori = 0
                    
                    for idx, (_, row) in enumerate(senza_coord.iterrows()):
                        indirizzo = row.get('indirizzo', '')
                        if indirizzo:
                            status.text(f"Geocoding: {row['nome_cliente']}...")
                            coords = get_coords(indirizzo)
                            
                            if coords:
                                # Aggiorna nel database
                                update_cliente(row['id'], {
                                    'latitude': coords[0],
                                    'longitude': coords[1]
                                })
                                successi += 1
                            else:
                                errori += 1
                            
                            # Rate limiting LocationIQ (2 req/sec)
                            time_module.sleep(0.5)
                        else:
                            errori += 1
                        
                        progress.progress((idx + 1) / len(senza_coord))
                    
                    progress.empty()
                    status.empty()
                    
                    st.success(f"✅ Completato! {successi} coordinate rigenerate, {errori} errori")
                    st.session_state.reload_data = True
                    st.rerun()
            else:
                st.success("✅ Tutti i clienti hanno coordinate valide!")
        
        st.divider()
        st.subheader("📥 Importa Clienti da CSV")
        
        st.info("""
        **Formato CSV richiesto:**
        Il file deve avere queste colonne (nell'ordine che preferisci):
        - `nome cliente` (obbligatorio)
        - `indirizzo`, `cap`, `provincia`
        - `latitude`, `longitude` (con virgola o punto)
        - `telefono`, `cellulare`, `mail`
        - `frequenza (giorni)`, `ultima visita`, `visitare`
        - `referente`, `contatto`, `note`, `storico report`
        """)
        
        uploaded_file = st.file_uploader("📂 Carica file CSV", type=['csv'])
        
        if uploaded_file is not None:
            try:
                # Leggi CSV
                df_import = pd.read_csv(uploaded_file)
                
                st.success(f"✅ File caricato! Trovati **{len(df_import)} clienti**")
                
                # Mostra anteprima
                with st.expander("👀 Anteprima dati", expanded=True):
                    st.dataframe(df_import.head(5), use_container_width=True)
                
                # Pulsante importazione
                col_imp1, col_imp2 = st.columns(2)
                
                if col_imp1.button("🚀 IMPORTA TUTTI I CLIENTI", type="primary", use_container_width=True):
                    user_id = get_user_id()
                    
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    successi = 0
                    errori = 0
                    errori_dettagli = []
                    
                    for idx, row in df_import.iterrows():
                        try:
                            # Converti latitude/longitude (gestisce sia virgola che punto)
                            lat = None
                            lon = None
                            if 'latitude' in row and pd.notnull(row['latitude']):
                                lat = float(str(row['latitude']).replace(',', '.'))
                            if 'longitude' in row and pd.notnull(row['longitude']):
                                lon = float(str(row['longitude']).replace(',', '.'))
                            
                            # Converti data ultima visita
                            ultima_visita = None
                            if 'ultima visita' in row and pd.notnull(row['ultima visita']):
                                try:
                                    data_str = str(row['ultima visita']).split(' ')[0]
                                    ultima_visita = datetime.strptime(data_str, '%d/%m/%Y').isoformat()
                                except:
                                    pass
                            
                            # Converti appuntamento
                            appuntamento = None
                            if 'appuntamento' in row and pd.notnull(row['appuntamento']):
                                try:
                                    appuntamento = datetime.strptime(str(row['appuntamento']), '%d/%m/%Y %H:%M').isoformat()
                                except:
                                    try:
                                        appuntamento = datetime.strptime(str(row['appuntamento']), '%d/%m/%Y').isoformat()
                                    except:
                                        pass
                            
                            # Prepara dati cliente
                            cliente = {
                                'user_id': user_id,
                                'nome_cliente': str(row.get('nome cliente', '')) if pd.notnull(row.get('nome cliente')) else '',
                                'indirizzo': str(row.get('indirizzo', '')) if pd.notnull(row.get('indirizzo')) else '',
                                'cap': str(row.get('cap', '')) if pd.notnull(row.get('cap')) else '',
                                'provincia': str(row.get('provincia', '')) if pd.notnull(row.get('provincia')) else '',
                                'latitude': lat,
                                'longitude': lon,
                                'frequenza_giorni': int(row.get('frequenza (giorni)', 30)) if pd.notnull(row.get('frequenza (giorni)')) else 30,
                                'ultima_visita': ultima_visita,
                                'visitare': str(row.get('visitare', 'SI')).upper() if pd.notnull(row.get('visitare')) else 'SI',
                                'storico_report': str(row.get('storico report', '')) if pd.notnull(row.get('storico report')) else '',
                                'telefono': str(row.get('telefono', '')) if pd.notnull(row.get('telefono')) else '',
                                'cellulare': str(row.get('cellulare', '')) if pd.notnull(row.get('cellulare')) else '',
                                'mail': str(row.get('mail', '')) if pd.notnull(row.get('mail')) else '',
                                'contatto': str(row.get('contatto', '')) if pd.notnull(row.get('contatto')) else '',
                                'referente': str(row.get('referente', '')) if pd.notnull(row.get('referente')) else '',
                                'note': str(row.get('note', '')) if pd.notnull(row.get('note')) else '',
                                'appuntamento': appuntamento
                            }
                            
                            # Pulisci valori vuoti e 'nan'
                            cliente_clean = {}
                            for k, v in cliente.items():
                                if v is not None and str(v) != 'nan' and str(v) != '':
                                    cliente_clean[k] = v
                            cliente_clean['user_id'] = user_id
                            
                            # Verifica che ci sia almeno il nome
                            if cliente_clean.get('nome_cliente'):
                                supabase.table('clienti').insert(cliente_clean).execute()
                                successi += 1
                            else:
                                errori += 1
                                errori_dettagli.append(f"Riga {idx+2}: Nome cliente mancante")
                            
                        except Exception as e:
                            errori += 1
                            errori_dettagli.append(f"Riga {idx+2}: {str(e)[:50]}")
                        
                        # Aggiorna progress bar
                        progress = (idx + 1) / len(df_import)
                        progress_bar.progress(progress)
                        status_text.text(f"Importazione: {idx+1}/{len(df_import)} ({successi} ✅ | {errori} ❌)")
                    
                    # Risultato finale
                    progress_bar.empty()
                    status_text.empty()
                    
                    if successi > 0:
                        st.success(f"🎉 **Importazione completata!**")
                        st.write(f"✅ Importati: **{successi}** clienti")
                        if errori > 0:
                            st.write(f"❌ Errori: **{errori}**")
                            with st.expander("Dettagli errori"):
                                for err in errori_dettagli[:20]:
                                    st.write(f"- {err}")
                        
                        # Ricarica dati
                        st.session_state.reload_data = True
                        st.rerun()
                    else:
                        st.error("❌ Nessun cliente importato. Controlla il formato del file.")
                
                if col_imp2.button("❌ Annulla", use_container_width=True):
                    st.rerun()
                    
            except Exception as e:
                st.error(f"❌ Errore lettura file: {str(e)}")
        
        st.divider()
        st.subheader("🗑️ Elimina Tutti i Dati")
        st.warning("⚠️ Questa azione è **IRREVERSIBILE**!")
        
        if st.checkbox("Confermo di voler eliminare TUTTI i miei clienti", key="confirm_delete_all"):
            if st.button("🗑️ ELIMINA TUTTO", type="primary"):
                try:
                    user_id = get_user_id()
                    supabase.table('clienti').delete().eq('user_id', user_id).execute()
                    st.session_state.reload_data = True
                    st.success("✅ Tutti i clienti eliminati")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Errore: {str(e)}")
    
    # Footer
    st.divider()
    st.caption("🚀 **Giro Visite CRM Pro** - Versione SaaS 2.0")

# --- RUN APP ---
init_auth_state()

if st.session_state.user is None:
    login_page()
else:
    main_app()
