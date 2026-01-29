import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from datetime import datetime, timedelta, time
from math import radians, cos, sin, asin, sqrt
from geopy.geocoders import Nominatim
import io
import re
import time as time_module
from supabase import create_client, Client

# --- 1. CONFIGURAZIONE ---
st.set_page_config(page_title="Giro Visite CRM Pro", layout="wide", page_icon="🚀")

# Supabase credentials
SUPABASE_URL = "https://ectezeclocjfbpbxdhyk.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVjdGV6ZWNsb2NqZmJwYnhkaHlrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njk2Mzg4NzcsImV4cCI6MjA4NTIxNDg3N30.k_i6vZBmVXhQs6NFSi_IiH6HSiN7O6tG3WwGViw7PIs"

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
    try:
        geolocator = Nominatim(user_agent="giro_visite_crm_pro", timeout=10)
        location = geolocator.geocode(f"{address}, Italia")
        if location:
            return (location.latitude, location.longitude)
        return None
    except Exception as e:
        return None

def reverse_geocode(lat, lon):
    try:
        geolocator = Nominatim(user_agent="giro_visite_crm_pro", timeout=10)
        location = geolocator.reverse(f"{lat}, {lon}", language='it')
        if location and location.raw.get('address'):
            addr = location.raw['address']
            return {
                'via': f"{addr.get('road', '')} {addr.get('house_number', '')}".strip(),
                'cap': addr.get('postcode', ''),
                'citta': addr.get('city') or addr.get('town') or addr.get('village', ''),
                'provincia': addr.get('state', ''),
                'indirizzo_completo': location.address
            }
        return None
    except:
        return None

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
    
    # Filtra clienti da visitare
    df_attivi = df[df['visitare'] == 'SI'].copy()
    
    # Trova appuntamenti del giorno
    appuntamenti = df_attivi[df_attivi['appuntamento'].dt.date == oggi].copy()
    
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
    for _, row in appuntamenti.iterrows():
        if row['nome_cliente'] not in esclusi:
            tappe.append({
                'id': row['id'],
                'nome_cliente': row['nome_cliente'],
                'latitude': row['latitude'],
                'longitude': row['longitude'],
                'indirizzo': row.get('indirizzo', ''),
                'cellulare': row.get('cellulare', ''),
                'ora_arrivo': row['appuntamento'].strftime("%H:%M") if pd.notnull(row['appuntamento']) else "09:00",
                'tipo_tappa': "📌 APPUNTAMENTO"
            })
    
    # Aggiungi urgenti ordinati per distanza
    start_lat = config.get('lat_base', 41.9028)
    start_lon = config.get('lon_base', 12.4964)
    pos_corrente = (start_lat, start_lon)
    
    urgenti_list = urgenti.to_dict('records')
    ora_corrente = datetime.combine(oggi, time(9, 0))
    durata_visita = config.get('durata_visita', 45)
    
    while urgenti_list and len(tappe) < 15:  # Max 15 visite al giorno
        # Trova il più vicino
        piu_vicino = min(urgenti_list, key=lambda x: haversine(pos_corrente[0], pos_corrente[1], x['latitude'], x['longitude']))
        
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
                'durata_visita': 45,
                'giorni_lavorativi': [0, 1, 2, 3, 4]
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
        c2.metric("✅ Attivi", len(df[df['visitare'] == 'SI']))
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
    
    # --- TAB: MAPPA ---
    elif st.session_state.active_tab == "🗺️ Mappa":
        st.header("🗺️ Mappa Clienti")
        
        if not df.empty:
            m = folium.Map(location=[df['latitude'].mean(), df['longitude'].mean()], zoom_start=8)
            for _, row in df.iterrows():
                color = "green" if row['visitare'] == "SI" else "red"
                folium.Marker(
                    [row['latitude'], row['longitude']],
                    popup=row['nome_cliente'],
                    icon=folium.Icon(color=color)
                ).add_to(m)
            st_folium(m, width="100%", height=500, key="mappa_clienti")
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
                ca = st.columns(4)
                ca[0].link_button("🚗 Naviga", f"https://www.google.com/maps/dir/?api=1&destination={cliente['latitude']},{cliente['longitude']}")
                if cliente.get('cellulare'):
                    ca[1].link_button("📱 Chiama", f"tel:{cliente['cellulare']}")
                if cliente.get('mail'):
                    ca[2].link_button("📧 Email", f"mailto:{cliente['mail']}")
                
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
                    
                    note = st.text_area("Note", cliente.get('note', ''), height=100)
                    storico = st.text_area("Storico Report", cliente.get('storico_report', ''), height=150)
                    
                    if st.form_submit_button("💾 Salva Modifiche", use_container_width=True):
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
                            'note': note,
                            'storico_report': storico
                        })
                        st.session_state.reload_data = True
                        st.success("✅ Salvato!")
                        st.rerun()
                
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
        citta = st.text_input("Città base:", config.get('citta_base', 'Roma'))
        
        if citta != config.get('citta_base'):
            coords = get_coords(citta)
            if coords:
                config['citta_base'] = citta
                config['lat_base'] = coords[0]
                config['lon_base'] = coords[1]
                save_config(config)
                st.session_state.config = config
                st.success("✅ Salvato!")
        
        st.divider()
        st.subheader("📅 Giorni Lavorativi")
        
        giorni_nomi = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
        cols = st.columns(7)
        nuovi_giorni = []
        
        for i, g in enumerate(giorni_nomi):
            with cols[i]:
                if st.checkbox(g, value=i in giorni_lavorativi, key=f"giorno_{i}"):
                    nuovi_giorni.append(i)
        
        if nuovi_giorni != giorni_lavorativi:
            config['giorni_lavorativi'] = nuovi_giorni
            save_config(config)
            st.session_state.config = config
        
        st.divider()
        st.subheader("⏰ Orari")
        
        durata = st.slider("Durata visita (min)", 15, 120, config.get('durata_visita', 45))
        if durata != config.get('durata_visita'):
            config['durata_visita'] = durata
            save_config(config)
            st.session_state.config = config
        
        st.divider()
        st.subheader("📊 Info Account")
        st.write(f"**Email:** {st.session_state.user.email}")
        st.write(f"**Clienti totali:** {len(df)}")
        st.write(f"**Clienti attivi:** {len(df[df['visitare'] == 'SI'])}")
    
    # Footer
    st.divider()
    st.caption("🚀 **Giro Visite CRM Pro** - Versione SaaS 1.0")

# --- RUN APP ---
init_auth_state()

if st.session_state.user is None:
    login_page()
else:
    main_app()
