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

# ============================================
# 🔐 CREDENZIALI DA STREAMLIT SECRETS
# ============================================
# Le chiavi sono ora protette in Streamlit Cloud → Settings → Secrets
# Questo rende il codice sicuro anche se il repo è pubblico!

SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")
LOCATIONIQ_KEY = st.secrets.get("LOCATIONIQ_KEY", "")
ADMIN_EMAIL = st.secrets.get("ADMIN_EMAIL", "")

# Verifica che i secrets siano configurati
if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("⚠️ **Configurazione mancante!** Vai su Streamlit Cloud → Settings → Secrets e aggiungi le credenziali.")
    st.stop()

# Durata trial in giorni
TRIAL_DAYS = 14

@st.cache_resource
def get_supabase_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = get_supabase_client()

# --- 2. GESTIONE ABBONAMENTI/UTENTI ---
def get_user_subscription(user_id, email=None):
    """Ottiene lo stato abbonamento di un utente"""
    try:
        response = supabase.table('user_subscriptions').select('*').eq('user_id', user_id).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        # Tabella potrebbe non esistere ancora
        return None

def create_user_subscription(user_id, email, is_trial=True):
    """Crea un nuovo record abbonamento per un utente"""
    try:
        today = datetime.now().date()
        
        # Controlla se è l'admin
        is_admin = email.lower() == ADMIN_EMAIL.lower()
        
        data = {
            'user_id': user_id,
            'email': email,
            'status': 'active' if is_admin else ('trial' if is_trial else 'pending'),
            'is_admin': is_admin,
            'created_at': datetime.now().isoformat()
        }
        
        if is_trial and not is_admin:
            data['trial_start'] = today.isoformat()
            data['trial_end'] = (today + timedelta(days=TRIAL_DAYS)).isoformat()
        
        if is_admin:
            data['subscription_start'] = today.isoformat()
        
        response = supabase.table('user_subscriptions').insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        st.error(f"Errore creazione abbonamento: {str(e)}")
        return None

def update_user_subscription(user_id, update_data):
    """Aggiorna lo stato abbonamento di un utente"""
    try:
        response = supabase.table('user_subscriptions').update(update_data).eq('user_id', user_id).execute()
        return True
    except Exception as e:
        return False

def check_subscription_status(subscription):
    """Verifica lo stato dell'abbonamento e restituisce (can_access, message)"""
    if not subscription:
        return False, "Account non trovato. Contatta l'amministratore."
    
    status = subscription.get('status', 'pending')
    
    if status == 'blocked':
        reason = subscription.get('blocked_reason', 'Non specificato')
        return False, f"❌ Account bloccato. Motivo: {reason}"
    
    if status == 'pending':
        return False, "⏳ Account in attesa di approvazione. Riceverai una notifica quando sarà attivo."
    
    if status == 'expired':
        return False, "⚠️ Abbonamento scaduto. Contatta l'amministratore per rinnovare."
    
    if status == 'trial':
        trial_end = subscription.get('trial_end')
        if trial_end:
            trial_end_date = datetime.strptime(trial_end, '%Y-%m-%d').date() if isinstance(trial_end, str) else trial_end
            if datetime.now().date() > trial_end_date:
                # Trial scaduto
                update_user_subscription(subscription['user_id'], {'status': 'expired'})
                return False, "⚠️ Periodo di prova terminato. Contatta l'amministratore per attivare l'abbonamento."
            days_left = (trial_end_date - datetime.now().date()).days
            return True, f"🎁 Prova gratuita: {days_left} giorni rimanenti"
    
    if status == 'active':
        # Controlla scadenza abbonamento
        sub_end = subscription.get('subscription_end')
        if sub_end:
            sub_end_date = datetime.strptime(sub_end, '%Y-%m-%d').date() if isinstance(sub_end, str) else sub_end
            if datetime.now().date() > sub_end_date:
                update_user_subscription(subscription['user_id'], {'status': 'expired'})
                return False, "⚠️ Abbonamento scaduto. Contatta l'amministratore per rinnovare."
        return True, "✅ Account attivo"
    
    return False, "Stato account non riconosciuto."

def is_admin(user_id):
    """Verifica se l'utente è admin"""
    try:
        sub = get_user_subscription(user_id)
        return sub.get('is_admin', False) if sub else False
    except:
        return False

def get_all_users():
    """Ottiene tutti gli utenti (solo per admin)"""
    try:
        response = supabase.table('user_subscriptions').select('*').order('created_at', desc=True).execute()
        return response.data if response.data else []
    except Exception as e:
        return []

# --- 3. AUTENTICAZIONE ---
def init_auth_state():
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'session' not in st.session_state:
        st.session_state.session = None
    if 'subscription' not in st.session_state:
        st.session_state.subscription = None

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
                        
                        user = response.user
                        
                        # Verifica/crea abbonamento
                        subscription = get_user_subscription(user.id, email)
                        if not subscription:
                            # Prima volta - crea record (l'admin viene riconosciuto automaticamente)
                            subscription = create_user_subscription(user.id, email, is_trial=True)
                        
                        # Verifica stato abbonamento
                        can_access, message = check_subscription_status(subscription)
                        
                        if can_access:
                            st.session_state.user = user
                            st.session_state.session = response.session
                            st.session_state.subscription = subscription
                            st.success(f"✅ Accesso effettuato! {message}")
                            time_module.sleep(1)
                            st.rerun()
                        else:
                            # Logout forzato
                            supabase.auth.sign_out()
                            st.error(message)
                            
                    except Exception as e:
                        st.error(f"❌ Errore: {str(e)}")
                else:
                    st.warning("⚠️ Inserisci email e password")
    
    with tab_register:
        st.info(f"🎁 **Registrati per una prova gratuita di {TRIAL_DAYS} giorni!**")
        
        with st.form("register_form"):
            new_email = st.text_input("📧 Email")
            new_password = st.text_input("🔑 Password", type="password")
            confirm_password = st.text_input("🔑 Conferma Password", type="password")
            nome_azienda = st.text_input("🏢 Nome Azienda (opzionale)")
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
                            
                            if response.user:
                                # Crea abbonamento trial
                                create_user_subscription(
                                    response.user.id, 
                                    new_email, 
                                    is_trial=True
                                )
                                
                                st.success(f"""
                                ✅ **Registrazione completata!**
                                
                                📧 Controlla la tua email per confermare l'account.
                                
                                🎁 Hai **{TRIAL_DAYS} giorni di prova gratuita** a partire dal primo accesso!
                                """)
                            else:
                                st.success("✅ Controlla la tua email per confermare l'account.")
                                
                        except Exception as e:
                            st.error(f"❌ Errore: {str(e)}")
                else:
                    st.warning("⚠️ Compila tutti i campi obbligatori")
    
    st.divider()
    st.caption("© 2025 Giro Visite CRM Pro - Versione SaaS")

def logout():
    try:
        supabase.auth.sign_out()
    except:
        pass
    st.session_state.user = None
    st.session_state.session = None
    st.session_state.subscription = None
    st.session_state.clear()
    st.rerun()

