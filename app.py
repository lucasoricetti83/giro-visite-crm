import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from datetime import datetime, timedelta, time
from math import radians, cos, sin, asin, sqrt
import math
import io
import re
import time as time_module
import requests
import hashlib
from supabase import create_client, Client

# --- 1. CONFIGURAZIONE ---
st.set_page_config(page_title="Giro Visite CRM Pro", layout="wide", page_icon="🚀")

# --- FUNZIONI PER PERSISTENZA SESSIONE ---
def generate_session_token(user_id, email):
    """Genera un token di sessione sicuro"""
    secret = "girovisitepro_secret_2024"  # In produzione usare un secret più sicuro
    data = f"{user_id}:{email}:{secret}"
    return hashlib.sha256(data.encode()).hexdigest()[:32]

def validate_session_token(user_id, email, token):
    """Valida il token di sessione"""
    expected_token = generate_session_token(user_id, email)
    return token == expected_token

def save_session_to_url(user_id, email):
    """Salva la sessione nei query params dell'URL"""
    token = generate_session_token(user_id, email)
    st.query_params["uid"] = user_id
    st.query_params["email"] = email
    st.query_params["token"] = token

def clear_session_from_url():
    """Rimuove la sessione dall'URL"""
    st.query_params.clear()

def restore_session_from_url():
    """Prova a recuperare la sessione dall'URL"""
    try:
        uid = st.query_params.get("uid")
        email = st.query_params.get("email")
        token = st.query_params.get("token")
        
        if uid and email and token:
            if validate_session_token(uid, email, token):
                return {"user_id": uid, "email": email}
    except:
        pass
    return None

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
        is_admin_user = email.lower() == ADMIN_EMAIL.lower()
        
        if is_admin_user:
            # Admin: accesso immediato
            data = {
                'user_id': user_id,
                'email': email,
                'status': 'active',
                'is_admin': True,
                'approved': True,
                'created_at': datetime.now().isoformat(),
                'subscription_start': today.isoformat()
            }
        else:
            # Nuovi utenti: in attesa di approvazione
            data = {
                'user_id': user_id,
                'email': email,
                'status': 'pending',  # In attesa di approvazione dall'admin
                'is_admin': False,
                'approved': False,
                'created_at': datetime.now().isoformat()
            }
        
        response = supabase.table('user_subscriptions').insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        st.error(f"Errore creazione abbonamento: {str(e)}")
        return None

def approve_user(user_id):
    """Approva un utente e avvia il periodo di prova"""
    try:
        today = datetime.now().date()
        update_data = {
            'status': 'trial',
            'approved': True,
            'trial_start': today.isoformat(),
            'trial_end': (today + timedelta(days=TRIAL_DAYS)).isoformat()
        }
        response = supabase.table('user_subscriptions').update(update_data).eq('user_id', user_id).execute()
        return True
    except Exception as e:
        st.error(f"Errore approvazione: {str(e)}")
        return False

def reject_user(user_id):
    """Rifiuta un utente"""
    try:
        update_data = {
            'status': 'blocked',
            'approved': False,
            'blocked_reason': 'Richiesta rifiutata'
        }
        response = supabase.table('user_subscriptions').update(update_data).eq('user_id', user_id).execute()
        return True
    except Exception as e:
        return False

def delete_user_account(user_id):
    """Elimina completamente un account utente"""
    try:
        # Elimina prima i clienti dell'utente
        supabase.table('clienti').delete().eq('user_id', user_id).execute()
        # Elimina la configurazione
        supabase.table('config_utente').delete().eq('user_id', user_id).execute()
        # Elimina l'abbonamento
        supabase.table('user_subscriptions').delete().eq('user_id', user_id).execute()
        return True
    except Exception as e:
        st.error(f"Errore eliminazione: {str(e)}")
        return False

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
    """Inizializza e recupera lo stato di autenticazione"""
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'session' not in st.session_state:
        st.session_state.session = None
    if 'subscription' not in st.session_state:
        st.session_state.subscription = None
    if 'auth_checked' not in st.session_state:
        st.session_state.auth_checked = False
    
    # Se non abbiamo un utente, proviamo a recuperare la sessione
    if st.session_state.user is None and not st.session_state.auth_checked:
        
        # METODO 1: Prova a recuperare dall'URL (persistenza tra refresh)
        url_session = restore_session_from_url()
        if url_session:
            try:
                # Recupera i dati dell'utente dal database
                subscription = get_user_subscription(url_session['user_id'], url_session['email'])
                
                if subscription:
                    can_access, message = check_subscription_status(subscription)
                    if can_access:
                        # Crea un oggetto user-like
                        class UserFromURL:
                            def __init__(self, uid, email):
                                self.id = uid
                                self.email = email
                        
                        st.session_state.user = UserFromURL(url_session['user_id'], url_session['email'])
                        st.session_state.subscription = subscription
                        st.session_state.auth_checked = True
                        return  # Sessione recuperata con successo!
            except Exception as e:
                pass
        
        # METODO 2: Prova Supabase (fallback)
        try:
            session_response = supabase.auth.get_session()
            
            if session_response and session_response.session:
                user = session_response.session.user
                if user:
                    subscription = get_user_subscription(user.id, user.email)
                    
                    if subscription:
                        can_access, message = check_subscription_status(subscription)
                        if can_access:
                            st.session_state.user = user
                            st.session_state.session = session_response.session
                            st.session_state.subscription = subscription
                            # Salva anche nell'URL per persistenza
                            save_session_to_url(user.id, user.email)
        except Exception as e:
            pass
        
        st.session_state.auth_checked = True

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
                            # Salva sessione nell'URL per persistenza
                            save_session_to_url(user.id, email)
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
        st.info(f"📝 **Registrati per richiedere l'accesso!**")
        st.caption("⏳ Dopo la registrazione, l'amministratore dovrà approvare il tuo account.")
        
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
                                # Crea account in attesa di approvazione
                                create_user_subscription(
                                    response.user.id, 
                                    new_email, 
                                    is_trial=True
                                )
                                
                                st.success(f"""
                                ✅ **Registrazione completata!**
                                
                                📧 Controlla la tua email per confermare l'account.
                                
                                ⏳ **Il tuo account è in attesa di approvazione.**
                                
                                Riceverai l'accesso quando l'amministratore approverà la tua richiesta.
                                Una volta approvato, avrai **{TRIAL_DAYS} giorni di prova gratuita**!
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
    # Pulisci sessione dall'URL
    clear_session_from_url()
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
    
    # === SEZIONE RICHIESTE IN ATTESA ===
    users_pending = [u for u in users if u['status'] == 'pending']
    
    if users_pending:
        st.divider()
        st.subheader(f"🔔 Richieste in Attesa ({len(users_pending)})")
        st.warning("⚠️ Questi utenti hanno richiesto l'accesso e sono in attesa di approvazione")
        
        for user in users_pending:
            with st.container(border=True):
                col1, col2, col3 = st.columns([3, 1, 1])
                
                with col1:
                    st.markdown(f"### 📧 {user['email']}")
                    created = user.get('created_at', '')[:10] if user.get('created_at') else 'N/D'
                    st.caption(f"📅 Registrato: {created}")
                
                with col2:
                    if st.button("✅ Approva", key=f"approve_{user['user_id']}", type="primary", use_container_width=True):
                        if approve_user(user['user_id']):
                            st.success(f"✅ {user['email']} approvato! Trial di {TRIAL_DAYS} giorni attivato.")
                            time_module.sleep(1)
                            st.rerun()
                
                with col3:
                    if st.button("❌ Rifiuta", key=f"reject_{user['user_id']}", use_container_width=True):
                        if reject_user(user['user_id']):
                            st.warning(f"🚫 {user['email']} rifiutato")
                            time_module.sleep(1)
                            st.rerun()
    
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
    
    st.subheader(f"📋 Tutti gli Utenti ({len(users_filtrati)})")
    
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
                    if status in ['pending']:
                        col_btn1, col_btn2 = st.columns(2)
                        with col_btn1:
                            if st.button("✅", key=f"appr_{user['user_id']}", help="Approva", use_container_width=True):
                                if approve_user(user['user_id']):
                                    st.success("✅ Approvato!")
                                    st.rerun()
                        with col_btn2:
                            if st.button("❌", key=f"rej_{user['user_id']}", help="Rifiuta", use_container_width=True):
                                if reject_user(user['user_id']):
                                    st.rerun()
                    
                    if status in ['expired', 'blocked']:
                        # Attiva con trial
                        if st.button("🎁 Attiva Trial", key=f"trial_{user['user_id']}", use_container_width=True):
                            if approve_user(user['user_id']):
                                st.success("✅ Trial attivato!")
                                st.rerun()
                    
                    # === GESTIONE ABBONAMENTO CON DATA ===
                    if status in ['trial', 'active', 'expired', 'blocked', 'pending']:
                        with st.expander("📅 Gestisci Abbonamento"):
                            # Mostra stato attuale
                            if status == 'trial' and user.get('trial_end'):
                                st.info(f"🎁 Trial fino al: **{user['trial_end']}**")
                            elif status == 'active' and user.get('subscription_end'):
                                st.info(f"✅ Abbonamento fino al: **{user['subscription_end']}**")
                            
                            # Data scadenza personalizzata
                            default_date = datetime.now().date() + timedelta(days=365)
                            if status == 'active' and user.get('subscription_end'):
                                try:
                                    se = user['subscription_end']
                                    default_date = datetime.strptime(se, '%Y-%m-%d').date() if isinstance(se, str) else se
                                except:
                                    pass
                            
                            nuova_scadenza = st.date_input(
                                "📅 Scadenza abbonamento:",
                                value=default_date,
                                min_value=datetime.now().date(),
                                key=f"sub_date_{user['user_id']}"
                            )
                            
                            if st.button("✅ Attiva/Prolunga Abbonamento", key=f"set_sub_{user['user_id']}", type="primary", use_container_width=True):
                                update_user_subscription(user['user_id'], {
                                    'status': 'active',
                                    'approved': True,
                                    'subscription_start': datetime.now().date().isoformat(),
                                    'subscription_end': nuova_scadenza.isoformat(),
                                    'blocked_reason': None
                                })
                                st.success(f"✅ Abbonamento attivo fino al {nuova_scadenza.strftime('%d/%m/%Y')}")
                                time_module.sleep(1)
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
                    
                    # ELIMINA ACCOUNT (sempre visibile)
                    st.divider()
                    with st.expander("🗑️ Elimina Account"):
                        st.warning(f"⚠️ Eliminare **{user['email']}** cancellerà tutti i suoi dati!")
                        conferma_email = st.text_input("Scrivi l'email per confermare:", key=f"del_conf_{user['user_id']}")
                        if conferma_email == user['email']:
                            if st.button("🗑️ ELIMINA DEFINITIVAMENTE", key=f"del_{user['user_id']}", type="primary"):
                                if delete_user_account(user['user_id']):
                                    st.success(f"✅ Account {user['email']} eliminato")
                                    time_module.sleep(1)
                                    st.rerun()
                        elif conferma_email:
                            st.error("❌ Email non corrisponde")
    
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
            
            # Converti colonne datetime
            if 'ultima_visita' in df.columns:
                df['ultima_visita'] = pd.to_datetime(df['ultima_visita'], errors='coerce')
            else:
                df['ultima_visita'] = pd.NaT
                
            if 'appuntamento' in df.columns:
                df['appuntamento'] = pd.to_datetime(df['appuntamento'], errors='coerce')
            else:
                df['appuntamento'] = pd.NaT
            
            # Converti coordinate
            if 'latitude' in df.columns:
                df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            else:
                df['latitude'] = 0.0
                
            if 'longitude' in df.columns:
                df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            else:
                df['longitude'] = 0.0
            
            # Frequenza giorni
            if 'frequenza_giorni' in df.columns:
                df['frequenza_giorni'] = pd.to_numeric(df['frequenza_giorni'], errors='coerce').fillna(30).astype(int)
            else:
                df['frequenza_giorni'] = 30
            
            # Campo visitare - IMPORTANTE per il giro
            if 'visitare' in df.columns:
                df['visitare'] = df['visitare'].fillna('SI').astype(str).str.upper().str.strip()
            else:
                df['visitare'] = 'SI'
            
            # Stato cliente
            if 'stato_cliente' in df.columns:
                df['stato_cliente'] = df['stato_cliente'].fillna('CLIENTE ATTIVO')
            else:
                df['stato_cliente'] = 'CLIENTE ATTIVO'
            
            # Città
            if 'citta' in df.columns:
                df['citta'] = df['citta'].fillna('')
            else:
                df['citta'] = ''
            
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

@st.cache_data(ttl=3600)  # Cache per 1 ora
def get_route_osrm(waypoints):
    """
    Ottiene il percorso stradale reale da OSRM (gratuito).
    waypoints: lista di tuple (lat, lon)
    Ritorna: lista di coordinate del percorso stradale
    """
    if len(waypoints) < 2:
        return waypoints
    
    try:
        # Formato OSRM: lon,lat;lon,lat;...
        coords_str = ";".join([f"{lon},{lat}" for lat, lon in waypoints])
        
        url = f"http://router.project-osrm.org/route/v1/driving/{coords_str}"
        params = {
            'overview': 'full',
            'geometries': 'geojson'
        }
        
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == 'Ok' and data.get('routes'):
                # Estrai le coordinate dal percorso GeoJSON
                geometry = data['routes'][0]['geometry']
                coords = geometry['coordinates']
                # GeoJSON è [lon, lat], convertiamo in [lat, lon] per Folium
                route_points = [(lat, lon) for lon, lat in coords]
                return route_points
        
        # Fallback: ritorna i waypoints originali (linee rette)
        return waypoints
    except Exception as e:
        # In caso di errore, usa linee rette
        return waypoints

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

# --- GPS COMPONENT (FUNZIONANTE CON STREAMLIT) ---
def render_gps_button(button_id, target_key="gps_coords"):
    """
    Componente GPS che comunica le coordinate a Streamlit tramite query params URL.
    Le coordinate vengono scritte nell'URL e lette da Streamlit al prossimo rerun.
    """
    html_code = f"""
    <div id="gps-container-{button_id}" style="width:100%; font-family: sans-serif;">
        <button id="btn-{button_id}" onclick="getLocation_{button_id}()" 
                style="padding:14px 24px; background:linear-gradient(135deg, #FF4B4B, #E63946); 
                       color:white; border:none; border-radius:10px; cursor:pointer; 
                       font-size:16px; width:100%; font-weight:700; 
                       box-shadow: 0 4px 12px rgba(230,57,70,0.3); transition: all 0.3s;">
            📍 Rileva Posizione GPS
        </button>
        <div id="status-{button_id}" style="margin-top:10px; font-size:14px; padding:10px; 
                                            border-radius:8px; text-align:center; display:none;"></div>
    </div>
    
    <script>
    function getLocation_{button_id}() {{
        const status = document.getElementById('status-{button_id}');
        const btn = document.getElementById('btn-{button_id}');
        status.style.display = 'block';
        
        if (!navigator.geolocation) {{
            status.innerHTML = '❌ Geolocalizzazione non supportata dal browser';
            status.style.backgroundColor = '#ffebee';
            status.style.color = '#c62828';
            return;
        }}
        
        btn.disabled = true;
        btn.style.opacity = '0.6';
        btn.innerHTML = '⏳ Acquisizione in corso...';
        status.innerHTML = '🔄 Attendo segnale GPS... (consenti l\\'accesso alla posizione)';
        status.style.backgroundColor = '#fff3e0';
        status.style.color = '#e65100';
        
        navigator.geolocation.getCurrentPosition(
            function(position) {{
                const lat = position.coords.latitude;
                const lon = position.coords.longitude;
                const acc = position.coords.accuracy;
                
                status.innerHTML = '✅ Posizione: ' + lat.toFixed(6) + ', ' + lon.toFixed(6) + ' (±' + Math.round(acc) + 'm)<br><b>Premi il pulsante qui sotto per confermare</b>';
                status.style.backgroundColor = '#e8f5e9';
                status.style.color = '#2e7d32';
                btn.innerHTML = '✅ Posizione Acquisita';
                btn.style.background = 'linear-gradient(135deg, #2e7d32, #4caf50)';
                
                // Scrivi coordinate nei query params dell'URL padre (Streamlit)
                const url = new URL(window.parent.location.href);
                url.searchParams.set('gps_lat', lat.toFixed(8));
                url.searchParams.set('gps_lon', lon.toFixed(8));
                url.searchParams.set('gps_acc', Math.round(acc).toString());
                url.searchParams.set('gps_ts', Date.now().toString());
                window.parent.history.replaceState(null, '', url.toString());
            }},
            function(error) {{
                let msg = '❌ ';
                switch(error.code) {{
                    case 1: msg += 'Permesso negato. Consenti la posizione nelle impostazioni del browser.'; break;
                    case 2: msg += 'Posizione non disponibile. Verifica che il GPS sia attivo.'; break;
                    case 3: msg += 'Timeout. Riprova in un luogo con migliore segnale GPS.'; break;
                    default: msg += 'Errore sconosciuto.';
                }}
                status.innerHTML = msg;
                status.style.backgroundColor = '#ffebee';
                status.style.color = '#c62828';
                btn.disabled = false;
                btn.style.opacity = '1';
                btn.innerHTML = '📍 Rileva Posizione GPS';
                btn.style.background = 'linear-gradient(135deg, #FF4B4B, #E63946)';
            }},
            {{ 
                enableHighAccuracy: true, 
                timeout: 30000, 
                maximumAge: 0 
            }}
        );
    }}
    </script>
    """
    return st.components.v1.html(html_code, height=130)

def read_gps_from_url():
    """Legge le coordinate GPS dai query params (scritti dal componente JS)"""
    try:
        lat = st.query_params.get("gps_lat")
        lon = st.query_params.get("gps_lon")
        acc = st.query_params.get("gps_acc")
        ts = st.query_params.get("gps_ts")
        
        if lat and lon:
            return {
                'latitude': float(lat),
                'longitude': float(lon),
                'accuracy': int(acc) if acc else None,
                'timestamp': int(ts) if ts else None
            }
    except (ValueError, TypeError):
        pass
    return None

def clear_gps_from_url():
    """Rimuove i dati GPS dall'URL mantenendo gli altri params"""
    for key in ['gps_lat', 'gps_lon', 'gps_acc', 'gps_ts']:
        if key in st.query_params:
            del st.query_params[key]