# --- 4. PANNELLO ADMIN ---
def admin_panel():
    """Pannello di amministrazione per gestire gli utenti"""
    st.header("🔐 Pannello Amministratore")
    
    # Verifica admin
    if not is_admin(st.session_state.user.id):
        st.error("❌ Accesso non autorizzato")
        return
    
    # Statistiche
    users = get_all_users()
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    total = len(users)
    active = len([u for u in users if u['status'] == 'active'])
    trial = len([u for u in users if u['status'] == 'trial'])
    pending = len([u for u in users if u['status'] == 'pending'])
    blocked = len([u for u in users if u['status'] == 'blocked'])
    
    col1.metric("👥 Totale Utenti", total)
    col2.metric("✅ Attivi", active)
    col3.metric("🎁 In Prova", trial)
    col4.metric("⏳ In Attesa", pending)
    col5.metric("🚫 Bloccati", blocked)
    
    st.divider()
    
    # Filtri
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        filtro_stato = st.selectbox(
            "Filtra per stato:",
            ["Tutti", "active", "trial", "pending", "blocked", "expired"]
        )
    with col_f2:
        cerca_email = st.text_input("🔍 Cerca per email:")
    
    # Filtra utenti
    users_filtrati = users
    if filtro_stato != "Tutti":
        users_filtrati = [u for u in users_filtrati if u['status'] == filtro_stato]
    if cerca_email:
        users_filtrati = [u for u in users_filtrati if cerca_email.lower() in u['email'].lower()]
    
    st.subheader(f"📋 Utenti ({len(users_filtrati)})")
    
    # Lista utenti
    for user in users_filtrati:
        with st.container(border=True):
            col1, col2, col3 = st.columns([3, 2, 2])
            
            with col1:
                # Badge admin
                admin_badge = "👑 " if user.get('is_admin') else ""
                st.markdown(f"### {admin_badge}{user['email']}")
                
                # Info
                created = user.get('created_at', '')[:10] if user.get('created_at') else 'N/D'
                st.caption(f"📅 Registrato: {created}")
                
                if user.get('notes'):
                    st.caption(f"📝 {user['notes']}")
            
            with col2:
                status = user['status']
                status_colors = {
                    'active': '🟢 Attivo',
                    'trial': '🎁 In Prova',
                    'pending': '⏳ In Attesa',
                    'blocked': '🚫 Bloccato',
                    'expired': '⚠️ Scaduto'
                }
                st.markdown(f"**{status_colors.get(status, status)}**")
                
                if status == 'trial' and user.get('trial_end'):
                    trial_end = user['trial_end']
                    if isinstance(trial_end, str):
                        trial_end = datetime.strptime(trial_end, '%Y-%m-%d').date()
                    days_left = (trial_end - datetime.now().date()).days
                    st.caption(f"⏱️ Scade tra {days_left} giorni")
                
                if status == 'active' and user.get('subscription_end'):
                    st.caption(f"📅 Scade: {user['subscription_end']}")
            
            with col3:
                # Non mostrare azioni per se stesso o altri admin
                if user['user_id'] != st.session_state.user.id and not user.get('is_admin'):
                    
                    # Azioni basate sullo stato
                    if status in ['pending', 'expired', 'blocked']:
                        # Attiva con trial
                        if st.button("🎁 Attiva Trial", key=f"trial_{user['user_id']}", use_container_width=True):
                            today = datetime.now().date()
                            update_user_subscription(user['user_id'], {
                                'status': 'trial',
                                'trial_start': today.isoformat(),
                                'trial_end': (today + timedelta(days=TRIAL_DAYS)).isoformat(),
                                'blocked_reason': None
                            })
                            st.success("✅ Trial attivato!")
                            st.rerun()
                        
                        # Attiva abbonamento
                        if st.button("✅ Attiva Abbonamento", key=f"active_{user['user_id']}", use_container_width=True):
                            today = datetime.now().date()
                            update_user_subscription(user['user_id'], {
                                'status': 'active',
                                'subscription_start': today.isoformat(),
                                'subscription_end': (today + timedelta(days=365)).isoformat(),
                                'blocked_reason': None
                            })
                            st.success("✅ Abbonamento attivato (1 anno)!")
                            st.rerun()
                    
                    if status in ['active', 'trial']:
                        # Blocca
                        if st.button("🚫 Blocca", key=f"block_{user['user_id']}", use_container_width=True):
                            update_user_subscription(user['user_id'], {
                                'status': 'blocked',
                                'blocked_reason': 'Bloccato da amministratore'
                            })
                            st.warning("🚫 Utente bloccato")
                            st.rerun()
                    
                    if status == 'blocked':
                        # Sblocca
                        if st.button("🔓 Sblocca", key=f"unblock_{user['user_id']}", use_container_width=True):
                            update_user_subscription(user['user_id'], {
                                'status': 'pending',
                                'blocked_reason': None
                            })
                            st.success("✅ Utente sbloccato (in attesa)")
                            st.rerun()
    
    # Sezione impostazioni
    st.divider()
    st.subheader("⚙️ Impostazioni Globali")
    
    with st.expander("📧 Notifiche Email (Coming Soon)"):
        st.info("Le notifiche email saranno disponibili in una futura versione.")
    
    with st.expander("📊 Esporta Dati Utenti"):
        if st.button("📥 Esporta CSV"):
            df_users = pd.DataFrame(users)
            csv = df_users.to_csv(index=False)
            st.download_button(
                "💾 Scarica CSV",
                csv,
                "utenti_export.csv",
                "text/csv"
            )

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
            # Default per stato_cliente se non esiste
            if 'stato_cliente' not in df.columns:
                df['stato_cliente'] = 'CLIENTE ATTIVO'
            else:
                df['stato_cliente'] = df['stato_cliente'].fillna('CLIENTE ATTIVO')
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

# --- 5. CALCOLO GIRO OTTIMIZZATO ---
def calcola_agenda_settimanale(df, config, esclusi=[], settimana_offset=0):
    """
    Calcola l'agenda ottimizzata per un'intera settimana.
    DISTRIBUISCE i clienti urgenti su tutti i giorni lavorativi.
    Per ogni giorno ottimizza il percorso con Nearest Neighbor.
    Considera: orari lavoro, pausa pranzo, tempo viaggio, ritorno a casa, FERIE.
    """
    if df.empty:
        return {}
    
    # Parametri configurazione
    start_lat = float(config.get('lat_base', 41.9028))
    start_lon = float(config.get('lon_base', 12.4964))
    durata_visita = int(config.get('durata_visita', 45))
    giorni_lavorativi = config.get('giorni_lavorativi', [0, 1, 2, 3, 4])
    
    if isinstance(giorni_lavorativi, str):
        giorni_lavorativi = [int(x) for x in giorni_lavorativi.strip('{}').split(',')]
    
    # Gestione FERIE
    attiva_ferie = config.get('attiva_ferie', False)
    ferie_inizio = None
    ferie_fine = None
    
    if attiva_ferie:
        fi = config.get('ferie_inizio')
        ff = config.get('ferie_fine')
        
        # Converti date ferie
        if fi:
            if isinstance(fi, str):
                try:
                    ferie_inizio = datetime.strptime(fi[:10], '%Y-%m-%d').date()
                except:
                    pass
            elif hasattr(fi, 'date'):
                ferie_inizio = fi.date()
            elif hasattr(fi, 'year'):
                ferie_inizio = fi
        
        if ff:
            if isinstance(ff, str):
                try:
                    ferie_fine = datetime.strptime(ff[:10], '%Y-%m-%d').date()
                except:
                    pass
            elif hasattr(ff, 'date'):
                ferie_fine = ff.date()
            elif hasattr(ff, 'year'):
                ferie_fine = ff
    
    def is_giorno_ferie(data):
        """Verifica se una data cade nel periodo ferie"""
        if not attiva_ferie or not ferie_inizio or not ferie_fine:
            return False
        return ferie_inizio <= data <= ferie_fine
    
    # Orari lavoro
    def parse_time_config(val, default):
        if val is None:
            return default
        if isinstance(val, str):
            try:
                return datetime.strptime(str(val)[:5], '%H:%M').time()
            except:
                return default
        if hasattr(val, 'hour'):
            return val
        return default
    
    h_inizio = parse_time_config(config.get('h_inizio'), time(9, 0))
    h_fine = parse_time_config(config.get('h_fine'), time(18, 0))
    pausa_inizio = parse_time_config(config.get('pausa_inizio'), time(13, 0))
    pausa_fine = parse_time_config(config.get('pausa_fine'), time(14, 0))
    
    # Calcola date della settimana
    oggi = ora_italiana.date()
    lunedi_corrente = oggi - timedelta(days=oggi.weekday())
    lunedi_settimana = lunedi_corrente + timedelta(weeks=settimana_offset)
    
    # Inizializza agenda
    agenda = {g: [] for g in range(7)}
    
    # Filtra clienti con coordinate valide e attivi
    df_validi = df[
        (df['visitare'] == 'SI') & 
        (df['latitude'].notna()) & 
        (df['longitude'].notna()) &
        (df['latitude'] != 0) &
        (df['longitude'] != 0) &
        (~df['nome_cliente'].isin(esclusi))
    ].copy()
    
    if df_validi.empty:
        return agenda
    
    # Converti coordinate a float
    df_validi['latitude'] = df_validi['latitude'].astype(float)
    df_validi['longitude'] = df_validi['longitude'].astype(float)
    
    # Calcola priorità (giorni di ritardo dalla frequenza)
    def calcola_giorni_ritardo(row):
        ultima = row.get('ultima_visita')
        freq = int(row.get('frequenza_giorni', 30))
        
        if pd.isnull(ultima) or (hasattr(ultima, 'year') and ultima.year < 2001):
            return 999  # Mai visitato
        
        ultima_date = ultima.date() if hasattr(ultima, 'date') else ultima
        prossima = ultima_date + timedelta(days=freq)
        return (oggi - prossima).days
    
    df_validi['ritardo'] = df_validi.apply(calcola_giorni_ritardo, axis=1)
    
    # Prendi TUTTI i clienti urgenti (ritardo >= 0, cioè scaduti)
    urgenti = df_validi[df_validi['ritardo'] >= 0].copy()
    
    # Ordina per ritardo (più scaduti prima)
    urgenti = urgenti.sort_values('ritardo', ascending=False)
    
    # Converti in lista di dizionari
    clienti_urgenti = []
    for _, row in urgenti.iterrows():
        clienti_urgenti.append({
            'id': row['id'],
            'nome_cliente': row['nome_cliente'],
            'latitude': row['latitude'],
            'longitude': row['longitude'],
            'indirizzo': row.get('indirizzo', ''),
            'cellulare': str(row.get('cellulare', '')),
            'ritardo': row['ritardo'],
            'frequenza': int(row.get('frequenza_giorni', 30))
        })
    
    # Filtra solo giorni lavorativi futuri (o oggi) ESCLUDENDO FERIE
    giorni_disponibili = []
    for giorno_idx in giorni_lavorativi:
        data_giorno = lunedi_settimana + timedelta(days=giorno_idx)
        # Escludi giorni passati (tranne oggi) e giorni di ferie
        if (settimana_offset > 0 or data_giorno >= oggi) and not is_giorno_ferie(data_giorno):
            giorni_disponibili.append(giorno_idx)
    
    if not giorni_disponibili or not clienti_urgenti:
        return agenda
    
    # ========================================
    # DISTRIBUZIONE CLIENTI SUI GIORNI
    # ========================================
    
    # Per ogni giorno, calcola quante visite possiamo fare
    # (basato su ore disponibili e durata visita media + viaggio)
    ore_lavoro_giorno = (datetime.combine(oggi, h_fine) - datetime.combine(oggi, h_inizio)).seconds / 3600
    ore_pausa = (datetime.combine(oggi, pausa_fine) - datetime.combine(oggi, pausa_inizio)).seconds / 3600
    ore_effettive = ore_lavoro_giorno - ore_pausa
    
    # Stima: visita + viaggio medio = durata_visita + 20 min
    tempo_medio_per_visita = (durata_visita + 20) / 60  # in ore
    max_visite_per_giorno = int(ore_effettive / tempo_medio_per_visita)
    max_visite_per_giorno = min(max_visite_per_giorno, 12)  # Cap a 12
    
    # Clienti ancora da assegnare
    clienti_da_assegnare = clienti_urgenti.copy()
    
    # Per ogni giorno disponibile
    for giorno_idx in giorni_disponibili:
        if not clienti_da_assegnare:
            break
            
        data_giorno = lunedi_settimana + timedelta(days=giorno_idx)
        
        # Prima: prendi gli APPUNTAMENTI del giorno
        tappe_giorno = []
        try:
            for _, row in df_validi.iterrows():
                if pd.notnull(row.get('appuntamento')):
                    app_date = row['appuntamento'].date() if hasattr(row['appuntamento'], 'date') else None
                    if app_date == data_giorno:
                        tappe_giorno.append({
                            'id': row['id'],
                            'nome_cliente': row['nome_cliente'],
                            'latitude': float(row['latitude']),
                            'longitude': float(row['longitude']),
                            'indirizzo': row.get('indirizzo', ''),
                            'cellulare': str(row.get('cellulare', '')),
                            'ora_arrivo': row['appuntamento'].strftime('%H:%M'),
                            'tipo_tappa': '📌 APPUNTAMENTO',
                            'distanza_km': 0
                        })
                        # Rimuovi dai clienti da assegnare
                        clienti_da_assegnare = [c for c in clienti_da_assegnare if c['nome_cliente'] != row['nome_cliente']]
        except:
            pass
        
        # Slot rimanenti per visite normali
        slot_disponibili = max_visite_per_giorno - len(tappe_giorno)
        
        if slot_disponibili <= 0 or not clienti_da_assegnare:
            agenda[giorno_idx] = tappe_giorno
            continue
        
        # ========================================
        # ALGORITMO OTTIMIZZATO: Direzione + 2-opt
        # ========================================
        
        import math
        
        def calcola_angolo(lat1, lon1, lat2, lon2):
            """Calcola l'angolo (bearing) tra due punti in gradi (0-360)"""
            lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
            diff_lon = math.radians(lon2 - lon1)
            x = math.sin(diff_lon) * math.cos(lat2_r)
            y = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(diff_lon)
            angolo = math.atan2(x, y)
            return (math.degrees(angolo) + 360) % 360
        
        def differenza_angolare(angolo1, angolo2):
            """Differenza minima tra due angoli (0-180)"""
            diff = abs(angolo1 - angolo2) % 360
            return min(diff, 360 - diff)
        
        def calcola_km_totale(percorso, start_lat, start_lon):
            """Calcola km totali di un percorso"""
            if not percorso:
                return 0
            km = haversine(start_lat, start_lon, percorso[0]['latitude'], percorso[0]['longitude'])
            for i in range(len(percorso) - 1):
                km += haversine(percorso[i]['latitude'], percorso[i]['longitude'],
                               percorso[i+1]['latitude'], percorso[i+1]['longitude'])
            km += haversine(percorso[-1]['latitude'], percorso[-1]['longitude'], start_lat, start_lon)
            return km
        
        def ottimizza_2opt(percorso, start_lat, start_lon):
            """Migliora il percorso scambiando segmenti (2-opt)"""
            if len(percorso) < 3:
                return percorso
            
            migliorato = True
            while migliorato:
                migliorato = False
                km_attuale = calcola_km_totale(percorso, start_lat, start_lon)
                
                for i in range(len(percorso) - 1):
                    for j in range(i + 2, len(percorso)):
                        # Prova a invertire il segmento tra i e j
                        nuovo_percorso = percorso[:i+1] + percorso[i+1:j+1][::-1] + percorso[j+1:]
                        km_nuovo = calcola_km_totale(nuovo_percorso, start_lat, start_lon)
                        
                        if km_nuovo < km_attuale - 0.1:  # Migliora di almeno 100m
                            percorso = nuovo_percorso
                            migliorato = True
                            break
                    if migliorato:
                        break
            
            return percorso
        
        pos_corrente = (start_lat, start_lon)
        direzione_corrente = None  # Non abbiamo ancora una direzione
        ora_corrente = datetime.combine(data_giorno, h_inizio)
        ora_fine_lavoro = datetime.combine(data_giorno, h_fine)
        ora_pausa_inizio = datetime.combine(data_giorno, pausa_inizio)
        ora_pausa_fine = datetime.combine(data_giorno, pausa_fine)
        
        clienti_per_oggi = []
        visite_aggiunte = 0
        
        # FASE 1: Costruisci percorso con direzione privilegiata
        while clienti_da_assegnare and visite_aggiunte < slot_disponibili:
            migliore = None
            score_min = float('inf')
            angolo_migliore = None
            dist_migliore = 0
            
            for c in clienti_da_assegnare:
                distanza = haversine(pos_corrente[0], pos_corrente[1], c['latitude'], c['longitude'])
                
                # Calcola l'angolo verso questo cliente
                if distanza > 0.1:  # Evita divisione per zero
                    angolo_cliente = calcola_angolo(pos_corrente[0], pos_corrente[1], c['latitude'], c['longitude'])
                else:
                    angolo_cliente = direzione_corrente if direzione_corrente else 0
                
                # Penalità se dobbiamo tornare indietro
                if direzione_corrente is not None:
                    deviazione = differenza_angolare(direzione_corrente, angolo_cliente)
                    # Penalità: 0 se dritto, 1 se torno completamente indietro (180°)
                    penalita = deviazione / 180.0
                else:
                    penalita = 0
                
                # BONUS per clienti con alto ritardo (urgenti)
                urgenza_bonus = min(c['ritardo'] / 100, 0.3) if c['ritardo'] > 0 else 0
                
                # Score finale: distanza * (1 + penalità * peso) - bonus urgenza
                # peso = 0.6 = tornare indietro costa come fare 60% km in più
                score = distanza * (1 + penalita * 0.6) - (urgenza_bonus * distanza)
                
                if score < score_min:
                    score_min = score
                    migliore = c
                    angolo_migliore = angolo_cliente
                    dist_migliore = distanza
            
            if not migliore:
                break
            
            # Verifica tempo
            tempo_viaggio = (dist_migliore / 50) * 60
            ora_arrivo = ora_corrente + timedelta(minutes=tempo_viaggio)
            
            if ora_arrivo.time() >= pausa_inizio and ora_arrivo.time() < pausa_fine:
                ora_corrente = datetime.combine(data_giorno, pausa_fine)
                ora_arrivo = ora_corrente + timedelta(minutes=tempo_viaggio)
            
            ora_fine_visita = ora_arrivo + timedelta(minutes=durata_visita)
            
            dist_ritorno = haversine(migliore['latitude'], migliore['longitude'], start_lat, start_lon)
            tempo_ritorno = (dist_ritorno / 50) * 60
            ora_rientro = ora_fine_visita + timedelta(minutes=tempo_ritorno)
            
            if ora_rientro.time() > h_fine:
                break
            
            # Aggiungi cliente alla lista
            clienti_per_oggi.append({
                'id': migliore['id'],
                'nome_cliente': migliore['nome_cliente'],
                'latitude': migliore['latitude'],
                'longitude': migliore['longitude'],
                'indirizzo': migliore.get('indirizzo', ''),
                'cellulare': migliore.get('cellulare', ''),
                'ritardo': migliore['ritardo']
            })
            
            # Aggiorna stato
            clienti_da_assegnare.remove(migliore)
            pos_corrente = (migliore['latitude'], migliore['longitude'])
            direzione_corrente = angolo_migliore
            ora_corrente = ora_fine_visita
            visite_aggiunte += 1
        
        # FASE 2: Ottimizza con 2-opt
        if len(clienti_per_oggi) >= 3:
            clienti_per_oggi = ottimizza_2opt(clienti_per_oggi, start_lat, start_lon)
        
        # FASE 3: Ricalcola orari e distanze per il percorso ottimizzato
        pos_corrente = (start_lat, start_lon)
        ora_corrente = datetime.combine(data_giorno, h_inizio)
        
        for cliente in clienti_per_oggi:
            dist = haversine(pos_corrente[0], pos_corrente[1], cliente['latitude'], cliente['longitude'])
            tempo_viaggio = (dist / 50) * 60
            ora_arrivo = ora_corrente + timedelta(minutes=tempo_viaggio)
            
            if ora_arrivo.time() >= pausa_inizio and ora_arrivo.time() < pausa_fine:
                ora_corrente = datetime.combine(data_giorno, pausa_fine)
                ora_arrivo = ora_corrente + timedelta(minutes=tempo_viaggio)
            
            tappe_giorno.append({
                'id': cliente['id'],
                'nome_cliente': cliente['nome_cliente'],
                'latitude': cliente['latitude'],
                'longitude': cliente['longitude'],
                'indirizzo': cliente.get('indirizzo', ''),
                'cellulare': cliente.get('cellulare', ''),
                'ora_arrivo': ora_arrivo.strftime('%H:%M'),
                'tipo_tappa': '🚗 Giro',
                'distanza_km': round(dist, 1),
                'ritardo': cliente.get('ritardo', 0)
            })
            
            pos_corrente = (cliente['latitude'], cliente['longitude'])
            ora_corrente = ora_arrivo + timedelta(minutes=durata_visita)
        
        agenda[giorno_idx] = tappe_giorno
    
    return agenda