# --- 5. CALCOLO GIRO OTTIMIZZATO (v6 — ÀNCORA APPUNTAMENTI + CLUSTER GIORNALIERI) ---
def calcola_agenda_settimanale(df, config, esclusi=[], settimana_offset=0, variante=0):
    """
    ALGORITMO v6 — Semplice, diretto, efficace.
    
    PRINCIPIO: ogni giorno si costruisce DA ZERO partendo da un punto.
    
    PASSI:
      1. Filtra: escludi chi è stato visitato di recente (frequenza)
      2. Giorni CON appuntamento → l'appuntamento è l'ÀNCORA:
         si cercano i clienti più vicini all'appuntamento da TUTTO il pool
      3. Giorni SENZA appuntamento → nearest-neighbor dalla base
         attraverso i clienti RIMASTI nel pool
      4. 2-opt su ogni giorno
    
    NESSUNA catena master, NESSUN blocco, NESSUN taglio.
    Ogni giorno prende i clienti che gli servono dal pool condiviso.
    """
    if df.empty:
        return {}
    
    import random
    
    base_lat = float(config.get('lat_base', 41.9028))
    base_lon = float(config.get('lon_base', 12.4964))
    durata_visita = int(config.get('durata_visita', 45))
    giorni_lavorativi = config.get('giorni_lavorativi', [0, 1, 2, 3, 4])
    
    if isinstance(giorni_lavorativi, str):
        giorni_lavorativi = [int(x) for x in giorni_lavorativi.strip('{}').split(',')]
    
    # Ferie
    ferie_attive = config.get('attiva_ferie', False)
    ferie_inizio, ferie_fine = None, None
    if ferie_attive:
        try:
            fi, ff = config.get('ferie_inizio'), config.get('ferie_fine')
            if fi:
                ferie_inizio = datetime.strptime(str(fi)[:10], '%Y-%m-%d').date() if isinstance(fi, str) else (fi.date() if hasattr(fi, 'date') else fi)
            if ff:
                ferie_fine = datetime.strptime(str(ff)[:10], '%Y-%m-%d').date() if isinstance(ff, str) else (ff.date() if hasattr(ff, 'date') else ff)
        except:
            pass
    
    # Orari
    def get_time(val, default):
        if val is None: return default
        if isinstance(val, str):
            try: return datetime.strptime(val[:5], '%H:%M').time()
            except: return default
        return val if hasattr(val, 'hour') else default
    
    ora_inizio = get_time(config.get('h_inizio'), time(9, 0))
    ora_fine = get_time(config.get('h_fine'), time(18, 0))
    pausa_da = get_time(config.get('pausa_inizio'), time(13, 0))
    pausa_a = get_time(config.get('pausa_fine'), time(14, 0))
    
    oggi = ora_italiana.date()
    lunedi = oggi - timedelta(days=oggi.weekday()) + timedelta(weeks=settimana_offset)
    fine_settimana = lunedi + timedelta(days=6)
    
    agenda = {g: [] for g in range(7)}
    
    # ========================================
    # 1. RACCOGLI CLIENTI + PARSE APPUNTAMENTI
    # ========================================
    tutti = []
    for _, r in df.iterrows():
        if str(r.get('visitare', 'SI')).upper() != 'SI':
            continue
        if r['nome_cliente'] in esclusi:
            continue
        lat, lon = r.get('latitude'), r.get('longitude')
        if pd.isna(lat) or pd.isna(lon) or lat == 0 or lon == 0:
            continue
        
        citta = str(r.get('citta', '') or '').strip().upper() or 'ALTRO'
        freq = int(r.get('frequenza_giorni', 30))
        ultima = r.get('ultima_visita')
        
        # Calcolo urgenza e prossima visita
        if pd.isnull(ultima) or (hasattr(ultima, 'year') and ultima.year < 2001):
            giorni_ritardo = 999
            urgenza = 100.0
            prossima_visita = None
        else:
            ultima_date = ultima.date() if hasattr(ultima, 'date') else ultima
            if isinstance(ultima_date, str):
                try:
                    ultima_date = datetime.strptime(ultima_date[:10], '%Y-%m-%d').date()
                except:
                    ultima_date = oggi
            prossima_visita = ultima_date + timedelta(days=freq)
            giorni_ritardo = (lunedi - prossima_visita).days
            if giorni_ritardo >= 0:
                urgenza = min(100, 50 + (giorni_ritardo / max(freq, 1)) * 50)
            else:
                giorni_alla_scadenza = abs(giorni_ritardo)
                if giorni_alla_scadenza <= 7:
                    urgenza = 30 + (7 - giorni_alla_scadenza) * 3
                elif giorni_alla_scadenza <= 14:
                    urgenza = 15
                else:
                    urgenza = max(0, 10 - (giorni_alla_scadenza - 14))
        
        # Parse appuntamento (stringa o datetime)
        app_raw = r.get('appuntamento')
        app_parsed = None
        if pd.notna(app_raw):
            if hasattr(app_raw, 'date') and hasattr(app_raw, 'hour'):
                app_parsed = app_raw
            elif isinstance(app_raw, str) and app_raw.strip():
                s = app_raw.strip()
                for sl, fmt in [(16, '%Y-%m-%dT%H:%M'), (19, '%Y-%m-%dT%H:%M:%S'),
                                (19, '%Y-%m-%d %H:%M:%S'), (10, '%Y-%m-%d')]:
                    try:
                        app_parsed = datetime.strptime(s[:sl], fmt)
                        break
                    except:
                        continue
        
        flat, flon = float(lat), float(lon)
        tutti.append({
            'id': r['id'],
            'nome': r['nome_cliente'],
            'lat': flat, 'lon': flon,
            'ind': r.get('indirizzo', ''),
            'citta': citta,
            'cell': str(r.get('cellulare', '')),
            'app': app_parsed,
            'dist_base': haversine(base_lat, base_lon, flat, flon),
            'urgenza': urgenza,
            'giorni_ritardo': giorni_ritardo,
            'frequenza': freq,
            'prossima_visita': prossima_visita
        })
    
    if not tutti:
        return agenda
    
    # ========================================
    # 2. GIORNI DISPONIBILI
    # ========================================
    giorni_calcolo = []
    for g in giorni_lavorativi:
        data = lunedi + timedelta(days=g)
        in_ferie = ferie_attive and ferie_inizio and ferie_fine and ferie_inizio <= data <= ferie_fine
        if not in_ferie:
            giorni_calcolo.append(g)
    
    giorni = [g for g in giorni_calcolo
              if (settimana_offset > 0 or (lunedi + timedelta(days=g)) >= oggi)]
    
    if not giorni:
        return agenda
    
    # ========================================
    # 3. SEPARA APPUNTAMENTI DAL POOL
    # ========================================
    app_per_giorno = {}
    nomi_app = set()
    
    for c in tutti:
        app = c.get('app')
        if app is not None and hasattr(app, 'date'):
            data_app = app.date()
            if lunedi <= data_app <= lunedi + timedelta(days=6):
                g = data_app.weekday()
                if g not in app_per_giorno:
                    app_per_giorno[g] = []
                c['ora_app'] = app.strftime('%H:%M')
                c['is_app'] = True
                app_per_giorno[g].append(c)
                nomi_app.add(c['nome'])
    
    # ========================================
    # 4. FILTRA PER FREQUENZA (RIGOROSO)
    # ========================================
    # REGOLA: un cliente entra nel giro SOLO se:
    #   a) Non è mai stato visitato (prossima_visita = None) → prima visita
    #   b) La sua prossima_visita cade ENTRO questa settimana (scaduto o in scadenza)
    #
    # Se un cliente è stato visitato e la prossima visita è DOPO domenica,
    # NON entra nel giro → meglio giorni vuoti che visite anticipate.
    
    scaduti = []       # clienti con prossima_visita <= fine_settimana (da visitare)
    mai_visitati = []  # clienti mai visitati (prima visita necessaria)
    
    for c in tutti:
        if c['nome'] in nomi_app:
            continue  # gestito come appuntamento
        pv = c.get('prossima_visita')
        if pv is None:
            mai_visitati.append(c)
        elif pv <= fine_settimana:
            scaduti.append(c)
        # else: pv > fine_settimana → NON inserire, rispetta la frequenza
    
    # Per i mai visitati: non buttarli TUTTI nel pool.
    # Distribuiscili gradualmente nelle settimane usando il numero settimana.
    # Es: 60 mai visitati, cap 35 → settimana 1 prende i primi 35, settimana 2 i successivi.
    numero_settimana = lunedi.isocalendar()[1]
    
    # Ordina i mai visitati per distanza dalla base (stabile)
    mai_visitati.sort(key=lambda c: c['dist_base'])
    
    # Quanti slot rimangono dopo gli scaduti?
    ore = (datetime.combine(oggi, ora_fine) - datetime.combine(oggi, ora_inizio)).seconds / 3600
    pausa_ore = (datetime.combine(oggi, pausa_a) - datetime.combine(oggi, pausa_da)).seconds / 3600
    max_visite = max(4, min(10, int(ore - pausa_ore)))
    num_giorni_calc = len(giorni_calcolo)
    cap_settimana = max_visite * num_giorni_calc
    
    slot_per_mai_visitati = max(0, cap_settimana - len(scaduti))
    
    if mai_visitati and slot_per_mai_visitati > 0:
        # Dividi in blocchi e ruota per settimana
        n_blocchi = max(1, -(-len(mai_visitati) // slot_per_mai_visitati))
        blocco = numero_settimana % n_blocchi
        start = blocco * slot_per_mai_visitati
        mv_settimana = mai_visitati[start : start + slot_per_mai_visitati]
        # Wrap se blocco corto
        if len(mv_settimana) < slot_per_mai_visitati and len(mai_visitati) > slot_per_mai_visitati:
            mv_settimana += mai_visitati[:slot_per_mai_visitati - len(mv_settimana)]
    else:
        mv_settimana = []
    
    pool = scaduti + mv_settimana
    
    if not pool and not app_per_giorno:
        return agenda
    
    # ========================================
    # 6. VARIANTE (giro alternativo)
    # ========================================
    if variante > 0:
        random.seed(variante * 7919)
        random.shuffle(pool)
    
    # ========================================
    # 7. FUNZIONI HELPER
    # ========================================
    def nearest_neighbor_from(clienti, start_lat, start_lon, max_n):
        """Prendi i max_n clienti più vicini in ordine NN da un punto."""
        result = []
        remaining = list(clienti)
        pos_lat, pos_lon = start_lat, start_lon
        for _ in range(min(max_n, len(remaining))):
            if not remaining:
                break
            min_d = float('inf')
            best_idx = -1
            for idx, c in enumerate(remaining):
                d = haversine(pos_lat, pos_lon, c['lat'], c['lon'])
                if d < min_d:
                    min_d = d
                    best_idx = idx
            picked = remaining.pop(best_idx)
            result.append(picked)
            pos_lat, pos_lon = picked['lat'], picked['lon']
        return result, remaining
    
    def closest_to_point(clienti, lat, lon, max_n):
        """Prendi i max_n clienti più vicini a un punto (in linea d'aria)."""
        scored = [(haversine(lat, lon, c['lat'], c['lon']), c) for c in clienti]
        scored.sort(key=lambda x: x[0])
        selected = [c for _, c in scored[:max_n]]
        remaining = [c for _, c in scored[max_n:]]
        return selected, remaining
    
    def ottimizza_2opt(percorso, lat_start, lon_start):
        if len(percorso) < 3:
            return percorso
        
        def distanza_totale(p):
            if not p: return 0
            d = haversine(lat_start, lon_start, p[0]['lat'], p[0]['lon'])
            for i in range(len(p)-1):
                d += haversine(p[i]['lat'], p[i]['lon'], p[i+1]['lat'], p[i+1]['lon'])
            d += haversine(p[-1]['lat'], p[-1]['lon'], lat_start, lon_start)
            return d
        
        percorso = list(percorso)
        migliorato = True
        iterazioni = 0
        while migliorato and iterazioni < 100:
            migliorato = False
            dist_attuale = distanza_totale(percorso)
            for i in range(len(percorso) - 1):
                for j in range(i + 2, len(percorso)):
                    nuovo = percorso[:i+1] + percorso[i+1:j+1][::-1] + percorso[j+1:]
                    if distanza_totale(nuovo) < dist_attuale - 0.1:
                        percorso = nuovo
                        migliorato = True
                        break
                if migliorato:
                    break
            iterazioni += 1
        return percorso
    
    # ========================================
    # 8. COSTRUISCI IL GIRO GIORNO PER GIORNO
    # ========================================
    # PRIMA: giorni con appuntamento (l'appuntamento ÀNCORA il giro)
    # POI: giorni senza appuntamento (NN dalla base con pool rimanente)
    
    pool_rimanente = list(pool)
    risultati = {}
    
    # --- PRIMA PASSATA: giorni CON appuntamento ---
    giorni_con_app = [g for g in giorni_calcolo if g in app_per_giorno]
    
    for giorno in giorni_con_app:
        tappe_app = list(app_per_giorno[giorno])
        slot = max_visite - len(tappe_app)
        
        if slot > 0 and pool_rimanente:
            # Centro di gravità degli appuntamenti
            app_lat = sum(a['lat'] for a in tappe_app) / len(tappe_app)
            app_lon = sum(a['lon'] for a in tappe_app) / len(tappe_app)
            
            # Prendi i clienti più vicini all'appuntamento
            day_clients, pool_rimanente = closest_to_point(
                pool_rimanente, app_lat, app_lon, slot
            )
        else:
            day_clients = []
        
        # Unisci appuntamenti + clienti, ordina con 2-opt dalla base
        giro = tappe_app + day_clients
        if len(giro) >= 3:
            giro = ottimizza_2opt(giro, base_lat, base_lon)
        
        risultati[giorno] = giro
    
    # --- SECONDA PASSATA: giorni SENZA appuntamento ---
    # Costruiamo UNA catena continua dalla base attraverso TUTTI i clienti
    # rimasti, poi la tagliamo in segmenti giornalieri consecutivi.
    # Così giorno 1 = zona A, giorno 2 = zona B adiacente, etc.
    
    giorni_senza_app = [g for g in giorni_calcolo if g not in app_per_giorno]
    
    if pool_rimanente and giorni_senza_app:
        # Catena unica dalla base
        catena_completa, _ = nearest_neighbor_from(
            pool_rimanente, base_lat, base_lon, len(pool_rimanente)
        )
        
        # Taglia in segmenti giornalieri
        idx = 0
        for giorno in giorni_senza_app:
            segmento = catena_completa[idx : idx + max_visite]
            idx += len(segmento)
            
            # 2-opt sul segmento
            if len(segmento) >= 3:
                segmento = ottimizza_2opt(segmento, base_lat, base_lon)
            elif len(segmento) == 2:
                d0 = haversine(base_lat, base_lon, segmento[0]['lat'], segmento[0]['lon'])
                d1 = haversine(base_lat, base_lon, segmento[1]['lat'], segmento[1]['lon'])
                if d1 < d0:
                    segmento = [segmento[1], segmento[0]]
            
            risultati[giorno] = segmento
    else:
        for giorno in giorni_senza_app:
            risultati[giorno] = []
    
    # ========================================
    # 9. CALCOLO ORARI
    # ========================================
    risultati_finali = {}
    
    for giorno in giorni_calcolo:
        data_g = lunedi + timedelta(days=giorno)
        giro = risultati.get(giorno, [])
        
        tappe_finali = []
        pos_lat, pos_lon = base_lat, base_lon
        ora = datetime.combine(data_g, ora_inizio)
        
        for c in giro:
            dist = haversine(pos_lat, pos_lon, c['lat'], c['lon'])
            tempo = (dist / 40) * 60
            
            if c.get('is_app'):
                ora_arr = c.get('ora_app', '09:00')
            else:
                arrivo = ora + timedelta(minutes=tempo)
                if arrivo.time() >= pausa_da and arrivo.time() < pausa_a:
                    ora = datetime.combine(data_g, pausa_a)
                    arrivo = ora + timedelta(minutes=tempo)
                ora_arr = arrivo.strftime('%H:%M')
                ora = arrivo + timedelta(minutes=durata_visita)
            
            tappe_finali.append({
                'id': c['id'],
                'nome_cliente': c['nome'],
                'latitude': c['lat'],
                'longitude': c['lon'],
                'indirizzo': c.get('ind', ''),
                'cellulare': c.get('cell', ''),
                'ora_arrivo': ora_arr,
                'tipo_tappa': '📌 APPUNTAMENTO' if c.get('is_app') else '🚗 Giro',
                'distanza_km': round(dist, 1),
                'ritardo': c.get('giorni_ritardo', 0),
                'citta': c.get('citta', ''),
                'urgenza': c.get('urgenza', 0)
            })
            pos_lat, pos_lon = c['lat'], c['lon']
        
        risultati_finali[giorno] = tappe_finali
    
    for giorno in giorni:
        agenda[giorno] = risultati_finali.get(giorno, [])
    
    return agenda

def calcola_piano_giornaliero(df, giorno_settimana, config, esclusi=[], variante=0):
    """Restituisce il piano per il giorno corrente"""
    agenda = calcola_agenda_settimanale(df, config, esclusi, settimana_offset=0, variante=variante)
    return agenda.get(giorno_settimana, [])

# --- 6. MAIN APP ---
# --- 6. MAIN APP ---
def main_app():
    # Verifica che l'utente sia ancora valido
    if not st.session_state.user:
        st.session_state.auth_checked = False
        st.rerun()
        return
    
    # Refresh periodico della sessione (ogni 10 minuti circa)
    if 'last_session_check' not in st.session_state:
        st.session_state.last_session_check = datetime.now()
    
    time_since_check = (datetime.now() - st.session_state.last_session_check).seconds
    if time_since_check > 600:  # 10 minuti
        try:
            session_response = supabase.auth.get_session()
            if session_response and session_response.session:
                st.session_state.session = session_response.session
            st.session_state.last_session_check = datetime.now()
        except:
            pass
    
    # Verifica abbonamento
    subscription = st.session_state.get('subscription')
    user_is_admin = is_admin(st.session_state.user.id) if st.session_state.user else False
    
    # Inizializza navigazione PRIMA della sidebar
    if 'active_tab' not in st.session_state:
        st.session_state.active_tab = "🚀 Giro Oggi"
    
    # Sidebar con info utente + NAVIGAZIONE
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
        
        st.divider()
        
        # === MENU NAVIGAZIONE (nella sidebar) ===
        menu_keys =   ["🚀 Giro Oggi", "📊 Dashboard", "📅 Agenda", "🗺️ Mappa", "👤 Anagrafica", "➕ Nuovo", "⚙️ Config"]
        menu_labels = ["🚀 Giro Oggi", "📊 Dashboard", "📅 Agenda", "🗺️ Mappa", "👤 Anagrafica", "➕ Nuovo Cliente", "⚙️ Configurazione"]
        
        current_key = st.session_state.get('active_tab', "🚀 Giro Oggi")
        # Se siamo in Admin, il radio punta a indice 0 ma NON deve sovrascrivere
        in_admin = (current_key == "🔐 Admin")
        current_idx = menu_keys.index(current_key) if current_key in menu_keys else 0
        
        scelta = st.radio("Menu", menu_labels, index=current_idx, label_visibility="collapsed")
        nuovo_idx = menu_labels.index(scelta)
        if not in_admin and menu_keys[nuovo_idx] != st.session_state.active_tab:
            st.session_state.active_tab = menu_keys[nuovo_idx]
            st.rerun()
        elif in_admin and menu_keys[nuovo_idx] != "🚀 Giro Oggi":
            # L'utente ha cliccato una voce diversa dal radio → esci da Admin
            st.session_state.active_tab = menu_keys[nuovo_idx]
            st.rerun()
        
        st.divider()
        
        if st.button("🚪 Logout", use_container_width=True):
            logout()
        
        # Pulsante Admin
        if user_is_admin:
            st.divider()
            if st.button("🔐 Pannello Admin", use_container_width=True, type="primary"):
                st.session_state.active_tab = "🔐 Admin"
                st.rerun()
    
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
    
    config = st.session_state.config
    giorni_lavorativi = config.get('giorni_lavorativi', [0, 1, 2, 3, 4])
    if isinstance(giorni_lavorativi, str):
        giorni_lavorativi = [int(x) for x in giorni_lavorativi.strip('{}').split(',')]
    
    # --- TAB: GIRO OGGI ---
    if st.session_state.active_tab == "🚀 Giro Oggi":
        col_header, col_regen, col_refresh = st.columns([4, 1, 1])
        with col_header:
            st.header(f"📍 Giro di Oggi ({ora_italiana.strftime('%d/%m/%Y')})")
        with col_regen:
            if st.button("🔄 Rigenera", use_container_width=True, help="Propone un giro diverso"):
                st.session_state.variante_giro = st.session_state.get('variante_giro', 0) + 1
                st.rerun()
        with col_refresh:
            if st.button("🔃", use_container_width=True, help="Ricarica dati"):
                st.session_state.reload_data = True
                st.rerun()
        
        idx_g = ora_italiana.weekday()
        giorni_nomi = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
        
        # Inizializza esclusi_oggi se non esiste
        if 'esclusi_oggi' not in st.session_state:
            st.session_state.esclusi_oggi = []
        if 'variante_giro' not in st.session_state:
            st.session_state.variante_giro = 0
        
        # === PANNELLO GESTIONE GIRO ===
        with st.expander("⚙️ Gestisci Giro", expanded=False):
            
            # Info variante attuale
            variante_attuale = st.session_state.get('variante_giro', 0)
            if variante_attuale > 0:
                st.info(f"🔄 Giro rigenerato {variante_attuale} volta/e - Premi '🔄 Rigenera' per provare un altro percorso")
                if st.button("↩️ Torna al giro originale"):
                    st.session_state.variante_giro = 0
                    st.rerun()
            
            st.divider()
            
            # --- SEZIONE: Escludi Clienti ---
            st.write("**🚫 Escludi clienti dal giro di oggi:**")
            
            # Lista clienti attivi (da poter escludere)
            clienti_attivi = df[df['visitare'] == 'SI']['nome_cliente'].tolist() if not df.empty and 'visitare' in df.columns else []
            
            if clienti_attivi:
                # Multiselect per escludere clienti
                esclusi_selezionati = st.multiselect(
                    "Seleziona clienti da escludere:",
                    sorted(clienti_attivi),
                    default=st.session_state.esclusi_oggi,
                    key="escludi_clienti_select"
                )
                
                col_esc1, col_esc2 = st.columns(2)
                
                with col_esc1:
                    if st.button("🔄 Ricalcola Giro", type="primary", use_container_width=True):
                        st.session_state.esclusi_oggi = esclusi_selezionati
                        st.rerun()
                
                with col_esc2:
                    if st.button("🗑️ Rimuovi Esclusioni", use_container_width=True):
                        st.session_state.esclusi_oggi = []
                        st.rerun()
                
                if st.session_state.esclusi_oggi:
                    st.warning(f"⚠️ **{len(st.session_state.esclusi_oggi)} clienti esclusi** dal giro di oggi")
            else:
                st.info("Nessun cliente attivo da escludere")
        
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
            
            # Calcola tappe (con variante giro)
            variante = st.session_state.get('variante_giro', 0)
            tappe_oggi = calcola_piano_giornaliero(df, idx_g, config, st.session_state.esclusi_oggi, variante=variante)
            
            # Trova visitati fuori giro
            nomi_nel_giro = [t['nome_cliente'] for t in tappe_oggi]
            visitati_fuori_giro = [v for v in st.session_state.visitati_oggi if v not in nomi_nel_giro]
            
            if tappe_oggi or visitati_fuori_giro:
                # Statistiche compatte + pulsante mappa
                km_tot, tempo_guida, tempo_tot = calcola_km_tempo_giro(
                    tappe_oggi, 
                    config.get('lat_base', 41.9028), 
                    config.get('lon_base', 12.4964),
                    config.get('durata_visita', 45)
                )
                
                col_stats, col_mappa = st.columns([4, 1])
                with col_stats:
                    st.caption(f"📊 **{len(tappe_oggi)}** visite · ✅ **{len(st.session_state.visitati_oggi)}** fatte · 🛣️ **{km_tot}** km · ⏱️ **{tempo_tot//60}h{tempo_tot%60:02d}m**")
                with col_mappa:
                    if st.button("🗺️ Mappa", use_container_width=True, help="Vedi clienti del giorno sulla mappa"):
                        st.session_state.active_tab = "🗺️ Mappa"
                        st.rerun()
                
                st.divider()
                
                # === LISTA TAPPE ===
                for i, t in enumerate(tappe_oggi, 1):
                    visitato = t['nome_cliente'] in st.session_state.visitati_oggi
                    
                    # Dati completi del cliente
                    cliente_row = df[df['nome_cliente'] == t['nome_cliente']].iloc[0] if not df[df['nome_cliente'] == t['nome_cliente']].empty else None
                    
                    if 'cliente_report_aperto' not in st.session_state:
                        st.session_state.cliente_report_aperto = None
                    
                    if visitato:
                        # --- VISITATO ---
                        with st.container(border=True):
                            st.markdown(f"""
                            <div style="background: linear-gradient(90deg, #d4edda 0%, #c3e6cb 100%); 
                                        padding: 15px; border-radius: 10px; border-left: 5px solid #28a745;">
                                <span style="font-size: 24px;">✅</span>
                                <span style="font-size: 18px; margin-left: 10px; text-decoration: line-through; color: #155724;">
                                    {i}. {t['nome_cliente']}
                                </span>
                                <span style="float: right; color: #155724; font-weight: bold;">VISITATO</span>
                            </div>
                            """, unsafe_allow_html=True)
                            st.caption(f"📍 {t.get('indirizzo', '')}")
                    else:
                        # --- DA VISITARE ---
                        with st.container(border=True):
                            form_aperto = st.session_state.cliente_report_aperto == t['id']
                            
                            if not form_aperto:
                                # Badge urgenza
                                ritardo = t.get('ritardo', 0)
                                urgenza_score = t.get('urgenza', 0)
                                
                                if ritardo == 999 or urgenza_score >= 80:
                                    urgenza_badge = "🔴"
                                elif ritardo >= 7 or urgenza_score >= 50:
                                    urgenza_badge = "🟠"
                                elif ritardo >= 0 or urgenza_score >= 30:
                                    urgenza_badge = "🟡"
                                else:
                                    urgenza_badge = "🟢"
                                
                                # Info cliente — riga unica compatta
                                st.markdown(f"**{t['tipo_tappa'].split()[0]} {i}. {t['nome_cliente']}** — ⏰ {t['ora_arrivo']} · {urgenza_badge} {ritardo:+d}gg · {t.get('distanza_km', 0)}km")
                                
                                if t.get('indirizzo'):
                                    st.caption(f"📍 {t['indirizzo']}")
                                
                                # Promemoria
                                if cliente_row is not None and pd.notnull(cliente_row.get('promemoria')) and str(cliente_row.get('promemoria')).strip():
                                    st.warning(f"📝 **Promemoria:** {cliente_row['promemoria']}")
                                
                                # === PULSANTE VISITA ===
                                if st.button("✅ Registra Visita", key=f"visita_{t['id']}", type="primary", use_container_width=True):
                                    st.session_state.cliente_report_aperto = t['id']
                                    st.rerun()
                                
                                # === 4 PULSANTI AZIONE IN LINEA (HTML flex = sempre orizzontali su iPhone) ===
                                nav_url = f"https://www.google.com/maps/dir/?api=1&destination={t['latitude']},{t['longitude']}"
                                cell_val = str(t.get('cellulare', '')).strip()
                                tel_url = f"tel:{cell_val}" if cell_val else ""
                                mail_val = ""
                                if cliente_row is not None and pd.notnull(cliente_row.get('mail')):
                                    mail_val = str(cliente_row.get('mail', '')).strip()
                                mail_url = f"mailto:{mail_val}" if mail_val else ""
                                
                                btn_style = (
                                    "display:inline-flex;align-items:center;justify-content:center;"
                                    "padding:8px 4px;border-radius:8px;text-decoration:none;"
                                    "font-size:14px;font-weight:500;flex:1;text-align:center;"
                                    "min-height:38px;border:1px solid #ddd;color:#333;background:#f8f9fa;"
                                )
                                btn_disabled = btn_style + "opacity:0.35;pointer-events:none;color:#999;"
                                
                                html_btns = f'<div style="display:flex;gap:6px;margin:4px 0 2px 0;">'
                                html_btns += f'<a href="{nav_url}" target="_blank" style="{btn_style}">🚗 Vai</a>'
                                if tel_url:
                                    html_btns += f'<a href="{tel_url}" style="{btn_style}">📱 Chiama</a>'
                                else:
                                    html_btns += f'<span style="{btn_disabled}">📱 Chiama</span>'
                                if mail_url:
                                    html_btns += f'<a href="{mail_url}" style="{btn_style}">📧 Mail</a>'
                                else:
                                    html_btns += f'<span style="{btn_disabled}">📧 Mail</span>'
                                html_btns += '</div>'
                                st.markdown(html_btns, unsafe_allow_html=True)
                                
                                # Scheda cliente (richiede Streamlit per navigazione)
                                if st.button("👤 Scheda cliente", key=f"scheda_{t['id']}", use_container_width=True):
                                    st.session_state.cliente_selezionato = t['nome_cliente']
                                    st.session_state.active_tab = "👤 Anagrafica"
                                    st.rerun()
                            
                            else:
                                # FORM REPORT APERTO
                                st.markdown(f"### 📝 Report Visita: {t['nome_cliente']}")
                                st.caption(f"📍 {t.get('indirizzo', '')}")
                                
                                # Mostra storico precedente se presente
                                storico_attuale = ""
                                if cliente_row is not None and pd.notnull(cliente_row.get('storico_report')):
                                    storico_attuale = str(cliente_row.get('storico_report', ''))
                                    if storico_attuale.strip():
                                        with st.expander("📜 Storico report precedenti"):
                                            st.text(storico_attuale)
                                
                                # Form per nuovo report
                                nuovo_report = st.text_area(
                                    "✍️ Scrivi il report della visita:",
                                    placeholder="Es: Incontrato Mario Rossi, discusso nuovo ordine, richiesta preventivo per...",
                                    height=120,
                                    key=f"report_text_{t['id']}"
                                )
                                
                                col_save, col_skip, col_cancel = st.columns(3)
                                
                                with col_save:
                                    if st.button("💾 Salva e Completa", key=f"save_report_{t['id']}", type="primary", use_container_width=True):
                                        # Prepara nuovo storico con data
                                        data_oggi = ora_italiana.strftime('%d/%m/%Y')
                                        if nuovo_report.strip():
                                            nuovo_storico = f"[{data_oggi}] {nuovo_report.strip()}"
                                            if storico_attuale.strip():
                                                nuovo_storico = f"{nuovo_storico}\n\n{storico_attuale}"
                                        else:
                                            nuovo_storico = storico_attuale
                                        
                                        # Aggiorna database
                                        update_cliente(t['id'], {
                                            'ultima_visita': ora_italiana.date().isoformat(),
                                            'storico_report': nuovo_storico
                                        })
                                        st.session_state.visitati_oggi.append(t['nome_cliente'])
                                        st.session_state.cliente_report_aperto = None
                                        st.session_state.reload_data = True
                                        st.success("✅ Visita registrata con report!")
                                        time_module.sleep(0.5)
                                        st.rerun()
                                
                                with col_skip:
                                    if st.button("⏭️ Salta Report", key=f"skip_report_{t['id']}", use_container_width=True):
                                        # Salva senza report
                                        update_cliente(t['id'], {
                                            'ultima_visita': ora_italiana.date().isoformat()
                                        })
                                        st.session_state.visitati_oggi.append(t['nome_cliente'])
                                        st.session_state.cliente_report_aperto = None
                                        st.session_state.reload_data = True
                                        st.rerun()
                                
                                with col_cancel:
                                    if st.button("❌ Annulla", key=f"cancel_report_{t['id']}", use_container_width=True):
                                        st.session_state.cliente_report_aperto = None
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
        c2.metric("✅ Nel Giro", clienti_attivi)
        c3.metric("🔴 Critici", len(critici))
        c4.metric("🟠 Warning", len(warning))
        
        # === STATO VISITE CLIENTI ===
        st.divider()
        st.subheader("📊 Stato Visite Clienti")
        
        if not df.empty and 'visitare' in df.columns:
            df_attivi = df[df['visitare'] == 'SI'].copy()
            
            if not df_attivi.empty:
                oggi = ora_italiana.date()
                
                # Calcola ritardo per ogni cliente
                def calc_ritardo(row):
                    ultima = row.get('ultima_visita')
                    freq = int(row.get('frequenza_giorni', 30))
                    if pd.isnull(ultima):
                        return 999
                    ultima_date = ultima.date() if hasattr(ultima, 'date') else ultima
                    prossima = ultima_date + timedelta(days=freq)
                    return (oggi - prossima).days
                
                df_attivi['ritardo'] = df_attivi.apply(calc_ritardo, axis=1)
                
                # Conta per categoria
                mai_visitati = len(df_attivi[df_attivi['ritardo'] == 999])
                critici_count = len(df_attivi[(df_attivi['ritardo'] >= 14) & (df_attivi['ritardo'] != 999)])
                in_ritardo = len(df_attivi[(df_attivi['ritardo'] >= 1) & (df_attivi['ritardo'] < 14)])
                scadono_oggi = len(df_attivi[df_attivi['ritardo'] == 0])
                in_scadenza_7gg = len(df_attivi[(df_attivi['ritardo'] >= -7) & (df_attivi['ritardo'] < 0)])
                ok = len(df_attivi[df_attivi['ritardo'] < -7])
                
                # Mostra metriche
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.markdown("**🚨 Da visitare SUBITO:**")
                    st.error(f"🆕 Mai visitati: **{mai_visitati}**")
                    st.error(f"🔴 Critici (+14gg): **{critici_count}**")
                    st.warning(f"🟠 In ritardo (1-14gg): **{in_ritardo}**")
                
                with col2:
                    st.markdown("**📅 Questa settimana:**")
                    st.warning(f"🟡 Scadono oggi: **{scadono_oggi}**")
                    st.info(f"🔵 Scadono entro 7gg: **{in_scadenza_7gg}**")
                
                with col3:
                    st.markdown("**✅ OK:**")
                    st.success(f"🟢 Regolari: **{ok}**")
                    
                    # Totale da visitare questa settimana
                    totale_settimana = mai_visitati + critici_count + in_ritardo + scadono_oggi + in_scadenza_7gg
                    st.metric("📊 Da visitare questa settimana", totale_settimana)
        
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
        
        # Inizializza giorni in ferie (lista di date)
        if 'giorni_ferie_singoli' not in st.session_state:
            st.session_state.giorni_ferie_singoli = []
        
        # Inizializza stato per scambio giorni
        if 'giorno_da_scambiare' not in st.session_state:
            st.session_state.giorno_da_scambiare = None
        
        # Inizializza scambi salvati (dizionario: chiave=settimana, valore=lista di scambi)
        if 'scambi_giorni' not in st.session_state:
            st.session_state.scambi_giorni = {}
        
        col_nav1, col_nav2, col_nav3, col_nav4, col_nav5 = st.columns([1, 1, 2, 1, 1])
        
        with col_nav1:
            if st.button("⬅️ Sett. Prec.", use_container_width=True):
                st.session_state.current_week_index -= 1
                st.session_state.giorno_da_scambiare = None
                st.rerun()
        
        with col_nav2:
            # Pulsante per tornare alla settimana corrente (visibile solo se non siamo già lì)
            if st.session_state.current_week_index != 0:
                if st.button("🏠 Oggi", use_container_width=True, type="primary"):
                    st.session_state.current_week_index = 0
                    st.session_state.giorno_da_scambiare = None
                    st.rerun()
        
        with col_nav5:
            if st.button("Sett. Succ. ➡️", use_container_width=True):
                st.session_state.current_week_index += 1
                st.session_state.giorno_da_scambiare = None
                st.rerun()
        
        # Calcola date della settimana selezionata
        oggi = ora_italiana.date()
        lunedi_corrente = oggi - timedelta(days=oggi.weekday())
        lunedi_selezionato = lunedi_corrente + timedelta(weeks=st.session_state.current_week_index)
        domenica_selezionata = lunedi_selezionato + timedelta(days=6)
        
        with col_nav3:
            if st.session_state.current_week_index == 0:
                st.markdown(f"### 📆 Settimana Corrente")
            elif st.session_state.current_week_index > 0:
                st.markdown(f"### 📆 +{st.session_state.current_week_index} Settimana/e")
            else:
                st.markdown(f"### 📆 {st.session_state.current_week_index} Settimana/e")
            st.caption(f"Dal {lunedi_selezionato.strftime('%d/%m/%Y')} al {domenica_selezionata.strftime('%d/%m/%Y')}")
        
        # Info distribuzione clienti
        if not df.empty and 'visitare' in df.columns:
            clienti_attivi = len(df[df['visitare'] == 'SI'])
            # Stima settimane necessarie (circa 30-40 clienti a settimana)
            settimane_stimate = max(1, (clienti_attivi + 34) // 35)
            ciclo_attuale = (st.session_state.current_week_index // settimane_stimate) + 1
            settimana_nel_ciclo = (st.session_state.current_week_index % settimane_stimate) + 1
            st.info(f"📊 **{clienti_attivi} clienti** da visitare in **~{settimane_stimate} settimane** | Ciclo {ciclo_attuale}, Settimana {settimana_nel_ciclo}/{settimane_stimate}")
        
        # === PANNELLO DEBUG ===
        with st.expander("🔧 DEBUG - Verifica Configurazione Giro (Motore Portatour)", expanded=False):
            base_lat = float(config.get('lat_base', 0))
            base_lon = float(config.get('lon_base', 0))
            
            col_dbg1, col_dbg2 = st.columns(2)
            
            with col_dbg1:
                st.write("**📍 Punto di Partenza (BASE):**")
                if base_lat != 0 and base_lon != 0:
                    st.success(f"Lat: **{base_lat:.4f}** | Lon: **{base_lon:.4f}**")
                    st.caption("Se le coordinate sono sbagliate, vai in ⚙️ Config e reimpostale")
                else:
                    st.error("⚠️ COORDINATE BASE NON IMPOSTATE!")
                    st.caption("Vai in ⚙️ Config → Imposta punto di partenza")
            
            with col_dbg2:
                st.write("**⚙️ Parametri Giro (Portatour Engine):**")
                st.write(f"- Durata visita: **{config.get('durata_visita', 45)} min**")
                st.write(f"- Orario: **{str(config.get('h_inizio', '09:00'))[:5]} - {str(config.get('h_fine', '18:00'))[:5]}**")
                giorni_cfg = config.get('giorni_lavorativi', [0,1,2,3,4])
                if isinstance(giorni_cfg, str):
                    giorni_cfg = [int(x) for x in giorni_cfg.strip('{}').split(',')]
                nomi_g = ["Lun","Mar","Mer","Gio","Ven","Sab","Dom"]
                st.write(f"- Giorni: **{', '.join([nomi_g[g] for g in giorni_cfg])}**")
                st.write("- Algoritmo: **Clustering + Urgenza + 2-Opt**")
            
            st.divider()
            st.write("**🎯 Come funziona l'algoritmo v6:**")
            st.markdown("""
            1. **Filtro frequenza RIGOROSO** — Solo clienti scaduti o in scadenza questa settimana. Visitato 7gg fa con freq 30gg? Non compare per altre 3 settimane. Meglio giorni vuoti che visite anticipate.
            2. **Mai visitati graduali** — I clienti mai visitati vengono distribuiti nelle settimane, non tutti insieme.
            3. **Appuntamenti = ÀNCORA** — Giorni con appuntamento: il giro si riempie con i clienti più vicini all'appuntamento.
            4. **Giorni senza appuntamento** — Nearest-neighbor dalla base, segmenti consecutivi → clienti vicini = stesso giorno.
            5. **2-Opt** — Ogni percorso giornaliero è ottimizzato per eliminare zig-zag.
            """)
            
            st.divider()
            
            # Mostra i 10 clienti più vicini alla base
            if base_lat != 0 and base_lon != 0 and not df.empty:
                st.write("**🎯 TOP 10 Clienti più VICINI alla BASE:**")
                
                df_debug = df[
                    (df['visitare'] == 'SI') & 
                    (df['latitude'].notna()) & 
                    (df['longitude'].notna()) &
                    (df['latitude'] != 0) &
                    (df['longitude'] != 0)
                ].copy()
                
                if not df_debug.empty:
                    # Calcola distanza dalla base
                    df_debug['dist_base'] = df_debug.apply(
                        lambda r: haversine(base_lat, base_lon, float(r['latitude']), float(r['longitude'])), 
                        axis=1
                    )
                    
                    # Ordina per distanza
                    df_debug = df_debug.sort_values('dist_base')
                    
                    # Mostra top 10
                    for idx, (_, r) in enumerate(df_debug.head(10).iterrows(), 1):
                        citta = r.get('citta', '') or ''
                        st.write(f"{idx}. **{r['nome_cliente']}** - {citta} ({r['dist_base']:.1f} km)")
                    
                    st.divider()
                    st.write("**❌ TOP 5 Clienti più LONTANI (non dovrebbero essere nel primo giorno!):**")
                    for idx, (_, r) in enumerate(df_debug.tail(5).iterrows(), 1):
                        citta = r.get('citta', '') or ''
                        st.warning(f"{idx}. {r['nome_cliente']} - {citta} ({r['dist_base']:.1f} km)")
                else:
                    st.warning("Nessun cliente con coordinate valide")
        
        # Giorni lavorativi configurati (definiti prima per poterli usare nell'expander)
        giorni_nomi_full = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
        giorni_attivi = config.get('giorni_lavorativi', [0, 1, 2, 3, 4])
        if isinstance(giorni_attivi, str):
            giorni_attivi = [int(x) for x in giorni_attivi.strip('{}').split(',')]
        
        # === PANNELLO GESTIONE AGENDA ===
        with st.expander("⚙️ Gestisci Agenda", expanded=st.session_state.giorno_da_scambiare is not None):
            col_gest1, col_gest2 = st.columns(2)
            
            with col_gest1:
                st.write("**🔄 Scambia Giorni**")
                if st.session_state.giorno_da_scambiare:
                    st.info(f"📅 Selezionato: **{st.session_state.giorno_da_scambiare.strftime('%A %d/%m')}**")
                    st.caption("Ora clicca su un altro giorno per scambiare le visite")
                    if st.button("❌ Annulla Scambio"):
                        st.session_state.giorno_da_scambiare = None
                        st.rerun()
                else:
                    st.caption("Clicca '🔄' su un giorno per iniziare lo scambio")
                
                # Mostra scambi attivi per questa settimana
                chiave_settimana = lunedi_selezionato.isoformat()
                if chiave_settimana in st.session_state.scambi_giorni and st.session_state.scambi_giorni[chiave_settimana]:
                    st.divider()
                    st.write("**📋 Scambi attivi:**")
                    for idx1, idx2 in st.session_state.scambi_giorni[chiave_settimana]:
                        st.caption(f"🔄 {giorni_nomi_full[idx1][:3]} ↔️ {giorni_nomi_full[idx2][:3]}")
                    if st.button("🗑️ Annulla tutti gli scambi"):
                        st.session_state.scambi_giorni[chiave_settimana] = []
                        st.rerun()
            
            with col_gest2:
                st.write("**🏖️ Giorni in Ferie**")
                # Mostra giorni in ferie di questa settimana
                ferie_settimana = [d for d in st.session_state.giorni_ferie_singoli 
                                  if lunedi_selezionato <= d <= domenica_selezionata]
                if ferie_settimana:
                    for d in ferie_settimana:
                        col_f1, col_f2 = st.columns([3, 1])
                        col_f1.write(f"🏖️ {d.strftime('%A %d/%m')}")
                        if col_f2.button("🗑️", key=f"del_ferie_{d}"):
                            st.session_state.giorni_ferie_singoli.remove(d)
                            st.rerun()
                else:
                    st.caption("Nessun giorno in ferie. Clicca '🏖️' su un giorno per metterlo in ferie.")
        
        st.divider()
        
        # CALCOLA AGENDA OTTIMIZZATA (escludendo giorni in ferie singoli)
        agenda_settimana = calcola_agenda_settimanale(
            df, 
            config, 
            st.session_state.esclusi_oggi if st.session_state.current_week_index == 0 else [],
            st.session_state.current_week_index
        )
        
        # APPLICA SCAMBI SALVATI per questa settimana
        chiave_settimana = lunedi_selezionato.isoformat()
        if chiave_settimana in st.session_state.scambi_giorni:
            # Crea una copia dell'agenda originale
            agenda_originale = {k: list(v) for k, v in agenda_settimana.items()}
            
            # Applica tutti gli scambi
            for idx1, idx2 in st.session_state.scambi_giorni[chiave_settimana]:
                # Scambia usando i valori originali
                tappe1 = agenda_originale.get(idx1, [])
                tappe2 = agenda_originale.get(idx2, [])
                agenda_settimana[idx1] = tappe2
                agenda_settimana[idx2] = tappe1
                # Aggiorna anche l'originale per scambi successivi
                agenda_originale[idx1] = tappe2
                agenda_originale[idx2] = tappe1
        
        # Funzione per verificare se un giorno è in ferie (range O singolo)
        def is_giorno_ferie_agenda(data):
            # Prima controlla ferie singole
            if data in st.session_state.giorni_ferie_singoli:
                return True
            
            # Poi controlla range ferie
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
        
        # Crea colonne per i giorni lavorativi
        if giorni_attivi:
            cols_giorni = st.columns(len(giorni_attivi))
            
            totale_visite_settimana = 0
            totale_km_settimana = 0
            
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
                    
                    # === PULSANTI AZIONE GIORNO ===
                    col_btn1, col_btn2, col_btn3 = st.columns(3)
                    
                    with col_btn1:
                        # Pulsante SCAMBIA
                        if st.session_state.giorno_da_scambiare is None:
                            # Modalità selezione primo giorno
                            if st.button("🔄", key=f"swap_{data_giorno}", help="Scambia visite", use_container_width=True):
                                st.session_state.giorno_da_scambiare = data_giorno
                                st.rerun()
                        elif st.session_state.giorno_da_scambiare == data_giorno:
                            # Questo è il giorno selezionato
                            st.button("✅", key=f"swap_{data_giorno}", disabled=True, use_container_width=True)
                        else:
                            # Modalità selezione secondo giorno
                            if st.button("🔄➡️", key=f"swap_{data_giorno}", help=f"Scambia con {st.session_state.giorno_da_scambiare.strftime('%d/%m')}", use_container_width=True, type="primary"):
                                # Esegui scambio
                                giorno1 = st.session_state.giorno_da_scambiare
                                giorno2 = data_giorno
                                
                                # Calcola indici giorni
                                idx1 = giorno1.weekday()
                                idx2 = giorno2.weekday()
                                
                                # SALVA lo scambio in session_state
                                chiave_settimana = lunedi_selezionato.isoformat()
                                if chiave_settimana not in st.session_state.scambi_giorni:
                                    st.session_state.scambi_giorni[chiave_settimana] = []
                                
                                # Aggiungi lo scambio
                                st.session_state.scambi_giorni[chiave_settimana].append((idx1, idx2))
                                
                                st.session_state.giorno_da_scambiare = None
                                st.toast(f"✅ Scambio salvato: {giorni_nomi_full[idx1][:3]} ↔️ {giorni_nomi_full[idx2][:3]}")
                                time_module.sleep(0.3)
                                st.rerun()
                    
                    with col_btn2:
                        # Pulsante MAPPA - mostra giro del giorno sulla mappa
                        if tappe_giorno and not is_ferie:
                            if st.button("🗺️", key=f"mappa_{data_giorno}", help="Vedi su mappa", use_container_width=True):
                                # Salva le tappe del giorno per la mappa
                                st.session_state.mappa_giorno_selezionato = {
                                    'data': data_giorno,
                                    'tappe': tappe_giorno,
                                    'giorno_nome': giorni_nomi_full[giorno_idx]
                                }
                                st.session_state.active_tab = "🗺️ Mappa"
                                st.rerun()
                        else:
                            st.button("🗺️", key=f"mappa_{data_giorno}", disabled=True, use_container_width=True, help="Nessuna visita")
                    
                    with col_btn3:
                        # Pulsante FERIE
                        if is_ferie and data_giorno in st.session_state.giorni_ferie_singoli:
                            # È in ferie singolo - mostra pulsante per togliere
                            if st.button("🔙", key=f"ferie_{data_giorno}", help="Togli ferie", use_container_width=True):
                                st.session_state.giorni_ferie_singoli.remove(data_giorno)
                                st.rerun()
                        elif not is_ferie:
                            # Non è in ferie - mostra pulsante per mettere
                            if st.button("🏖️", key=f"ferie_{data_giorno}", help="Metti in ferie", use_container_width=True):
                                st.session_state.giorni_ferie_singoli.append(data_giorno)
                                st.rerun()
                        else:
                            # È in ferie da range - pulsante disabilitato
                            st.button("🏖️", key=f"ferie_{data_giorno}", disabled=True, use_container_width=True, help="In ferie (range)")
                    
                    st.divider()
                    
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
                                
                                # Mostra ritardo
                                ritardo = tappa.get('ritardo', 0)
                                if ritardo >= 14:
                                    st.caption(f"🔴 +{ritardo}gg")
                                elif ritardo >= 0:
                                    st.caption(f"🟡 +{ritardo}gg")
                                else:
                                    st.caption(f"🟢 {ritardo}gg")
                        
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
        
        # Inizializza stato mappa
        if 'mappa_giorno_selezionato' not in st.session_state:
            st.session_state.mappa_giorno_selezionato = None
        if 'mappa_cliente_cliccato' not in st.session_state:
            st.session_state.mappa_cliente_cliccato = None
        
        # ============================================
        # GEOLOCALIZZAZIONE BROWSER
        # ============================================
        # Usa le funzioni GPS già presenti nell'app
        
        if 'geo_lat' not in st.session_state:
            st.session_state.geo_lat = None
            st.session_state.geo_lon = None
        
        # Leggi GPS da query params (scritti dal componente JS)
        gps_data = read_gps_from_url()
        if gps_data:
            st.session_state.geo_lat = gps_data['latitude']
            st.session_state.geo_lon = gps_data['longitude']
        
        # === MAPPA GIRO DEL GIORNO (dall'Agenda) ===
        if st.session_state.mappa_giorno_selezionato:
            giorno_info = st.session_state.mappa_giorno_selezionato
            data_giorno = giorno_info['data']
            tappe = giorno_info['tappe']
            giorno_nome = giorno_info['giorno_nome']
            
            st.success(f"🗺️ **Giro di {giorno_nome} {data_giorno.strftime('%d/%m/%Y')}** - {len(tappe)} visite")
            
            if st.button("⬅️ Torna a tutti i clienti", use_container_width=True):
                st.session_state.mappa_giorno_selezionato = None
                st.session_state.mappa_cliente_cliccato = None
                st.rerun()
            
            if tappe:
                lat_center = sum(t['latitude'] for t in tappe) / len(tappe)
                lon_center = sum(t['longitude'] for t in tappe) / len(tappe)
                
                m = folium.Map(location=[lat_center, lon_center], zoom_start=12)
                
                # Posizione utente
                try:
                    from folium.plugins import LocateControl
                    LocateControl(auto_start=True, strings={"title": "La mia posizione"}).add_to(m)
                except:
                    pass
                
                # Marker posizione GPS se disponibile
                if st.session_state.geo_lat and st.session_state.geo_lon:
                    folium.Marker(
                        [st.session_state.geo_lat, st.session_state.geo_lon],
                        popup="📍 La mia posizione",
                        tooltip="📍 IO SONO QUI",
                        icon=folium.Icon(color='blue', icon='user', prefix='fa')
                    ).add_to(m)
                
                # Punto di partenza (base)
                lat_base = float(config.get('lat_base', lat_center))
                lon_base = float(config.get('lon_base', lon_center))
                folium.Marker(
                    [lat_base, lon_base],
                    popup="🏠 Partenza",
                    tooltip="🏠 BASE",
                    icon=folium.Icon(color='green', icon='home', prefix='fa')
                ).add_to(m)
                
                # Tappe numerate con tooltip (nome) e popup (dettagli)
                coords_percorso = [[lat_base, lon_base]]
                lookup_tappe = {}  # per match click
                
                for idx, tappa in enumerate(tappe, 1):
                    lat = tappa['latitude']
                    lon = tappa['longitude']
                    nome = tappa['nome_cliente']
                    indirizzo = tappa.get('indirizzo', '')
                    ora = tappa.get('ora_arrivo', '--:--')
                    ritardo = tappa.get('ritardo', 0)
                    dist_km = tappa.get('distanza_km', 0)
                    
                    if ritardo >= 14:
                        color = 'red'
                    elif ritardo >= 7:
                        color = 'orange'
                    elif ritardo >= 0:
                        color = 'blue'
                    else:
                        color = 'green'
                    
                    badge = '🔴' if ritardo >= 14 else '🟡' if ritardo >= 0 else '🟢'
                    
                    popup_html = f"""<div style="min-width:200px">
                    <b>{idx}. {nome}</b><br>
                    📍 {indirizzo}<br>
                    ⏰ Arrivo: {ora}<br>
                    🚗 {dist_km} km<br>
                    {badge} Ritardo: {ritardo}gg
                    </div>"""
                    
                    folium.Marker(
                        [lat, lon],
                        popup=folium.Popup(popup_html, max_width=280),
                        tooltip=f"{idx}. {nome}",
                        icon=folium.DivIcon(
                            html=f'<div style="font-size:12pt;color:white;background:{color};border-radius:50%;width:26px;height:26px;text-align:center;line-height:26px;font-weight:bold;border:2px solid white;box-shadow:0 1px 3px rgba(0,0,0,0.3);">{idx}</div>'
                        )
                    ).add_to(m)
                    
                    coords_percorso.append([lat, lon])
                    lookup_tappe[f"{lat:.6f},{lon:.6f}"] = tappa
                
                # Linea percorso
                coords_percorso.append([lat_base, lon_base])
                folium.PolyLine(coords_percorso, color='blue', weight=3, opacity=0.7, dash_array='10').add_to(m)
                
                # Mostra mappa e cattura click
                map_data = st_folium(m, width=None, height=500, use_container_width=True, key="mappa_giro")
                
                # Rileva click su marker
                clicked = map_data.get('last_object_clicked') if map_data else None
                if clicked:
                    click_lat = clicked.get('lat', 0)
                    click_lon = clicked.get('lng', 0)
                    
                    # Trova il cliente più vicino al punto cliccato
                    min_d = float('inf')
                    found = None
                    for t in tappe:
                        d = haversine(click_lat, click_lon, t['latitude'], t['longitude'])
                        if d < min_d:
                            min_d = d
                            found = t
                    
                    if found and min_d < 1:  # entro 1km = è il marker cliccato
                        st.session_state.mappa_cliente_cliccato = found['nome_cliente']
                
                # Mostra scheda del cliente cliccato
                if st.session_state.mappa_cliente_cliccato:
                    nome_click = st.session_state.mappa_cliente_cliccato
                    tappa_click = next((t for t in tappe if t['nome_cliente'] == nome_click), None)
                    
                    if tappa_click:
                        with st.container(border=True):
                            st.markdown(f"### 📍 {tappa_click['nome_cliente']}")
                            
                            info_parts = []
                            if tappa_click.get('indirizzo'):
                                info_parts.append(f"📍 {tappa_click['indirizzo']}")
                            if tappa_click.get('ora_arrivo'):
                                info_parts.append(f"⏰ Arrivo: {tappa_click['ora_arrivo']}")
                            if tappa_click.get('distanza_km'):
                                info_parts.append(f"🚗 {tappa_click['distanza_km']} km")
                            ritardo = tappa_click.get('ritardo', 0)
                            badge = '🔴' if ritardo >= 14 else '🟡' if ritardo >= 0 else '🟢'
                            info_parts.append(f"{badge} Ritardo: {ritardo}gg")
                            st.write(" · ".join(info_parts))
                            
                            # Pulsanti azione
                            nav_url = f"https://www.google.com/maps/dir/?api=1&destination={tappa_click['latitude']},{tappa_click['longitude']}"
                            cell = tappa_click.get('cellulare', '')
                            
                            btn_style = "display:inline-flex;align-items:center;justify-content:center;padding:8px 12px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:500;flex:1;text-align:center;min-height:38px;border:1px solid #ddd;color:#333;background:#f8f9fa;"
                            
                            html_btns = f'<div style="display:flex;gap:6px;margin:4px 0;">'
                            html_btns += f'<a href="{nav_url}" target="_blank" style="{btn_style}">🚗 Vai</a>'
                            if cell and cell.strip() and cell != 'nan':
                                html_btns += f'<a href="tel:{cell}" style="{btn_style}">📱 Chiama</a>'
                            html_btns += '</div>'
                            st.markdown(html_btns, unsafe_allow_html=True)
                            
                            if st.button("👤 Apri Scheda Cliente", key="apri_scheda_mappa_giro", type="primary", use_container_width=True):
                                st.session_state.cliente_selezionato = nome_click
                                st.session_state.active_tab = "👤 Anagrafica"
                                st.session_state.mappa_cliente_cliccato = None
                                st.rerun()
                
                # Lista tappe sotto la mappa
                st.divider()
                st.subheader("📋 Ordine Visite")
                for idx, tappa in enumerate(tappe, 1):
                    ritardo = tappa.get('ritardo', 0)
                    badge = "🔴" if ritardo >= 14 else "🟡" if ritardo >= 0 else "🟢"
                    with st.container(border=True):
                        st.markdown(f"**{idx}. {tappa['nome_cliente']}** — {tappa.get('indirizzo', '')}  \n{badge} {tappa.get('ora_arrivo', '--:--')} · 🚗 {tappa.get('distanza_km', 0)} km")
                        if st.button("👤 Scheda", key=f"giro_scheda_{tappa['id']}", use_container_width=True):
                            st.session_state.cliente_selezionato = tappa['nome_cliente']
                            st.session_state.active_tab = "👤 Anagrafica"
                            st.rerun()
            
            return  # Non mostrare la mappa normale
        
        # ============================================
        # MAPPA TUTTI I CLIENTI
        # ============================================
        if not df.empty:
            # --- Geolocalizzazione ---
            geo_lat = st.session_state.geo_lat
            geo_lon = st.session_state.geo_lon
            
            if geo_lat and geo_lon:
                st.success(f"📍 Posizione rilevata: {geo_lat:.4f}, {geo_lon:.4f}")
            else:
                render_gps_button("mappa_gps_btn")
            
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                filtro_stato = st.selectbox("📊 Stato:", ["Tutti", "Solo nel giro", "Fuori giro"], key="filtro_stato_mappa")
            with col_f2:
                if geo_lat:
                    raggio_km = st.slider("🎯 Raggio (km)", 1, 100, 30, key="raggio_mappa")
                else:
                    raggio_km = 100
            
            # Posizione manuale
            with st.expander("📍 Posizione manuale"):
                col_m1, col_m2, col_m3 = st.columns([2, 2, 1])
                with col_m1:
                    manual_lat = st.number_input("Latitudine", value=float(geo_lat or config.get('lat_base', 39.22)), format="%.6f", key="manual_lat")
                with col_m2:
                    manual_lon = st.number_input("Longitudine", value=float(geo_lon or config.get('lon_base', 9.12)), format="%.6f", key="manual_lon")
                with col_m3:
                    st.write("")
                    if st.button("📍 Usa", key="usa_manual"):
                        st.session_state.geo_lat = manual_lat
                        st.session_state.geo_lon = manual_lon
                        st.rerun()
                    if st.button("🏠 Base", key="usa_base"):
                        st.session_state.geo_lat = float(config.get('lat_base', 39.22))
                        st.session_state.geo_lon = float(config.get('lon_base', 9.12))
                        st.rerun()
            
            st.divider()
            
            # Filtra
            df_filtered = df.copy()
            if filtro_stato == "Solo nel giro":
                df_filtered = df_filtered[df_filtered['visitare'] == 'SI']
            elif filtro_stato == "Fuori giro":
                df_filtered = df_filtered[df_filtered['visitare'] != 'SI']
            
            df_filtered = df_filtered[
                (df_filtered['latitude'].notna()) & 
                (df_filtered['longitude'].notna()) &
                (df_filtered['latitude'] != 0) &
                (df_filtered['longitude'] != 0)
            ]
            
            # Calcola distanze dalla posizione
            pos_lat = geo_lat or float(config.get('lat_base', 39.22))
            pos_lon = geo_lon or float(config.get('lon_base', 9.12))
            
            df_filtered['distanza_km'] = df_filtered.apply(
                lambda row: haversine(pos_lat, pos_lon, row['latitude'], row['longitude']), axis=1
            )
            
            if geo_lat:
                df_filtered = df_filtered[df_filtered['distanza_km'] <= raggio_km]
            
            df_filtered = df_filtered.sort_values('distanza_km')
            
            st.write(f"📍 **{len(df_filtered)} clienti** nel raggio di {raggio_km} km")
            
            if not df_filtered.empty:
                # Costruisci mappa
                m = folium.Map(location=[pos_lat, pos_lon], zoom_start=12 if geo_lat else 9)
                
                # Locate control (pulsante GPS nativo nella mappa)
                try:
                    from folium.plugins import LocateControl
                    LocateControl(
                        auto_start=True,
                        strings={"title": "Mostra la mia posizione"}
                    ).add_to(m)
                except:
                    pass
                
                # Marker posizione utente
                folium.Marker(
                    [pos_lat, pos_lon],
                    popup="📍 La mia posizione",
                    tooltip="📍 IO SONO QUI",
                    icon=folium.Icon(color='blue', icon='user', prefix='fa')
                ).add_to(m)
                
                # Cerchio raggio
                if geo_lat:
                    folium.Circle(
                        [pos_lat, pos_lon],
                        radius=raggio_km * 1000,
                        color='blue', fill=True, fillOpacity=0.05, weight=1
                    ).add_to(m)
                
                # Marker clienti con tooltip (nome) e popup (dettagli)
                for _, row in df_filtered.iterrows():
                    lat_c = row['latitude']
                    lon_c = row['longitude']
                    nome_c = row['nome_cliente']
                    ind_c = row.get('indirizzo', '') or ''
                    dist_c = row.get('distanza_km', 0)
                    visitare = str(row.get('visitare', 'SI')).upper()
                    
                    # Colore: verde = nel giro, grigio = fuori giro
                    color = 'green' if visitare == 'SI' else 'lightgray'
                    
                    # Ritardo
                    ultima = row.get('ultima_visita')
                    freq = int(row.get('frequenza_giorni', 30))
                    if pd.isnull(ultima) or (hasattr(ultima, 'year') and ultima.year < 2001):
                        ritardo_str = "Mai visitato"
                        badge = "🔵"
                    else:
                        ultima_date = ultima.date() if hasattr(ultima, 'date') else ultima
                        prossima = ultima_date + timedelta(days=freq)
                        ritardo_gg = (ora_italiana.date() - prossima).days
                        if ritardo_gg > 0:
                            ritardo_str = f"In ritardo di {ritardo_gg}gg"
                            badge = "🔴"
                        elif ritardo_gg >= -7:
                            ritardo_str = f"Scade tra {abs(ritardo_gg)}gg"
                            badge = "🟡"
                        else:
                            ritardo_str = f"OK (tra {abs(ritardo_gg)}gg)"
                            badge = "🟢"
                    
                    popup_html = f"""<div style="min-width:180px;font-size:13px;">
                    <b>{nome_c}</b><br>
                    📍 {ind_c}<br>
                    🚗 {dist_c:.1f} km da te<br>
                    {badge} {ritardo_str}
                    </div>"""
                    
                    folium.Marker(
                        [lat_c, lon_c],
                        popup=folium.Popup(popup_html, max_width=250),
                        tooltip=f"{nome_c} ({dist_c:.1f}km)",
                        icon=folium.Icon(color=color, icon='briefcase', prefix='fa')
                    ).add_to(m)
                
                # Mostra mappa e cattura click
                map_data = st_folium(m, width=None, height=500, use_container_width=True, key="mappa_clienti")
                
                # Rileva click su marker
                clicked = map_data.get('last_object_clicked') if map_data else None
                if clicked:
                    click_lat = clicked.get('lat', 0)
                    click_lon = clicked.get('lng', 0)
                    
                    # Trova il cliente più vicino al punto cliccato
                    min_d = float('inf')
                    found_nome = None
                    for _, row in df_filtered.iterrows():
                        d = haversine(click_lat, click_lon, row['latitude'], row['longitude'])
                        if d < min_d:
                            min_d = d
                            found_nome = row['nome_cliente']
                    
                    if found_nome and min_d < 1:  # entro 1km
                        st.session_state.mappa_cliente_cliccato = found_nome
                
                # === SCHEDA CLIENTE CLICCATO ===
                if st.session_state.mappa_cliente_cliccato:
                    nome_sel = st.session_state.mappa_cliente_cliccato
                    cliente_row = df_filtered[df_filtered['nome_cliente'] == nome_sel]
                    
                    if not cliente_row.empty:
                        c = cliente_row.iloc[0]
                        with st.container(border=True):
                            st.markdown(f"### 📍 {c['nome_cliente']}")
                            
                            info = []
                            if c.get('indirizzo'):
                                info.append(f"📍 {c['indirizzo']}")
                            if c.get('citta'):
                                info.append(f"🏙️ {c['citta']}")
                            dist_c = c.get('distanza_km', 0)
                            info.append(f"🚗 {dist_c:.1f} km da te")
                            
                            ultima = c.get('ultima_visita')
                            if pd.notnull(ultima) and hasattr(ultima, 'strftime'):
                                info.append(f"📅 Ultima visita: {ultima.strftime('%d/%m/%Y')}")
                            else:
                                info.append("📅 Mai visitato")
                            
                            st.write(" · ".join(info))
                            
                            # Pulsanti azione (HTML flex per mobile)
                            nav_url = f"https://www.google.com/maps/dir/?api=1&destination={c['latitude']},{c['longitude']}"
                            cell_val = str(c.get('cellulare', '')) if pd.notna(c.get('cellulare')) else ''
                            mail_val = str(c.get('email', '')) if pd.notna(c.get('email')) else ''
                            
                            btn_s = "display:inline-flex;align-items:center;justify-content:center;padding:8px 12px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:500;flex:1;text-align:center;min-height:38px;border:1px solid #ddd;color:#333;background:#f8f9fa;"
                            btn_d = btn_s + "opacity:0.35;pointer-events:none;color:#999;"
                            
                            html_btns = '<div style="display:flex;gap:6px;margin:4px 0;">'
                            html_btns += f'<a href="{nav_url}" target="_blank" style="{btn_s}">🚗 Vai</a>'
                            html_btns += f'<a href="tel:{cell_val}" style="{btn_s}">📱 Chiama</a>' if cell_val and cell_val.strip() and cell_val != 'nan' else f'<span style="{btn_d}">📱 Chiama</span>'
                            html_btns += f'<a href="mailto:{mail_val}" style="{btn_s}">📧 Mail</a>' if mail_val and mail_val.strip() and mail_val != 'nan' else f'<span style="{btn_d}">📧 Mail</span>'
                            html_btns += '</div>'
                            st.markdown(html_btns, unsafe_allow_html=True)
                            
                            if st.button("👤 Apri Scheda Cliente", key="apri_scheda_mappa", type="primary", use_container_width=True):
                                st.session_state.cliente_selezionato = nome_sel
                                st.session_state.active_tab = "👤 Anagrafica"
                                st.session_state.mappa_cliente_cliccato = None
                                st.rerun()
                
                # === LISTA CLIENTI VICINI ===
                st.divider()
                st.subheader(f"📋 Clienti più vicini ({min(15, len(df_filtered))} di {len(df_filtered)})")
                
                for _, row in df_filtered.head(15).iterrows():
                    dist_c = row.get('distanza_km', 0)
                    nome_c = row['nome_cliente']
                    ind_c = row.get('indirizzo', '') or ''
                    
                    with st.container(border=True):
                        st.markdown(f"**{nome_c}** — 🚗 {dist_c:.1f} km  \n📍 {ind_c}")
                        
                        nav_url = f"https://www.google.com/maps/dir/?api=1&destination={row['latitude']},{row['longitude']}"
                        cell_v = str(row.get('cellulare', '')) if pd.notna(row.get('cellulare')) else ''
                        
                        btn_s = "display:inline-flex;align-items:center;justify-content:center;padding:8px 4px;border-radius:8px;text-decoration:none;font-size:13px;font-weight:500;flex:1;text-align:center;min-height:36px;border:1px solid #ddd;color:#333;background:#f8f9fa;"
                        btn_d = btn_s + "opacity:0.35;pointer-events:none;color:#999;"
                        
                        h = '<div style="display:flex;gap:5px;margin:2px 0;">'
                        h += f'<a href="{nav_url}" target="_blank" style="{btn_s}">🚗 Vai</a>'
                        h += f'<a href="tel:{cell_v}" style="{btn_s}">📱</a>' if cell_v and cell_v.strip() and cell_v != 'nan' else f'<span style="{btn_d}">📱</span>'
                        h += '</div>'
                        st.markdown(h, unsafe_allow_html=True)
                        
                        if st.button("👤 Scheda", key=f"lista_scheda_{row['id']}", use_container_width=True):
                            st.session_state.cliente_selezionato = nome_c
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
                    col_vis1, col_vis2, col_vis3, col_vis4 = st.columns(4)
                    
                    ultima = cliente.get('ultima_visita')
                    frequenza = int(cliente.get('frequenza_giorni', 30))
                    
                    if pd.notnull(ultima):
                        col_vis1.metric("📅 Ultima visita", ultima.strftime('%d/%m/%Y'))
                        # Calcola prossima visita
                        if hasattr(ultima, 'date'):
                            prossima = ultima.date() + timedelta(days=frequenza)
                        else:
                            prossima = ultima + timedelta(days=frequenza)
                        
                        oggi_date = ora_italiana.date()
                        giorni_mancanti = (prossima - oggi_date).days
                        
                        if giorni_mancanti < 0:
                            col_vis2.metric("📆 Prossima visita", prossima.strftime('%d/%m/%Y'), f"🔴 {abs(giorni_mancanti)} gg fa!")
                        elif giorni_mancanti == 0:
                            col_vis2.metric("📆 Prossima visita", "OGGI", "🟡 Scade oggi!")
                        elif giorni_mancanti <= 7:
                            col_vis2.metric("📆 Prossima visita", prossima.strftime('%d/%m/%Y'), f"🟠 tra {giorni_mancanti} gg")
                        else:
                            col_vis2.metric("📆 Prossima visita", prossima.strftime('%d/%m/%Y'), f"🟢 tra {giorni_mancanti} gg")
                    else:
                        col_vis1.metric("📅 Ultima visita", "Mai")
                        col_vis2.metric("📆 Prossima visita", "ASAP", "🔴 Mai visitato!")
                    
                    col_vis3.metric("🔄 Frequenza", f"{frequenza} giorni")
                    
                    # Toggle rapido per Nel Giro
                    visitare_attuale = str(cliente.get('visitare', 'SI')).upper().strip()
                    is_nel_giro = visitare_attuale == 'SI'
                    
                    with col_vis4:
                        st.metric("🚗 Nel giro", "✅ SI" if is_nel_giro else "❌ NO")
                        # Pulsante toggle
                        if is_nel_giro:
                            if st.button("❌ Togli dal giro", key=f"toggle_giro_{cliente['id']}", use_container_width=True):
                                update_cliente(cliente['id'], {'visitare': 'NO'})
                                st.session_state.reload_data = True
                                st.rerun()
                        else:
                            if st.button("✅ Metti nel giro", key=f"toggle_giro_{cliente['id']}", use_container_width=True, type="primary"):
                                update_cliente(cliente['id'], {'visitare': 'SI'})
                                st.session_state.reload_data = True
                                st.rerun()
                    
                    # === SEZIONE APPUNTAMENTO ===
                    st.divider()
                    
                    appuntamento_attuale = cliente.get('appuntamento')
                    
                    col_app1, col_app2 = st.columns([2, 1])
                    
                    with col_app1:
                        if pd.notnull(appuntamento_attuale):
                            # Mostra appuntamento esistente
                            if hasattr(appuntamento_attuale, 'strftime'):
                                app_data = appuntamento_attuale.strftime('%d/%m/%Y')
                                app_ora = appuntamento_attuale.strftime('%H:%M')
                            else:
                                app_data = str(appuntamento_attuale)[:10]
                                app_ora = str(appuntamento_attuale)[11:16] if len(str(appuntamento_attuale)) > 10 else "00:00"
                            
                            st.success(f"📌 **APPUNTAMENTO FISSATO:** {app_data} alle **{app_ora}**")
                            st.caption("⚡ Questo cliente avrà la priorità nel giro del giorno dell'appuntamento")
                        else:
                            st.info("📌 Nessun appuntamento fissato")
                    
                    with col_app2:
                        if pd.notnull(appuntamento_attuale):
                            if st.button("🗑️ Rimuovi Appuntamento", key=f"rimuovi_app_{cliente['id']}", use_container_width=True):
                                update_cliente(cliente['id'], {'appuntamento': None})
                                st.session_state.reload_data = True
                                st.success("✅ Appuntamento rimosso!")
                                st.rerun()
                    
                    # Form per nuovo appuntamento
                    with st.expander("📅 Fissa Nuovo Appuntamento", expanded=not pd.notnull(appuntamento_attuale)):
                        col_data_app, col_ora_app = st.columns(2)
                        
                        with col_data_app:
                            # Default: domani
                            data_default = ora_italiana.date() + timedelta(days=1)
                            data_appuntamento = st.date_input(
                                "📆 Data appuntamento:",
                                value=data_default,
                                min_value=ora_italiana.date(),
                                key=f"data_app_{cliente['id']}"
                            )
                        
                        with col_ora_app:
                            ora_appuntamento = st.time_input(
                                "⏰ Ora appuntamento:",
                                value=time(10, 0),
                                key=f"ora_app_{cliente['id']}"
                            )
                        
                        if st.button("📌 FISSA APPUNTAMENTO", type="primary", use_container_width=True, key=f"fissa_app_{cliente['id']}"):
                            # Combina data e ora
                            appuntamento_datetime = datetime.combine(data_appuntamento, ora_appuntamento)
                            
                            update_cliente(cliente['id'], {'appuntamento': appuntamento_datetime.isoformat()})
                            st.session_state.reload_data = True
                            st.success(f"✅ Appuntamento fissato per il {data_appuntamento.strftime('%d/%m/%Y')} alle {ora_appuntamento.strftime('%H:%M')}!")
                            st.rerun()
                    
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
                    with st.form(f"edit_cliente_{cliente['id']}"):
                        c1, c2 = st.columns(2)
                        
                        nome = c1.text_input("Nome", cliente['nome_cliente'], key=f"nome_{cliente['id']}")
                        indirizzo = c1.text_input("Indirizzo", cliente.get('indirizzo', ''), key=f"indirizzo_{cliente['id']}")
                        citta = c1.text_input("Città", cliente.get('citta', ''), key=f"citta_{cliente['id']}")
                        cap = c1.text_input("CAP", cliente.get('cap', ''), key=f"cap_{cliente['id']}")
                        provincia = c1.text_input("Provincia", cliente.get('provincia', ''), key=f"provincia_{cliente['id']}")
                        frequenza = c1.number_input("Frequenza (gg)", value=int(cliente.get('frequenza_giorni', 30)), key=f"freq_{cliente['id']}")
                        
                        stati_cliente = ["CLIENTE ATTIVO", "CLIENTE NUOVO", "CLIENTE POSSIBILE", "CLIENTE PROBABILE"]
                        stato_attuale = cliente.get('stato_cliente', 'CLIENTE ATTIVO')
                        if stato_attuale not in stati_cliente:
                            stato_attuale = 'CLIENTE ATTIVO'
                        stato_cliente = c1.selectbox("📊 Stato", stati_cliente, index=stati_cliente.index(stato_attuale), key=f"stato_{cliente['id']}")
                        
                        # Fix: normalizza il valore visitare
                        visitare_attuale = str(cliente.get('visitare', 'SI')).upper().strip()
                        visitare_index = 0 if visitare_attuale == 'SI' else 1
                        visitare = c1.selectbox("🚗 Nel Giro?", ["SI", "NO"], index=visitare_index, key=f"visitare_{cliente['id']}")
                        
                        telefono = c2.text_input("Telefono", cliente.get('telefono', ''), key=f"tel_{cliente['id']}")
                        cellulare = c2.text_input("Cellulare", cliente.get('cellulare', ''), key=f"cell_{cliente['id']}")
                        mail = c2.text_input("Email", cliente.get('mail', ''), key=f"mail_{cliente['id']}")
                        contatto = c2.text_input("Referente", cliente.get('contatto', ''), key=f"contatto_{cliente['id']}")
                        
                        latitudine = c2.number_input("Latitudine", value=float(lat_attuale), format="%.6f", key=f"lat_{cliente['id']}")
                        longitudine = c2.number_input("Longitudine", value=float(lon_attuale), format="%.6f", key=f"lon_{cliente['id']}")
                        
                        note = st.text_area("Note", cliente.get('note', ''), height=80, key=f"note_{cliente['id']}")
                        storico = st.text_area("Storico Report", cliente.get('storico_report', ''), height=120, key=f"storico_{cliente['id']}")
                        
                        if st.form_submit_button("💾 Salva Modifiche", use_container_width=True, type="primary"):
                            update_data = {
                                'nome_cliente': nome,
                                'indirizzo': indirizzo,
                                'citta': citta,
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
                            }
                            
                            if update_cliente(cliente['id'], update_data):
                                st.session_state.reload_data = True
                                st.success(f"✅ Salvato! Nel giro: {visitare}")
                                time_module.sleep(0.5)
                                st.rerun()
                            else:
                                st.error("❌ Errore nel salvataggio")
                
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
        
        # Inizializza campi in session_state se non esistono
        if 'nuovo_cliente_indirizzo' not in st.session_state:
            st.session_state.nuovo_cliente_indirizzo = ''
        if 'nuovo_cliente_cap' not in st.session_state:
            st.session_state.nuovo_cliente_cap = ''
        if 'nuovo_cliente_citta' not in st.session_state:
            st.session_state.nuovo_cliente_citta = ''
        if 'nuovo_cliente_provincia' not in st.session_state:
            st.session_state.nuovo_cliente_provincia = ''
        if 'nuovo_cliente_lat' not in st.session_state:
            st.session_state.nuovo_cliente_lat = None
        if 'nuovo_cliente_lon' not in st.session_state:
            st.session_state.nuovo_cliente_lon = None
        
        # === SEZIONE GPS ===
        st.subheader("📍 Posizione GPS")
        st.caption("Usa il GPS del dispositivo oppure incolla le coordinate da Google Maps")
        
        # Controlla se ci sono coordinate GPS dai query params
        gps_data = read_gps_from_url()
        if gps_data and 'gps_acquisito_nuovo' not in st.session_state:
            st.session_state.gps_acquisito_nuovo = True
            # Reverse geocoding per ottenere indirizzo
            addr = reverse_geocode(gps_data['latitude'], gps_data['longitude'])
            if addr:
                st.session_state.nuovo_cliente_indirizzo = addr.get('via', '')
                st.session_state.nuovo_cliente_cap = addr.get('cap', '')
                st.session_state.nuovo_cliente_citta = addr.get('citta', '')
                st.session_state.nuovo_cliente_provincia = addr.get('provincia', '')
            st.session_state.nuovo_cliente_lat = gps_data['latitude']
            st.session_state.nuovo_cliente_lon = gps_data['longitude']
            clear_gps_from_url()
            st.rerun()
        
        col_gps1, col_gps2 = st.columns([1, 1])
        
        with col_gps1:
            # Pulsante GPS nativo del browser
            render_gps_button("nuovo_cliente")
            if st.button("🔄 Conferma posizione GPS", use_container_width=True, 
                         help="Dopo aver premuto 'Rileva GPS', premi qui per caricare la posizione"):
                gps_check = read_gps_from_url()
                if gps_check:
                    with st.spinner("🔄 Ricerca indirizzo..."):
                        addr = reverse_geocode(gps_check['latitude'], gps_check['longitude'])
                    if addr:
                        st.session_state.nuovo_cliente_indirizzo = addr.get('via', '')
                        st.session_state.nuovo_cliente_cap = addr.get('cap', '')
                        st.session_state.nuovo_cliente_citta = addr.get('citta', '')
                        st.session_state.nuovo_cliente_provincia = addr.get('provincia', '')
                    st.session_state.nuovo_cliente_lat = gps_check['latitude']
                    st.session_state.nuovo_cliente_lon = gps_check['longitude']
                    clear_gps_from_url()
                    st.success("✅ Posizione GPS acquisita!")
                    st.rerun()
                else:
                    st.warning("⚠️ Premi prima '📍 Rileva Posizione GPS' e poi questo pulsante")

        with col_gps2:
            # Input manuale coordinate (può essere compilato da GPS o manualmente)
            coords_input = st.text_input(
                "📍 Oppure incolla coordinate (lat, lon):",
                placeholder="Es: 45.4642, 9.1900 - Da Google Maps",
                key="coords_input_nuovo"
            )
            if st.button("🔍 Cerca Indirizzo da Coordinate", use_container_width=True, type="primary"):
                if coords_input:
                    try:
                        parts = coords_input.replace(" ", "").split(",")
                        lat = float(parts[0])
                        lon = float(parts[1])
                        
                        with st.spinner("🔄 Ricerca indirizzo..."):
                            addr = reverse_geocode(lat, lon)
                        
                        if addr:
                            st.session_state.nuovo_cliente_indirizzo = addr.get('via', '')
                            st.session_state.nuovo_cliente_cap = addr.get('cap', '')
                            st.session_state.nuovo_cliente_citta = addr.get('citta', '')
                            st.session_state.nuovo_cliente_provincia = addr.get('provincia', '')
                            st.session_state.nuovo_cliente_lat = lat
                            st.session_state.nuovo_cliente_lon = lon
                            st.success("✅ Indirizzo trovato!")
                            st.rerun()
                        else:
                            st.error("❌ Indirizzo non trovato per queste coordinate")
                    except:
                        st.error("❌ Formato non valido. Usa: latitudine, longitudine")
                else:
                    st.warning("⚠️ Inserisci le coordinate")
        
        # Istruzioni per ottenere coordinate
        with st.expander("💡 Come ottenere le coordinate"):
            st.markdown("""
            **Metodo 1 - GPS automatico (da smartphone):**
            1. Premi **📍 Rileva Posizione GPS** qui sopra
            2. Consenti l'accesso alla posizione
            3. Premi **🔄 Conferma posizione GPS**
            
            **Metodo 2 - Da Google Maps (smartphone o PC):**
            1. Apri **Google Maps**
            2. Tieni premuto sulla posizione esatta
            3. Tocca/clicca sulle coordinate che appaiono
            4. Incollale nel campo "Coordinate"
            5. Premi **🔍 Cerca Indirizzo**
            """)
        
        # Mostra indirizzo trovato
        if st.session_state.nuovo_cliente_lat:
            st.success(f"""
            📍 **Posizione acquisita:**
            - Via: {st.session_state.nuovo_cliente_indirizzo}
            - Città: {st.session_state.nuovo_cliente_citta}
            - CAP: {st.session_state.nuovo_cliente_cap}
            - Provincia: {st.session_state.nuovo_cliente_provincia}
            - Coordinate: {st.session_state.nuovo_cliente_lat:.6f}, {st.session_state.nuovo_cliente_lon:.6f}
            """)
            
            if st.button("🗑️ Cancella posizione"):
                st.session_state.nuovo_cliente_indirizzo = ''
                st.session_state.nuovo_cliente_cap = ''
                st.session_state.nuovo_cliente_citta = ''
                st.session_state.nuovo_cliente_provincia = ''
                st.session_state.nuovo_cliente_lat = None
                st.session_state.nuovo_cliente_lon = None
                st.rerun()
        
        st.divider()
        
        # === FORM DATI CLIENTE ===
        st.subheader("📝 Dati Cliente")
        
        with st.form("nuovo_cliente_form"):
            c1, c2 = st.columns(2)
            
            nome = c1.text_input("Nome Cliente *")
            indirizzo = c1.text_input("Indirizzo", value=st.session_state.nuovo_cliente_indirizzo)
            cap = c1.text_input("CAP", value=st.session_state.nuovo_cliente_cap)
            citta = c1.text_input("Città *", value=st.session_state.nuovo_cliente_citta)
            provincia = c1.text_input("Provincia", value=st.session_state.nuovo_cliente_provincia)
            frequenza = c1.number_input("Frequenza visite (gg)", value=30)
            
            telefono = c2.text_input("Telefono")
            cellulare = c2.text_input("Cellulare")
            mail = c2.text_input("Email")
            contatto = c2.text_input("Referente")
            note = c2.text_area("Note")
            
            # Mostra coordinate se acquisite da GPS
            if st.session_state.nuovo_cliente_lat:
                c2.info(f"📍 Coordinate GPS: {st.session_state.nuovo_cliente_lat:.6f}, {st.session_state.nuovo_cliente_lon:.6f}")
            
            if st.form_submit_button("✅ Crea Cliente", use_container_width=True, type="primary"):
                if nome and citta:
                    # Usa coordinate GPS se disponibili, altrimenti geocoding
                    if st.session_state.nuovo_cliente_lat and st.session_state.nuovo_cliente_lon:
                        coords = (st.session_state.nuovo_cliente_lat, st.session_state.nuovo_cliente_lon)
                    else:
                        coords = get_coords(f"{indirizzo}, {citta}, {provincia}")
                        if not coords:
                            coords = get_coords(citta)
                    
                    if coords:
                        save_cliente({
                            'nome_cliente': nome,
                            'indirizzo': indirizzo,
                            'citta': citta,
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
                            'visitare': 'SI',
                            'stato_cliente': 'CLIENTE NUOVO'
                        })
                        
                        # Reset campi GPS
                        st.session_state.nuovo_cliente_indirizzo = ''
                        st.session_state.nuovo_cliente_cap = ''
                        st.session_state.nuovo_cliente_citta = ''
                        st.session_state.nuovo_cliente_provincia = ''
                        st.session_state.nuovo_cliente_lat = None
                        st.session_state.nuovo_cliente_lon = None
                        
                        st.session_state.reload_data = True
                        st.success(f"✅ Cliente {nome} creato!")
                        time_module.sleep(1)
                        st.rerun()
                    else:
                        st.error("❌ Impossibile trovare le coordinate. Usa il GPS o verifica l'indirizzo.")
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
        
        # Controlla se ci sono coordinate GPS dai query params (per la base)
        gps_data_config = read_gps_from_url()
        if gps_data_config:
            with st.spinner("🔄 Aggiornamento posizione base da GPS..."):
                addr_info = reverse_geocode(gps_data_config['latitude'], gps_data_config['longitude'])
                citta_nome = addr_info['citta'] if addr_info and addr_info.get('citta') else "Posizione GPS"
            
            config['citta_base'] = citta_nome
            config['lat_base'] = gps_data_config['latitude']
            config['lon_base'] = gps_data_config['longitude']
            save_config(config)
            st.session_state.config = config
            clear_gps_from_url()
            st.success(f"✅ Posizione base aggiornata via GPS: {citta_nome}")
            st.rerun()
        
        # Opzione 0: GPS
        with st.expander("📍 Usa GPS per impostare posizione base"):
            render_gps_button("config_base")
            if st.button("🔄 Conferma posizione GPS come base", use_container_width=True, type="primary",
                         help="Dopo aver premuto 'Rileva GPS', premi qui"):
                gps_check = read_gps_from_url()
                if gps_check:
                    addr_info = reverse_geocode(gps_check['latitude'], gps_check['longitude'])
                    citta_nome = addr_info['citta'] if addr_info and addr_info.get('citta') else "Posizione GPS"
                    config['citta_base'] = citta_nome
                    config['lat_base'] = gps_check['latitude']
                    config['lon_base'] = gps_check['longitude']
                    save_config(config)
                    st.session_state.config = config
                    clear_gps_from_url()
                    st.success(f"✅ Base aggiornata: {citta_nome}")
                    st.rerun()
                else:
                    st.warning("⚠️ Premi prima il pulsante GPS, poi conferma qui")
        
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
        st.subheader("🏙️ Aggiorna Città Clienti")
        st.info("Se hai clienti senza il campo città compilato, puoi aggiornarlo automaticamente dalle coordinate GPS.")
        
        if not df.empty:
            # Assicurati che la colonna citta esista
            if 'citta' not in df.columns:
                df['citta'] = None
            
            # Trova clienti senza città ma con coordinate valide
            senza_citta = df[
                ((df['citta'].isna()) | (df['citta'] == '') | (df['citta'].isnull())) &
                (df['latitude'].notna()) & (df['latitude'] != 0) &
                (df['longitude'].notna()) & (df['longitude'] != 0)
            ]
            
            if len(senza_citta) > 0:
                st.warning(f"🏙️ **{len(senza_citta)} clienti** hanno coordinate ma non hanno la città compilata!")
                
                with st.expander(f"👀 Vedi clienti senza città ({len(senza_citta)})"):
                    for _, row in senza_citta.head(20).iterrows():
                        st.write(f"- **{row['nome_cliente']}**: {row.get('indirizzo', 'N/A')} ({row['latitude']:.4f}, {row['longitude']:.4f})")
                    if len(senza_citta) > 20:
                        st.write(f"... e altri {len(senza_citta) - 20}")
                
                if st.button("🏙️ AGGIORNA TUTTE LE CITTÀ", type="primary", use_container_width=True):
                    progress = st.progress(0)
                    status = st.empty()
                    
                    successi = 0
                    errori = 0
                    
                    for idx, (_, row) in enumerate(senza_citta.iterrows()):
                        status.text(f"Cercando città per: {row['nome_cliente']}...")
                        
                        try:
                            # Reverse geocoding
                            addr = reverse_geocode(float(row['latitude']), float(row['longitude']))
                            
                            if addr and addr.get('citta'):
                                # Aggiorna nel database
                                update_data = {'citta': addr['citta']}
                                
                                # Aggiorna anche altri campi se vuoti
                                if not row.get('indirizzo') and addr.get('via'):
                                    update_data['indirizzo'] = addr['via']
                                if not row.get('cap') and addr.get('cap'):
                                    update_data['cap'] = addr['cap']
                                if not row.get('provincia') and addr.get('provincia'):
                                    update_data['provincia'] = addr['provincia']
                                
                                update_cliente(row['id'], update_data)
                                successi += 1
                            else:
                                errori += 1
                        except Exception as e:
                            errori += 1
                        
                        # Rate limiting LocationIQ (2 req/sec)
                        time_module.sleep(0.5)
                        
                        progress.progress((idx + 1) / len(senza_citta))
                    
                    progress.empty()
                    status.empty()
                    
                    st.success(f"✅ Completato! {successi} città aggiornate, {errori} errori")
                    st.session_state.reload_data = True
                    time_module.sleep(1)
                    st.rerun()
            else:
                st.success("✅ Tutti i clienti hanno la città compilata!")
        
        st.divider()
        st.subheader("📥 Importa Clienti da CSV")
        
        st.info("""
        **Formato CSV richiesto:**
        Il file deve avere queste colonne (nell'ordine che preferisci):
        - `nome cliente` (obbligatorio)
        - `indirizzo`, `citta`, `cap`, `provincia`
        - `latitude`, `longitude` (con virgola o punto)
        - `telefono`, `cellulare`, `mail`
        - `frequenza (giorni)`, `ultima visita`, `visitare`
        - `referente`, `contatto`, `note`, `storico report`
        
        ℹ️ **Separatore:** Accetta sia `,` che `;`
        """)
        
        uploaded_file = st.file_uploader("📂 Carica file CSV", type=['csv'])
        
        if uploaded_file is not None:
            try:
                # Leggi il contenuto per rilevare il separatore
                content = uploaded_file.read().decode('utf-8-sig', errors='ignore')  # utf-8-sig gestisce BOM
                uploaded_file.seek(0)
                
                # Rileva separatore (conta quale appare di più nella prima riga)
                first_line = content.split('\n')[0]
                count_comma = first_line.count(',')
                count_semicolon = first_line.count(';')
                
                if count_semicolon > count_comma:
                    separatore = ';'
                    st.info("🔍 Rilevato separatore: **punto e virgola (;)**")
                else:
                    separatore = ','
                    st.info("🔍 Rilevato separatore: **virgola (,)**")
                
                # Prova a leggere con diversi encoding
                try:
                    uploaded_file.seek(0)
                    df_import = pd.read_csv(uploaded_file, sep=separatore, encoding='utf-8-sig')
                except:
                    try:
                        uploaded_file.seek(0)
                        df_import = pd.read_csv(uploaded_file, sep=separatore, encoding='latin-1')
                    except:
                        uploaded_file.seek(0)
                        df_import = pd.read_csv(uploaded_file, sep=separatore, encoding='cp1252')
                
                # Normalizza nomi colonne: minuscolo, underscore -> spazio
                df_import.columns = [c.lower().strip().replace('_', ' ') for c in df_import.columns]
                
                st.success(f"✅ File caricato! Trovati **{len(df_import)} clienti**")
                st.caption(f"Colonne trovate: {', '.join(df_import.columns.tolist())}")
                
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
                            # Funzione helper per estrarre valori
                            def get_val(col_name, default=''):
                                val = row.get(col_name)
                                if pd.isna(val) or val is None or str(val).lower() == 'nan':
                                    return default
                                return str(val).strip()
                            
                            def get_float(col_name):
                                val = row.get(col_name)
                                if pd.isna(val) or val is None:
                                    return None
                                try:
                                    return float(str(val).replace(',', '.'))
                                except:
                                    return None
                            
                            # Estrai nome cliente
                            nome = get_val('nome cliente')
                            
                            if not nome:
                                errori += 1
                                errori_dettagli.append(f"Riga {idx+2}: Nome cliente mancante")
                                continue
                            
                            # Converti latitude/longitude
                            lat = get_float('latitude')
                            lon = get_float('longitude')
                            
                            # Converti data ultima visita
                            ultima_visita = None
                            data_str = get_val('ultima visita')
                            if data_str:
                                try:
                                    data_str = data_str.split(' ')[0]
                                    ultima_visita = datetime.strptime(data_str, '%d/%m/%Y').isoformat()
                                except:
                                    try:
                                        ultima_visita = datetime.strptime(data_str, '%Y-%m-%d').isoformat()
                                    except:
                                        pass
                            
                            # Converti frequenza
                            freq = 30
                            freq_val = row.get('frequenza giorni') or row.get('frequenza (giorni)')
                            if pd.notna(freq_val):
                                try:
                                    freq = int(float(freq_val))
                                except:
                                    pass
                            
                            # Prepara dati cliente
                            cliente = {
                                'user_id': user_id,
                                'nome_cliente': nome,
                                'indirizzo': get_val('indirizzo'),
                                'citta': get_val('citta'),
                                'cap': get_val('cap'),
                                'provincia': get_val('provincia'),
                                'latitude': lat,
                                'longitude': lon,
                                'frequenza_giorni': freq,
                                'ultima_visita': ultima_visita,
                                'visitare': get_val('visitare', 'SI').upper(),
                                'storico_report': get_val('storico report'),
                                'telefono': get_val('telefono'),
                                'cellulare': get_val('cellulare'),
                                'mail': get_val('mail'),
                                'contatto': get_val('contatto'),
                                'referente': get_val('referente'),
                                'note': get_val('note'),
                                'stato_cliente': get_val('stato cliente', 'CLIENTE ATTIVO')
                            }
                            
                            # Rimuovi valori vuoti (tranne user_id e nome_cliente)
                            cliente_clean = {k: v for k, v in cliente.items() 
                                           if v is not None and v != ''}
                            cliente_clean['user_id'] = user_id
                            cliente_clean['nome_cliente'] = nome
                            
                            # Inserisci nel database
                            supabase.table('clienti').insert(cliente_clean).execute()
                            successi += 1
                            
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
    st.caption("🚀 **Giro Visite CRM Pro** - Versione SaaS 6.1")

# --- RUN APP ---
init_auth_state()

if st.session_state.user is None:
    login_page()
else:
    try:
        main_app()
    except Exception as e:
        st.error(f"⚠️ Si è verificato un errore. Ricarica la pagina.")
        with st.expander("Dettagli errore (per supporto)"):
            st.code(str(e))
        if st.button("🔄 Ricarica App"):
            st.rerun()