def calcola_piano_giornaliero(df, giorno_settimana, config, esclusi=[]):
    """Restituisce il piano per il giorno corrente"""
    agenda = calcola_agenda_settimanale(df, config, esclusi, settimana_offset=0)
    return agenda.get(giorno_settimana, [])

# --- 6. MAIN APP ---
def main_app():
    # Verifica abbonamento
    subscription = st.session_state.get('subscription')
    user_is_admin = is_admin(st.session_state.user.id) if st.session_state.user else False
    
    # Sidebar con info utente
    with st.sidebar:
        st.markdown(f"### 👤 {st.session_state.user.email}")
        
        # Badge admin
        if user_is_admin:
            st.success("👑 **Amministratore**")
        
        # Banner stato abbonamento
        if subscription:
            status = subscription.get('status', 'pending')
            
            if status == 'trial':
                trial_end = subscription.get('trial_end')
                if trial_end:
                    trial_end_date = datetime.strptime(trial_end, '%Y-%m-%d').date() if isinstance(trial_end, str) else trial_end
                    days_left = (trial_end_date - datetime.now().date()).days
                    if days_left <= 3:
                        st.error(f"⚠️ **Prova scade tra {days_left} giorni!**")
                    else:
                        st.warning(f"🎁 **Prova:** {days_left} giorni rimasti")
            
            elif status == 'active' and subscription.get('subscription_end'):
                sub_end = subscription.get('subscription_end')
                sub_end_date = datetime.strptime(sub_end, '%Y-%m-%d').date() if isinstance(sub_end, str) else sub_end
                days_left = (sub_end_date - datetime.now().date()).days
                if days_left <= 30:
                    st.warning(f"📅 Abbonamento scade tra {days_left} giorni")
        
        if st.button("🚪 Logout", use_container_width=True):
            logout()
        
        # Pulsante Admin
        if user_is_admin:
            st.divider()
            if st.button("🔐 Pannello Admin", use_container_width=True, type="primary"):
                st.session_state.active_tab = "🔐 Admin"
                st.rerun()
        
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
    
    # Se è il pannello admin, mostralo
    if st.session_state.active_tab == "🔐 Admin":
        if user_is_admin:
            admin_panel()
            st.divider()
            if st.button("⬅️ Torna all'App", use_container_width=True):
                st.session_state.active_tab = "🚀 Giro Oggi"
                st.rerun()
            return
        else:
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
        
        # Controlla se oggi è giorno di ferie
        oggi_date = ora_italiana.date()
        is_ferie_oggi = False
        
        attiva_ferie = config.get('attiva_ferie', False)
        if attiva_ferie:
            fi = config.get('ferie_inizio')
            ff = config.get('ferie_fine')
            
            ferie_inizio = None
            ferie_fine = None
            
            if fi:
                if isinstance(fi, str):
                    try:
                        ferie_inizio = datetime.strptime(fi[:10], '%Y-%m-%d').date()
                    except:
                        pass
                elif hasattr(fi, 'date'):
                    ferie_inizio = fi.date()
                elif hasattr(fi, 'year'):
                    ferie_inizio = fi
            
            if ff:
                if isinstance(ff, str):
                    try:
                        ferie_fine = datetime.strptime(ff[:10], '%Y-%m-%d').date()
                    except:
                        pass
                elif hasattr(ff, 'date'):
                    ferie_fine = ff.date()
                elif hasattr(ff, 'year'):
                    ferie_fine = ff
            
            if ferie_inizio and ferie_fine:
                is_ferie_oggi = ferie_inizio <= oggi_date <= ferie_fine
        
        # Mostra messaggio appropriato
        if is_ferie_oggi:
            st.warning(f"🏖️ **Oggi sei in FERIE!** (dal {ferie_inizio.strftime('%d/%m/%Y')} al {ferie_fine.strftime('%d/%m/%Y')})")
            st.info("Per disattivare le ferie, vai su ⚙️ Config → Ferie")
        elif idx_g in giorni_lavorativi:
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
                    
                    # Trova dati completi del cliente per promemoria e email
                    cliente_row = df[df['nome_cliente'] == t['nome_cliente']].iloc[0] if not df[df['nome_cliente'] == t['nome_cliente']].empty else None
                    
                    # Stile diverso se visitato
                    if visitato:
                        with st.container(border=True):
                            col_vis = st.columns([1, 4])
                            col_vis[0].markdown("### ✅")
                            col_vis[1].markdown(f"### ~~{i}. {t['nome_cliente']}~~")
                            col_vis[1].caption(f"📍 {t.get('indirizzo', '')}")
                    else:
                        with st.container(border=True):
                            c1, c2 = st.columns([3, 2])
                            
                            with c1:
                                st.markdown(f"### {t['tipo_tappa'].split()[0]} {i}. {t['nome_cliente']}")
                                st.caption(f"⏰ {t['ora_arrivo']}")
                                
                                if t.get('indirizzo'):
                                    st.caption(f"📍 {t['indirizzo']}")
                                
                                # Mostra promemoria se presente
                                if cliente_row is not None and pd.notnull(cliente_row.get('promemoria')) and str(cliente_row.get('promemoria')).strip():
                                    st.warning(f"📝 **Promemoria:** {cliente_row['promemoria']}")
                            
                            with c2:
                                # PULSANTE REGISTRA VISITA
                                if st.button(f"✅ VISITATO", key=f"visita_{t['id']}", type="primary", use_container_width=True):
                                    # Aggiorna database
                                    update_cliente(t['id'], {
                                        'ultima_visita': ora_italiana.date().isoformat()
                                    })
                                    st.session_state.visitati_oggi.append(t['nome_cliente'])
                                    st.session_state.reload_data = True
                                    st.rerun()
                                
                                # Pulsanti azione
                                btn_cols = st.columns(4)
                                
                                # Naviga
                                btn_cols[0].link_button("🚗", f"https://www.google.com/maps/dir/?api=1&destination={t['latitude']},{t['longitude']}", use_container_width=True, help="Naviga")
                                
                                # Chiama
                                if t.get('cellulare') and str(t.get('cellulare')).strip():
                                    btn_cols[1].link_button("📱", f"tel:{t['cellulare']}", use_container_width=True, help="Chiama")
                                else:
                                    btn_cols[1].button("📱", disabled=True, use_container_width=True, key=f"tel_dis_{t['id']}")
                                
                                # Email
                                if cliente_row is not None and pd.notnull(cliente_row.get('mail')) and str(cliente_row.get('mail')).strip():
                                    btn_cols[2].link_button("📧", f"mailto:{cliente_row['mail']}", use_container_width=True, help="Email")
                                else:
                                    btn_cols[2].button("📧", disabled=True, use_container_width=True, key=f"mail_dis_{t['id']}")
                                
                                # Scheda cliente
                                if btn_cols[3].button("👤", key=f"scheda_{t['id']}", help="Scheda", use_container_width=True):
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
                        st.success("🎉 Hai completato tutte le visite programmate!")
                
                # === SEZIONE VISITE FUORI GIRO ===
                st.divider()
                nomi_nel_giro = [t['nome_cliente'] for t in tappe_oggi]
                visitati_fuori_giro = [v for v in st.session_state.visitati_oggi if v not in nomi_nel_giro]
                
                # Mostra clienti visitati fuori giro
                if visitati_fuori_giro:
                    st.subheader("➕ Visite Fuori Giro")
                    for nome_vfg in visitati_fuori_giro:
                        cliente_vfg = df[df['nome_cliente'] == nome_vfg]
                        if not cliente_vfg.empty:
                            cliente_vfg = cliente_vfg.iloc[0]
                            with st.container(border=True):
                                col_vfg1, col_vfg2 = st.columns([4, 1])
                                col_vfg1.markdown(f"### ✅ {nome_vfg}")
                                if cliente_vfg.get('indirizzo'):
                                    col_vfg1.caption(f"📍 {cliente_vfg['indirizzo']}")
                                if col_vfg2.button("👤", key=f"vfg_scheda_{nome_vfg}", help="Scheda"):
                                    st.session_state.cliente_selezionato = nome_vfg
                                    st.session_state.active_tab = "👤 Anagrafica"
                                    st.rerun()
                
                # Form per aggiungere visita fuori giro
                with st.expander("➕ Registra visita a cliente fuori giro"):
                    clienti_non_visitati = [c for c in df['nome_cliente'].tolist() if c not in st.session_state.visitati_oggi] if not df.empty and 'nome_cliente' in df.columns else []
                    cliente_extra = st.selectbox("Seleziona cliente:", [""] + sorted(clienti_non_visitati), key="cliente_extra_giro")
                    
                    if cliente_extra:
                        col_extra1, col_extra2 = st.columns(2)
                        if col_extra1.button("✅ Registra Visita", type="primary", use_container_width=True):
                            # Aggiorna ultima_visita nel database
                            cliente_row = df[df['nome_cliente'] == cliente_extra].iloc[0]
                            update_cliente(cliente_row['id'], {
                                'ultima_visita': ora_italiana.date().isoformat()
                            })
                            st.session_state.visitati_oggi.append(cliente_extra)
                            st.session_state.reload_data = True
                            st.success(f"✅ Visita a {cliente_extra} registrata!")
                            st.rerun()
                        
                        if col_extra2.button("👤 Vai alla Scheda", use_container_width=True):
                            st.session_state.cliente_selezionato = cliente_extra
                            st.session_state.active_tab = "👤 Anagrafica"
                            st.rerun()
                
                # Riepilogo finale
                st.divider()
                tot_visitati = len(st.session_state.visitati_oggi)
                tot_giro = len(tappe_oggi)
                tot_fuori = len(visitati_fuori_giro)
                
                st.markdown(f"""
                ### 📊 Riepilogo Giornata
                | | |
                |---|---|
                | ✅ **Visitati totali** | **{tot_visitati}** |
                | 🚗 Nel giro | {tot_visitati - tot_fuori} / {tot_giro} |
                | ➕ Fuori giro | {tot_fuori} |
                """)
                
            else:
                st.info("📭 Nessuna visita pianificata per oggi")
                
                # Anche senza giro, permetti visite fuori giro
                st.divider()
                st.subheader("➕ Registra visita")
                
                if st.session_state.visitati_oggi:
                    st.success(f"✅ Hai visitato {len(st.session_state.visitati_oggi)} clienti oggi")
                    for nome_v in st.session_state.visitati_oggi:
                        st.write(f"✅ {nome_v}")
                
                clienti_non_visitati = [c for c in df['nome_cliente'].tolist() if c not in st.session_state.visitati_oggi] if not df.empty and 'nome_cliente' in df.columns else []
                cliente_extra = st.selectbox("Seleziona cliente da visitare:", [""] + sorted(clienti_non_visitati), key="cliente_no_giro")
                
                if cliente_extra:
                    if st.button("✅ Registra Visita", type="primary"):
                        cliente_row = df[df['nome_cliente'] == cliente_extra].iloc[0]
                        update_cliente(cliente_row['id'], {
                            'ultima_visita': ora_italiana.date().isoformat()
                        })
                        st.session_state.visitati_oggi.append(cliente_extra)
                        st.session_state.reload_data = True
                        st.success(f"✅ Visita a {cliente_extra} registrata!")
                        st.rerun()
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
        
        # === STORICO VISITE ===
        st.divider()
        st.subheader("📅 Storico Visite")
        
        col_data1, col_data2, col_data3 = st.columns([1, 1, 2])
        
        with col_data1:
            # Selezione tipo filtro
            tipo_filtro = st.radio("Periodo:", ["Giorno singolo", "Range date"], horizontal=True)
        
        with col_data2:
            if tipo_filtro == "Giorno singolo":
                data_filtro = st.date_input("📆 Seleziona data:", value=ora_italiana.date(), key="data_storico")
                data_inizio = data_filtro
                data_fine = data_filtro
            else:
                data_inizio = st.date_input("📆 Da:", value=ora_italiana.date() - timedelta(days=7), key="data_inizio_storico")
                data_fine = st.date_input("📆 A:", value=ora_italiana.date(), key="data_fine_storico")
        
        # Filtra clienti visitati nel periodo
        if not df.empty and 'ultima_visita' in df.columns:
            df_storico = df[df['ultima_visita'].notna()].copy()
            
            if not df_storico.empty:
                # Filtra per data
                df_storico['data_visita'] = df_storico['ultima_visita'].dt.date
                df_visitati = df_storico[
                    (df_storico['data_visita'] >= data_inizio) & 
                    (df_storico['data_visita'] <= data_fine)
                ].sort_values('ultima_visita', ascending=False)
                
                with col_data3:
                    if tipo_filtro == "Giorno singolo":
                        st.metric("📊 Visite del giorno", len(df_visitati))
                    else:
                        giorni_periodo = (data_fine - data_inizio).days + 1
                        media = len(df_visitati) / giorni_periodo if giorni_periodo > 0 else 0
                        m1, m2 = st.columns(2)
                        m1.metric("📊 Visite totali", len(df_visitati))
                        m2.metric("📈 Media/giorno", f"{media:.1f}")
                
                if not df_visitati.empty:
                    st.divider()
                    
                    # Raggruppa per data se range
                    if tipo_filtro == "Range date" and len(df_visitati) > 0:
                        # Mostra grafico visite per giorno
                        visite_per_giorno = df_visitati.groupby('data_visita').size().reset_index(name='visite')
                        visite_per_giorno['data_visita'] = pd.to_datetime(visite_per_giorno['data_visita'])
                        visite_per_giorno = visite_per_giorno.sort_values('data_visita')
                        
                        st.bar_chart(visite_per_giorno.set_index('data_visita')['visite'])
                    
                    # Lista clienti visitati
                    st.subheader(f"📋 Clienti visitati ({len(df_visitati)})")
                    
                    for _, row in df_visitati.iterrows():
                        with st.container(border=True):
                            col_st1, col_st2, col_st3 = st.columns([3, 2, 1])
                            
                            # Info cliente
                            col_st1.markdown(f"**{row['nome_cliente']}**")
                            col_st1.caption(f"📍 {row.get('indirizzo', 'N/D')}")
                            
                            # Stato e data
                            stato = row.get('stato_cliente', 'CLIENTE ATTIVO')
                            colori_stato = {
                                'CLIENTE ATTIVO': '🟢',
                                'CLIENTE NUOVO': '🔵',
                                'CLIENTE POSSIBILE': '🟡',
                                'CLIENTE PROBABILE': '🟠'
                            }
                            icona = colori_stato.get(stato, '⚪')
                            col_st2.write(f"{icona} {stato}")
                            col_st2.caption(f"📅 {row['ultima_visita'].strftime('%d/%m/%Y %H:%M') if pd.notnull(row['ultima_visita']) else 'N/D'}")
                            
                            # Pulsante scheda
                            if col_st3.button("👤", key=f"storico_{row['id']}", help="Apri scheda"):
                                st.session_state.cliente_selezionato = row['nome_cliente']
                                st.session_state.active_tab = "👤 Anagrafica"
                                st.rerun()
                else:
                    if tipo_filtro == "Giorno singolo":
                        st.info(f"📭 Nessuna visita registrata il {data_filtro.strftime('%d/%m/%Y')}")
                    else:
                        st.info(f"📭 Nessuna visita registrata dal {data_inizio.strftime('%d/%m/%Y')} al {data_fine.strftime('%d/%m/%Y')}")
            else:
                st.info("📭 Nessuna visita registrata")
        
        # === STATISTICHE PER STATO ===
        st.divider()
        st.subheader("📈 Statistiche per Stato Cliente")
        
        if not df.empty and 'stato_cliente' in df.columns:
            # Conta per stato
            stats_stato = df['stato_cliente'].value_counts()
            
            col_stat1, col_stat2 = st.columns([1, 2])
            
            with col_stat1:
                for stato, count in stats_stato.items():
                    colori_stato = {
                        'CLIENTE ATTIVO': '🟢',
                        'CLIENTE NUOVO': '🔵',
                        'CLIENTE POSSIBILE': '🟡',
                        'CLIENTE PROBABILE': '🟠'
                    }
                    icona = colori_stato.get(stato, '⚪')
                    st.write(f"{icona} **{stato}**: {count}")
            
            with col_stat2:
                # Grafico a barre
                chart_data = pd.DataFrame({
                    'Stato': stats_stato.index,
                    'Clienti': stats_stato.values
                })
                st.bar_chart(chart_data.set_index('Stato'))
    
    # --- TAB: AGENDA ---
    elif st.session_state.active_tab == "📅 Agenda":
        st.header("📅 Agenda Settimanale Ottimizzata")
        
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
        
        # CALCOLA AGENDA OTTIMIZZATA
        agenda_settimana = calcola_agenda_settimanale(
            df, 
            config, 
            st.session_state.esclusi_oggi if st.session_state.current_week_index == 0 else [],
            st.session_state.current_week_index
        )
        
        # Crea colonne per i giorni lavorativi
        if giorni_attivi:
            cols_giorni = st.columns(len(giorni_attivi))
            
            totale_visite_settimana = 0
            totale_km_settimana = 0
            
            # Funzione per verificare se un giorno è in ferie
            def is_giorno_ferie_agenda(data):
                attiva_ferie = config.get('attiva_ferie', False)
                if not attiva_ferie:
                    return False
                
                fi = config.get('ferie_inizio')
                ff = config.get('ferie_fine')
                
                ferie_inizio = None
                ferie_fine = None
                
                if fi:
                    if isinstance(fi, str):
                        try:
                            ferie_inizio = datetime.strptime(fi[:10], '%Y-%m-%d').date()
                        except:
                            pass
                    elif hasattr(fi, 'date'):
                        ferie_inizio = fi.date()
                    elif hasattr(fi, 'year'):
                        ferie_inizio = fi
                
                if ff:
                    if isinstance(ff, str):
                        try:
                            ferie_fine = datetime.strptime(ff[:10], '%Y-%m-%d').date()
                        except:
                            pass
                    elif hasattr(ff, 'date'):
                        ferie_fine = ff.date()
                    elif hasattr(ff, 'year'):
                        ferie_fine = ff
                
                if ferie_inizio and ferie_fine:
                    return ferie_inizio <= data <= ferie_fine
                return False
            
            for col_idx, giorno_idx in enumerate(giorni_attivi):
                data_giorno = lunedi_selezionato + timedelta(days=giorno_idx)
                tappe_giorno = agenda_settimana.get(giorno_idx, [])
                is_ferie = is_giorno_ferie_agenda(data_giorno)
                
                with cols_giorni[col_idx]:
                    # Header giorno
                    is_oggi = data_giorno == oggi
                    giorno_label = f"**{giorni_nomi_full[giorno_idx][:3]}**" if is_oggi else giorni_nomi_full[giorno_idx][:3]
                    
                    if is_ferie:
                        st.subheader(f"🏖️ {giorno_label}")
                    else:
                        st.subheader(f"{'📍 ' if is_oggi else ''}{giorno_label}")
                    st.caption(f"{data_giorno.strftime('%d/%m')}")
                    
                    # Mostra FERIE se è giorno di ferie
                    if is_ferie:
                        st.warning("🏖️ **FERIE**")
                        continue
                    
                    # Mostra tappe
                    if tappe_giorno:
                        num_app = sum(1 for t in tappe_giorno if '📌' in t.get('tipo_tappa', ''))
                        num_giro = len(tappe_giorno) - num_app
                        km_giorno = sum(t.get('distanza_km', 0) for t in tappe_giorno)
                        
                        if num_app > 0:
                            st.info(f"📌 {num_app} appuntamenti")
                        if num_giro > 0:
                            st.success(f"🚗 {num_giro} visite")
                        if km_giorno > 0:
                            st.caption(f"🛣️ ~{km_giorno:.0f} km")
                        
                        totale_visite_settimana += len(tappe_giorno)
                        totale_km_settimana += km_giorno
                        
                        st.divider()
                        
                        for tappa in tappe_giorno[:8]:  # Max 8 per colonna
                            with st.container(border=True):
                                icona = "📌" if "📌" in tappa.get('tipo_tappa', '') else "🚗"
                                st.caption(f"{icona} {tappa.get('ora_arrivo', '--:--')}")
                                
                                nome_display = tappa['nome_cliente'][:15] + "..." if len(tappa['nome_cliente']) > 15 else tappa['nome_cliente']
                                if st.button(nome_display, key=f"ag_{data_giorno}_{tappa['nome_cliente']}", use_container_width=True):
                                    st.session_state.cliente_selezionato = tappa['nome_cliente']
                                    st.session_state.active_tab = "👤 Anagrafica"
                                    st.rerun()
                                
                                if tappa.get('distanza_km'):
                                    st.caption(f"📍 {tappa['distanza_km']} km")
                        
                        if len(tappe_giorno) > 8:
                            st.caption(f"... +{len(tappe_giorno) - 8} altre")
                    else:
                        if data_giorno < oggi:
                            st.info("📅 Passato")
                        else:
                            st.info("📭 Nessuna visita")
            
            # Statistiche settimana
            st.divider()
            st.subheader("📊 Riepilogo Settimana")
            
            col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
            col_stat1.metric("📊 Visite Totali", totale_visite_settimana)
            col_stat2.metric("🛣️ Km Totali", f"~{totale_km_settimana:.0f}")
            col_stat3.metric("📅 Giorni Lavorativi", len(giorni_attivi))
            media = totale_visite_settimana / len(giorni_attivi) if giorni_attivi else 0
            col_stat4.metric("📈 Media/Giorno", f"{media:.1f}")
            
            # Info algoritmo
            with st.expander("ℹ️ Come funziona l'ottimizzazione"):
                st.markdown("""
                **L'algoritmo considera:**
                - 📍 **Distanza dal punto di partenza** e tra clienti
                - ⏰ **Orari di lavoro** configurati
                - 🍽️ **Pausa pranzo** automatica
                - 🏠 **Tempo di ritorno** a casa prima della fine lavoro
                - 🚨 **Priorità clienti** (scaduti da più tempo = visitati prima)
                - 🚗 **Percorso ottimizzato** con algoritmo Nearest Neighbor
                
                Ogni cliente appare **una sola volta** nella settimana!
                """)
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
            # === 1. BARRA RICERCA CLIENTE ===
            col_filtro1, col_filtro2, col_filtro3 = st.columns([2, 1, 1])
            
            with col_filtro1:
                # Ricerca cliente
                nomi_tutti = [""] + sorted(df['nome_cliente'].tolist()) if 'nome_cliente' in df.columns else [""]
                idx = nomi_tutti.index(st.session_state.cliente_selezionato) if st.session_state.cliente_selezionato in nomi_tutti else 0
                scelto = st.selectbox("🔍 Cerca cliente:", nomi_tutti, index=idx)
            
            with col_filtro2:
                # Filtro per stato cliente
                stati_filtro = ["Tutti", "🟢 Attivo", "🔵 Nuovo", "🟡 Possibile", "🟠 Probabile"]
                filtro_stato = st.selectbox("📊 Stato:", stati_filtro, key="filtro_stato_anagrafica")
            
            with col_filtro3:
                # Filtro per incluso nel giro
                filtro_giro = st.selectbox("🚗 Giro:", ["Tutti", "Nel giro", "Fuori giro"], key="filtro_giro_anagrafica")
            
            # Applica filtri per mostrare conteggio
            df_filtrato = df.copy()
            mappa_stati = {"🟢 Attivo": "CLIENTE ATTIVO", "🔵 Nuovo": "CLIENTE NUOVO", "🟡 Possibile": "CLIENTE POSSIBILE", "🟠 Probabile": "CLIENTE PROBABILE"}
            if filtro_stato != "Tutti":
                df_filtrato = df_filtrato[df_filtrato['stato_cliente'] == mappa_stati.get(filtro_stato, '')]
            if filtro_giro == "Nel giro":
                df_filtrato = df_filtrato[df_filtrato['visitare'] == 'SI']
            elif filtro_giro == "Fuori giro":
                df_filtrato = df_filtrato[df_filtrato['visitare'] != 'SI']
            
            st.caption(f"📋 {len(df_filtrato)} clienti | Totale: {len(df)}")
            
            if scelto:
                st.session_state.cliente_selezionato = scelto
                cliente = df[df['nome_cliente'] == scelto].iloc[0]
                
                st.divider()
                
                # === 2. ANAGRAFICA DEL CLIENTE ===
                with st.container(border=True):
                    # Header con stato
                    stato = cliente.get('stato_cliente', 'CLIENTE ATTIVO')
                    colori_stato = {
                        'CLIENTE ATTIVO': ('🟢', 'green'),
                        'CLIENTE NUOVO': ('🔵', 'blue'),
                        'CLIENTE POSSIBILE': ('🟡', 'orange'),
                        'CLIENTE PROBABILE': ('🟠', 'red')
                    }
                    icona_stato, _ = colori_stato.get(stato, ('⚪', 'gray'))
                    
                    col_nome, col_stato = st.columns([3, 1])
                    col_nome.markdown(f"## {scelto}")
                    col_stato.markdown(f"### {icona_stato} {stato.replace('CLIENTE ', '')}")
                    
                    # Dati principali in colonne
                    col_info1, col_info2 = st.columns(2)
                    
                    with col_info1:
                        if cliente.get('indirizzo'):
                            st.write(f"📍 **Indirizzo:** {cliente['indirizzo']}")
                        if cliente.get('cap') or cliente.get('provincia'):
                            st.write(f"🏙️ **CAP/Prov:** {cliente.get('cap', '')} {cliente.get('provincia', '')}")
                        if cliente.get('contatto'):
                            st.write(f"👤 **Referente:** {cliente['contatto']}")
                    
                    with col_info2:
                        if cliente.get('telefono'):
                            st.write(f"📞 **Telefono:** {cliente['telefono']}")
                        if cliente.get('cellulare'):
                            st.write(f"📱 **Cellulare:** {cliente['cellulare']}")
                        if cliente.get('mail'):
                            st.write(f"📧 **Email:** {cliente['mail']}")
                    
                    st.divider()
                    
                    # Info visite
                    col_vis1, col_vis2, col_vis3 = st.columns(3)
                    
                    ultima = cliente.get('ultima_visita')
                    if pd.notnull(ultima):
                        col_vis1.metric("📅 Ultima visita", ultima.strftime('%d/%m/%Y'))
                    else:
                        col_vis1.metric("📅 Ultima visita", "Mai")
                    
                    col_vis2.metric("🔄 Frequenza", f"{cliente.get('frequenza_giorni', 30)} giorni")
                    col_vis3.metric("🚗 Nel giro", "✅ SI" if cliente.get('visitare') == 'SI' else "❌ NO")
                    
                    # Pulsanti azione rapida
                    st.divider()
                    btn1, btn2, btn3, btn4 = st.columns(4)
                    
                    if pd.notnull(cliente.get('latitude')) and cliente.get('latitude') != 0:
                        btn1.link_button("🚗 Naviga", f"https://www.google.com/maps/dir/?api=1&destination={cliente['latitude']},{cliente['longitude']}", use_container_width=True)
                    else:
                        btn1.button("🚗 Naviga", disabled=True, use_container_width=True)
                    
                    if cliente.get('cellulare'):
                        btn2.link_button("📱 Chiama", f"tel:{cliente['cellulare']}", use_container_width=True)
                    else:
                        btn2.button("📱 Chiama", disabled=True, use_container_width=True)
                    
                    if cliente.get('mail'):
                        btn3.link_button("📧 Email", f"mailto:{cliente['mail']}", use_container_width=True)
                    else:
                        btn3.button("📧 Email", disabled=True, use_container_width=True)
                    
                    if cliente.get('telefono'):
                        btn4.link_button("📞 Telefono", f"tel:{cliente['telefono']}", use_container_width=True)
                    else:
                        btn4.button("📞 Telefono", disabled=True, use_container_width=True)
                
                st.divider()
                
                # === 3. REGISTRA VISITA + PROMEMORIA (affiancati) ===
                col_visita, col_promemoria = st.columns(2)
                
                # --- Colonna Registra Visita ---
                with col_visita:
                    with st.container(border=True):
                        st.subheader("🏁 Registra Visita")
                        
                        # Tipo visita
                        tipo_visita = st.radio(
                            "Tipo di contatto:",
                            ["🚗 Visita dal cliente", "📞 Telefonata"],
                            horizontal=True,
                            key="tipo_visita"
                        )
                        
                        data_visita = st.date_input("📅 Data:", value=ora_italiana.date(), key="data_visita_reg")
                        
                        report_visita = st.text_area(
                            "📝 Note/Report:",
                            placeholder="Descrivi brevemente la visita o telefonata...",
                            height=100,
                            key="report_visita"
                        )
                        
                        if st.button("✅ REGISTRA VISITA", type="primary", use_container_width=True):
                            # Crea report con tipo
                            tipo_label = "VISITA" if "Visita" in tipo_visita else "TELEFONATA"
                            nuovo_report = f"[{data_visita.strftime('%d/%m/%Y')}] [{tipo_label}] {report_visita}"
                            vecchio = str(cliente.get('storico_report', '') or '')
                            storico = nuovo_report + "\n\n" + vecchio if vecchio.strip() else nuovo_report
                            
                            update_cliente(cliente['id'], {
                                'ultima_visita': data_visita.isoformat(),
                                'storico_report': storico
                            })
                            
                            if scelto not in st.session_state.visitati_oggi:
                                st.session_state.visitati_oggi.append(scelto)
                            
                            st.session_state.reload_data = True
                            st.success(f"✅ {tipo_label} registrata!")
                            st.rerun()
                
                # --- Colonna Promemoria ---
                with col_promemoria:
                    with st.container(border=True):
                        st.subheader("📝 Promemoria")
                        
                        promemoria_attuale = cliente.get('promemoria', '') if pd.notnull(cliente.get('promemoria')) else ''
                        
                        if promemoria_attuale:
                            st.warning(f"**Attuale:** {promemoria_attuale}")
                        
                        nuovo_promemoria = st.text_area(
                            "Promemoria prossima visita:",
                            value=promemoria_attuale,
                            placeholder="Es: Portare catalogo, Chiedere feedback...",
                            height=100,
                            key="input_promemoria"
                        )
                        
                        col_prom1, col_prom2 = st.columns(2)
                        
                        if col_prom1.button("💾 Salva", use_container_width=True, type="primary"):
                            update_cliente(cliente['id'], {'promemoria': nuovo_promemoria})
                            st.session_state.reload_data = True
                            st.success("✅ Salvato!")
                            st.rerun()
                        
                        if col_prom2.button("🗑️ Cancella", use_container_width=True):
                            update_cliente(cliente['id'], {'promemoria': ''})
                            st.session_state.reload_data = True
                            st.success("✅ Cancellato!")
                            st.rerun()
                
                st.divider()
                
                # === 4. GEOLOCALIZZA CLIENTE ===
                with st.container(border=True):
                    st.subheader("📍 Geolocalizza Cliente")
                    
                    # Mostra coordinate attuali
                    lat_attuale = cliente.get('latitude') if pd.notnull(cliente.get('latitude')) else 0.0
                    lon_attuale = cliente.get('longitude') if pd.notnull(cliente.get('longitude')) else 0.0
                    
                    if lat_attuale != 0 and lon_attuale != 0:
                        st.success(f"📍 Coordinate attuali: **{lat_attuale:.6f}, {lon_attuale:.6f}**")
                    else:
                        st.error("⚠️ Coordinate mancanti! Il cliente non apparirà nel giro.")
                    
                    col_geo1, col_geo2 = st.columns(2)
                    
                    with col_geo1:
                        st.write("**🔍 Da indirizzo:**")
                        if st.button("🌍 Genera coordinate da indirizzo", use_container_width=True):
                            if cliente.get('indirizzo'):
                                new_coords = get_coords(cliente['indirizzo'])
                                if new_coords:
                                    update_cliente(cliente['id'], {
                                        'latitude': new_coords[0],
                                        'longitude': new_coords[1]
                                    })
                                    st.session_state.reload_data = True
                                    st.success(f"✅ Coordinate: {new_coords[0]:.6f}, {new_coords[1]:.6f}")
                                    st.rerun()
                                else:
                                    st.error("❌ Indirizzo non trovato")
                            else:
                                st.error("❌ Inserisci prima un indirizzo")
                    
                    with col_geo2:
                        st.write("**📍 Manuale (sono qui):**")
                        with st.expander("Inserisci coordinate GPS"):
                            new_lat = st.number_input("Latitudine", value=0.0, format="%.6f", key="new_lat")
                            new_lon = st.number_input("Longitudine", value=0.0, format="%.6f", key="new_lon")
                            
                            if st.button("💾 Salva posizione", use_container_width=True):
                                if new_lat != 0 and new_lon != 0:
                                    addr_info = reverse_geocode(new_lat, new_lon)
                                    update_data = {'latitude': new_lat, 'longitude': new_lon}
                                    if addr_info:
                                        update_data['indirizzo'] = addr_info['indirizzo_completo']
                                        if addr_info['cap']:
                                            update_data['cap'] = addr_info['cap']
                                        if addr_info['provincia']:
                                            update_data['provincia'] = addr_info['provincia']
                                    
                                    update_cliente(cliente['id'], update_data)
                                    st.session_state.reload_data = True
                                    st.success("✅ Posizione salvata!")
                                    st.rerun()
                                else:
                                    st.error("❌ Coordinate non valide")
                        
                        st.caption("💡 Da Google Maps: tieni premuto → copia coordinate")
                
                # === 5. MODIFICA DATI (in expander) ===
                with st.expander("✏️ Modifica tutti i dati"):
                    with st.form("edit_cliente"):
                        c1, c2 = st.columns(2)
                        
                        nome = c1.text_input("Nome", cliente['nome_cliente'])
                        indirizzo = c1.text_input("Indirizzo", cliente.get('indirizzo', ''))
                        cap = c1.text_input("CAP", cliente.get('cap', ''))
                        provincia = c1.text_input("Provincia", cliente.get('provincia', ''))
                        frequenza = c1.number_input("Frequenza (gg)", value=int(cliente.get('frequenza_giorni', 30)))
                        
                        stati_cliente = ["CLIENTE ATTIVO", "CLIENTE NUOVO", "CLIENTE POSSIBILE", "CLIENTE PROBABILE"]
                        stato_attuale = cliente.get('stato_cliente', 'CLIENTE ATTIVO')
                        if stato_attuale not in stati_cliente:
                            stato_attuale = 'CLIENTE ATTIVO'
                        stato_cliente = c1.selectbox("📊 Stato", stati_cliente, index=stati_cliente.index(stato_attuale))
                        visitare = c1.selectbox("🚗 Nel Giro?", ["SI", "NO"], index=0 if cliente.get('visitare') == 'SI' else 1)
                        
                        telefono = c2.text_input("Telefono", cliente.get('telefono', ''))
                        cellulare = c2.text_input("Cellulare", cliente.get('cellulare', ''))
                        mail = c2.text_input("Email", cliente.get('mail', ''))
                        contatto = c2.text_input("Referente", cliente.get('contatto', ''))
                        
                        latitudine = c2.number_input("Latitudine", value=float(lat_attuale), format="%.6f")
                        longitudine = c2.number_input("Longitudine", value=float(lon_attuale), format="%.6f")
                        
                        note = st.text_area("Note", cliente.get('note', ''), height=80)
                        storico = st.text_area("Storico Report", cliente.get('storico_report', ''), height=120)
                        
                        if st.form_submit_button("💾 Salva Modifiche", use_container_width=True, type="primary"):
                            update_cliente(cliente['id'], {
                                'nome_cliente': nome,
                                'indirizzo': indirizzo,
                                'cap': cap,
                                'provincia': provincia,
                                'frequenza_giorni': frequenza,
                                'stato_cliente': stato_cliente,
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
                
                # === 6. ELIMINA CLIENTE ===
                with st.expander("🗑️ Elimina Cliente"):
                    st.warning(f"⚠️ L'eliminazione di **{scelto}** è DEFINITIVA e non può essere annullata!")
                    conferma = st.checkbox("Confermo di voler eliminare questo cliente")
                    if conferma:
                        if st.button("❌ ELIMINA CLIENTE", type="primary"):
                            delete_cliente(cliente['id'])
                            st.session_state.cliente_selezionato = None
                            st.session_state.reload_data = True
                            st.rerun()
        else:
            st.info("Nessun cliente presente. Vai su ➕ Nuovo per aggiungerne uno.")
    
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
        
        # =============================================
        # === NUOVA SEZIONE: ESPORTAZIONE DATI ===
        # =============================================
        st.divider()
        st.subheader("📤 Esporta Dati")
        
        tab_exp1, tab_exp2, tab_exp3 = st.tabs(["👥 Clienti", "📅 Agenda", "📊 Report Visite"])
        
        # --- TAB ESPORTA CLIENTI ---
        with tab_exp1:
            st.write("**Esporta l'elenco dei clienti in formato CSV o Excel**")
            
            col_filt1, col_filt2 = st.columns(2)
            
            with col_filt1:
                exp_stato = st.selectbox(
                    "Filtra per stato:",
                    ["Tutti", "CLIENTE ATTIVO", "CLIENTE NUOVO", "CLIENTE POSSIBILE", "CLIENTE PROBABILE"],
                    key="exp_stato_cliente"
                )
            
            with col_filt2:
                exp_giro = st.selectbox(
                    "Filtra per giro:",
                    ["Tutti", "Solo nel giro (SI)", "Solo fuori giro (NO)"],
                    key="exp_giro_cliente"
                )
            
            # Applica filtri
            df_export = df.copy()
            if exp_stato != "Tutti":
                df_export = df_export[df_export['stato_cliente'] == exp_stato]
            if exp_giro == "Solo nel giro (SI)":
                df_export = df_export[df_export['visitare'] == 'SI']
            elif exp_giro == "Solo fuori giro (NO)":
                df_export = df_export[df_export['visitare'] != 'SI']
            
            # Seleziona colonne da esportare
            with st.expander("⚙️ Seleziona colonne"):
                colonne_disponibili = ['nome_cliente', 'indirizzo', 'cap', 'provincia', 'telefono', 
                                      'cellulare', 'mail', 'contatto', 'frequenza_giorni', 
                                      'ultima_visita', 'visitare', 'stato_cliente', 'latitude', 
                                      'longitude', 'note', 'promemoria']
                
                colonne_default = ['nome_cliente', 'indirizzo', 'cap', 'provincia', 'telefono', 
                                  'cellulare', 'mail', 'frequenza_giorni', 'ultima_visita', 'stato_cliente']
                
                colonne_sel = st.multiselect(
                    "Colonne da includere:",
                    [c for c in colonne_disponibili if c in df_export.columns],
                    default=[c for c in colonne_default if c in df_export.columns],
                    key="colonne_export_clienti"
                )
            
            st.info(f"📊 **{len(df_export)} clienti** pronti per l'esportazione")
            
            col_btn1, col_btn2 = st.columns(2)
            
            with col_btn1:
                if not df_export.empty and colonne_sel:
                    df_to_export = df_export[colonne_sel].copy()
                    # Formatta date
                    if 'ultima_visita' in df_to_export.columns:
                        df_to_export['ultima_visita'] = pd.to_datetime(df_to_export['ultima_visita']).dt.strftime('%d/%m/%Y')
                    
                    csv = df_to_export.to_csv(index=False)
                    st.download_button(
                        "📥 Scarica CSV",
                        csv,
                        f"clienti_export_{ora_italiana.strftime('%Y%m%d')}.csv",
                        "text/csv",
                        use_container_width=True
                    )
            
            with col_btn2:
                if not df_export.empty and colonne_sel:
                    df_to_export = df_export[colonne_sel].copy()
                    if 'ultima_visita' in df_to_export.columns:
                        df_to_export['ultima_visita'] = pd.to_datetime(df_to_export['ultima_visita']).dt.strftime('%d/%m/%Y')
                    
                    # Crea Excel in memoria
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df_to_export.to_excel(writer, index=False, sheet_name='Clienti')
                    output.seek(0)
                    
                    st.download_button(
                        "📥 Scarica Excel",
                        output,
                        f"clienti_export_{ora_italiana.strftime('%Y%m%d')}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
        
        # --- TAB ESPORTA AGENDA ---
        with tab_exp2:
            st.write("**Esporta l'agenda settimanale ottimizzata**")
            
            # Selezione settimana
            col_sett1, col_sett2 = st.columns(2)
            with col_sett1:
                settimana_exp = st.selectbox(
                    "Seleziona settimana:",
                    ["Settimana corrente", "Prossima settimana", "Tra 2 settimane"],
                    key="settimana_export"
                )
            
            offset_map = {"Settimana corrente": 0, "Prossima settimana": 1, "Tra 2 settimane": 2}
            offset = offset_map.get(settimana_exp, 0)
            
            # Calcola agenda
            agenda_exp = calcola_agenda_settimanale(df, config, [], offset)
            
            # Prepara dati per export
            righe_agenda = []
            giorni_nomi_full = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
            
            oggi = ora_italiana.date()
            lunedi = oggi - timedelta(days=oggi.weekday()) + timedelta(weeks=offset)
            
            for giorno_idx, tappe in agenda_exp.items():
                data_giorno = lunedi + timedelta(days=giorno_idx)
                for i, tappa in enumerate(tappe, 1):
                    righe_agenda.append({
                        'Giorno': giorni_nomi_full[giorno_idx],
                        'Data': data_giorno.strftime('%d/%m/%Y'),
                        'Ordine': i,
                        'Ora Arrivo': tappa.get('ora_arrivo', ''),
                        'Cliente': tappa.get('nome_cliente', ''),
                        'Indirizzo': tappa.get('indirizzo', ''),
                        'Tipo': 'Appuntamento' if '📌' in tappa.get('tipo_tappa', '') else 'Giro',
                        'Distanza (km)': round(tappa.get('distanza_km', 0), 1)
                    })
            
            df_agenda_exp = pd.DataFrame(righe_agenda)
            
            tot_visite = len(df_agenda_exp)
            tot_km = df_agenda_exp['Distanza (km)'].sum() if not df_agenda_exp.empty else 0
            
            st.info(f"📊 **{tot_visite} visite** programmate | ~{tot_km:.0f} km totali")
            
            if not df_agenda_exp.empty:
                with st.expander("👀 Anteprima agenda"):
                    st.dataframe(df_agenda_exp, use_container_width=True)
                
                col_ag1, col_ag2 = st.columns(2)
                
                with col_ag1:
                    csv_agenda = df_agenda_exp.to_csv(index=False)
                    st.download_button(
                        "📥 Scarica CSV",
                        csv_agenda,
                        f"agenda_{lunedi.strftime('%Y%m%d')}.csv",
                        "text/csv",
                        use_container_width=True
                    )
                
                with col_ag2:
                    output_ag = io.BytesIO()
                    with pd.ExcelWriter(output_ag, engine='openpyxl') as writer:
                        df_agenda_exp.to_excel(writer, index=False, sheet_name='Agenda')
                    output_ag.seek(0)
                    
                    st.download_button(
                        "📥 Scarica Excel",
                        output_ag,
                        f"agenda_{lunedi.strftime('%Y%m%d')}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
            else:
                st.warning("📭 Nessuna visita programmata per questa settimana")
        
        # --- TAB ESPORTA REPORT VISITE ---
        with tab_exp3:
            st.write("**Esporta lo storico delle visite effettuate**")
            
            col_date1, col_date2 = st.columns(2)
            with col_date1:
                data_inizio_exp = st.date_input(
                    "📅 Da:",
                    value=ora_italiana.date() - timedelta(days=30),
                    key="exp_data_inizio"
                )
            with col_date2:
                data_fine_exp = st.date_input(
                    "📅 A:",
                    value=ora_italiana.date(),
                    key="exp_data_fine"
                )
            
            # Filtra visite nel periodo
            if not df.empty and 'ultima_visita' in df.columns:
                df_report = df[df['ultima_visita'].notna()].copy()
                
                if not df_report.empty:
                    df_report['data_visita'] = df_report['ultima_visita'].dt.date
                    df_report_filtered = df_report[
                        (df_report['data_visita'] >= data_inizio_exp) & 
                        (df_report['data_visita'] <= data_fine_exp)
                    ].sort_values('ultima_visita', ascending=False)
                    
                    # Prepara dati per export
                    cols_report = ['nome_cliente', 'indirizzo', 'provincia', 'ultima_visita', 'stato_cliente', 'storico_report']
                    cols_presenti = [c for c in cols_report if c in df_report_filtered.columns]
                    df_report_exp = df_report_filtered[cols_presenti].copy()
                    df_report_exp.columns = ['Cliente', 'Indirizzo', 'Provincia', 'Data Visita', 'Stato', 'Report'][:len(cols_presenti)]
                    if 'Data Visita' in df_report_exp.columns:
                        df_report_exp['Data Visita'] = pd.to_datetime(df_report_exp['Data Visita']).dt.strftime('%d/%m/%Y')
                    
                    st.info(f"📊 **{len(df_report_exp)} visite** nel periodo selezionato")
                    
                    if not df_report_exp.empty:
                        with st.expander("👀 Anteprima report"):
                            st.dataframe(df_report_exp.head(20), use_container_width=True)
                        
                        col_rep1, col_rep2 = st.columns(2)
                        
                        with col_rep1:
                            csv_report = df_report_exp.to_csv(index=False)
                            st.download_button(
                                "📥 Scarica CSV",
                                csv_report,
                                f"report_visite_{data_inizio_exp.strftime('%Y%m%d')}_{data_fine_exp.strftime('%Y%m%d')}.csv",
                                "text/csv",
                                use_container_width=True
                            )
                        
                        with col_rep2:
                            output_rep = io.BytesIO()
                            with pd.ExcelWriter(output_rep, engine='openpyxl') as writer:
                                df_report_exp.to_excel(writer, index=False, sheet_name='Report Visite')
                            output_rep.seek(0)
                            
                            st.download_button(
                                "📥 Scarica Excel",
                                output_rep,
                                f"report_visite_{data_inizio_exp.strftime('%Y%m%d')}_{data_fine_exp.strftime('%Y%m%d')}.xlsx",
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                use_container_width=True
                            )
                    else:
                        st.warning("📭 Nessuna visita nel periodo selezionato")
                else:
                    st.warning("📭 Nessuna visita registrata")
            else:
                st.warning("📭 Nessun dato disponibile")
        
        # =============================================
        # === FINE SEZIONE ESPORTAZIONE ===
        # =============================================
        
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
    st.caption("🚀 **Giro Visite CRM Pro** - Versione SaaS 3.1")

# --- RUN APP ---
init_auth_state()

if st.session_state.user is None:
    login_page()
else:
    main_app()
