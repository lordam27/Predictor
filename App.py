import math
import datetime
import requests
import pandas as pd
import streamlit as st

# -----------------------------------------------------------------------------
# 1. CONFIGURACIÓN Y ESTILOS CSS ESTILO ESTADIO NOCTURNO
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Football Predictor Pro | Quantitative Engine",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    /* Fondo principal y fuentes */
    .stApp {
        background: radial-gradient(circle at 50% 10%, #112d23 0%, #08120e 100%);
        color: #e2e8f0;
    }
    
    /* Sidebar Táctica */
    [data-testid="stSidebar"] {
        background-color: #0d1b15;
        border-right: 1px solid #1e3a2f;
    }

    /* Tarjeta de Marcador Principal (Estilo Transmisión de TV) */
    .scoreboard-card {
        background: rgba(15, 30, 23, 0.75);
        backdrop-filter: blur(12px);
        border: 1px solid #00ff87;
        box-shadow: 0 8px 32px 0 rgba(0, 255, 135, 0.15);
        border-radius: 16px;
        padding: 24px;
        margin-bottom: 25px;
    }
    
    .crest-container img {
        max-height: 90px;
        filter: drop-shadow(0px 4px 10px rgba(0,0,0,0.5));
    }

    /* Badge de Cuota de Valor (+EV) */
    .ev-badge {
        background: linear-gradient(90deg, #00b09b, #96c93d);
        color: #000;
        font-weight: 800;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
    }
    
    /* Métricas con brillo */
    [data-testid="stMetricValue"] {
        color: #00ff87 !important;
        font-family: 'Trebuchet MS', sans-serif;
    }
    
    /* Pestañas modernas */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #12251c;
        border-radius: 8px 8px 0px 0px;
        color: #a0aec0;
        border: 1px solid #1e3a2f;
        padding: 10px 20px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #00ff87 !important;
        color: #000000 !important;
        font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. CONEXIÓN A API Y DATOS HISTÓRICOS
# -----------------------------------------------------------------------------
try:
    API_KEY = st.secrets["FOOTBALL_API_KEY"]
except KeyError:
    st.error("⚠️ Falta la clave API. Agrégala en `.streamlit/secrets.toml` bajo el nombre `FOOTBALL_API_KEY`.")
    st.stop()

HEADERS = {"X-Auth-Token": API_KEY}
BASE_URL = "https://api.football-data.org/v4/"

LIGAS = {
    "PD": "🇪🇸 LaLiga", "PL": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League", "SA": "🇮🇹 Serie A",
    "BL1": "🇩🇪 Bundesliga", "FL1": "🇫🇷 Ligue 1", "CL": "🇪🇺 Champions League",
    "DED": "🇳🇱 Eredivisie", "PPL": "🇵🇹 Primeira Liga"
}

@st.cache_data(ttl=86400)
def obtener_equipos(liga_code):
    url = f"{BASE_URL}competitions/{liga_code}/teams"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200: return []
        teams = res.json().get("teams", [])
        return sorted([{"id": t["id"], "nombre": t["name"], "crest": t.get("crest", "")} for t in teams], key=lambda x: x["nombre"])
    except:
        return []

@st.cache_data(ttl=7200)
def obtener_historico(liga_code):
    anio_actual = datetime.datetime.now().year
    seasons = [anio_actual, anio_actual - 1]
    jugados, programados = [], []

    for idx, season in enumerate(seasons):
        try:
            res = requests.get(f"{BASE_URL}competitions/{liga_code}/matches?season={season}", headers=HEADERS, timeout=10)
            if res.status_code == 200:
                matches = res.json().get("matches", [])
                if idx == 0:
                    programados = [m for m in matches if m.get("status") in ["SCHEDULED", "TIMED", "LIVE"]]
                jugados.extend([m for m in matches if m.get("status") == "FINISHED"])
        except:
            continue
    return jugados, programados

# -----------------------------------------------------------------------------
# 3. MOTOR MATEMÁTICO (POISSON + DIXON COLES + DECAIMIENTO EXPONENCIAL)
# -----------------------------------------------------------------------------
def calcular_metricas(equipo_id, partidos_jugados, es_local=True, limite=20):
    partidos = [m for m in partidos_jugados if m["homeTeam"]["id"] == equipo_id or m["awayTeam"]["id"] == equipo_id][:limite]
    if not partidos:
        return 1.2, 1.1

    gf_weighted, gc_weighted, peso_total = 0.0, 0.0, 0.0
    for idx, m in enumerate(partidos):
        is_home = m["homeTeam"]["id"] == equipo_id
        score = m["score"]["fullTime"]
        gf = score["home"] if is_home else score["away"]
        gc = score["away"] if is_home else score["home"]
        if gf is None or gc is None: continue
        
        peso = math.exp(-0.10 * idx) # Decaimiento temporal
        peso_total += peso
        gf_weighted += gf * peso
        gc_weighted += gc * peso

    return (gf_weighted / peso_total), (gc_weighted / peso_total)

def poisson_pmf(lmbda, k):
    return (lmbda ** k) * math.exp(-lmbda) / math.factorial(k) if lmbda > 0 else 0.0

def dixon_coles_tau(x, y, lmbda, mu, rho=-0.11):
    if x == 0 and y == 0: return 1.0 - (lmbda * mu * rho)
    elif x == 1 and y == 0: return 1.0 + (mu * rho)
    elif x == 0 and y == 1: return 1.0 + (lmbda * rho)
    elif x == 1 and y == 1: return 1.0 - rho
    return 1.0

def simular_partido(exp_loc, exp_vis):
    raw_matrix = []
    total_prob = 0.0
    for g_loc in range(6):
        fila = []
        for g_vis in range(6):
            p = poisson_pmf(exp_loc, g_loc) * poisson_pmf(exp_vis, g_vis) * dixon_coles_tau(g_loc, g_vis, exp_loc, exp_vis)
            p = max(0.0, p)
            fila.append(p)
            total_prob += p
        raw_matrix.append(fila)

    prob_1, prob_x, prob_2 = 0.0, 0.0, 0.0
    marcadores = []
    
    for g_loc in range(6):
        for g_vis in range(6):
            p_norm = (raw_matrix[g_loc][g_vis] / total_prob) * 100
            if g_loc > g_vis: prob_1 += p_norm
            elif g_loc == g_vis: prob_x += p_norm
            else: prob_2 += p_norm
            
            marcadores.append({"score": f"{g_loc}-{g_vis}", "prob": p_norm, "loc": g_loc, "vis": g_vis})

    marcadores = sorted(marcadores, key=lambda x: x["prob"], reverse=True)
    return {"1": prob_1, "X": prob_x, "2": prob_2}, marcadores

# -----------------------------------------------------------------------------
# 4. INTERFAZ DE USUARIO PRINCIPAL
# -----------------------------------------------------------------------------
st.title("⚽ Predictor Profesional de Fútbol")
st.caption("Engine cuantitativo basado en modelos Poisson/Dixon-Coles y simulación de valor (+EV).")

# SELECCIÓN RÁPIDA EN BARRA LATERAL
st.sidebar.header("⚙️ Configuración del Partido")
liga_sel = st.sidebar.selectbox("Competición", list(LIGAS.keys()), format_func=lambda x: LIGAS[x])

equipos = obtener_equipos(liga_sel)
if not equipos:
    st.error("No se pudieron cargar los datos de la liga seleccionada.")
    st.stop()

equipos_dict = {e["nombre"]: e for e in equipos}
jugados, programados = obtener_historico(liga_sel)

if programados:
    opciones_p = [f"{m['homeTeam']['name']} vs {m['awayTeam']['name']}" for m in programados[:12]]
    partido_opt = st.sidebar.selectbox("Próximos Partidos Programados", opciones_p)
    idx_p = opciones_p.index(partido_opt)
    local_nom = programados[idx_p]["homeTeam"]["name"]
    visitante_nom = programados[idx_p]["awayTeam"]["name"]
else:
    local_nom = st.sidebar.selectbox("Local", list(equipos_dict.keys()), index=0)
    visitante_nom = st.sidebar.selectbox("Visitante", [e for e in equipos_dict.keys() if e != local_nom], index=0)

# PRESETS DE ESCENARIO TÁCTICO (MEJORA UX)
st.sidebar.divider()
st.sidebar.header("🎯 Preset Táctico Rápido")
preset = st.sidebar.radio("Ajuste rápido de contexto:", ["Estándar", "Derby / Clásico (Alta Intenso)", "Rotaciones / Suplentes", "Partido Defensivo / Cerrado"])

factor_home = 1.12
mod_loc_atq, mod_vis_atq = 1.0, 1.0

if preset == "Derby / Clásico (Alta Intenso)":
    factor_home = 1.05 # Se reduce ventaja de campo pura por tensión
elif preset == "Rotaciones / Suplentes":
    mod_loc_atq, mod_vis_atq = 0.85, 0.85
elif preset == "Partido Defensivo / Cerrado":
    mod_loc_atq, mod_vis_atq = 0.80, 0.80

# CALCULADORA AL INSTANTE
eq_loc = equipos_dict.get(local_nom, {})
eq_vis = equipos_dict.get(visitante_nom, {})

atq_loc, def_loc = calcular_metricas(eq_loc.get("id"), jugados, es_local=True)
atq_vis, def_vis = calcular_metricas(eq_vis.get("id"), jugados, es_local=False)

exp_local = max(0.2, ((atq_loc * def_vis) / 1.35) * factor_home * mod_loc_atq)
exp_vis = max(0.2, ((atq_vis * def_loc) / 1.35) * mod_vis_atq)

probs_1x2, marcadores = simular_partido(exp_local, exp_vis)
top_m = marcadores[0]

# MARCADOR PRINCIPAL TIPO TRANSMISIÓN DE TV
st.markdown(f"""
    <div class="scoreboard-card">
        <div style="display: flex; justify-content: space-around; align-items: center; text-align: center;">
            <div style="flex: 1;" class="crest-container">
                <img src="{eq_loc.get('crest', '')}"/><br>
                <h2 style="margin: 10px 0 0 0; color: #ffffff;">{local_nom}</h2>
                <span style="color: #a0aec0; font-size: 0.9rem;">xG Est: {exp_local:.2f}</span>
            </div>
            <div style="flex: 0.8; background: rgba(0,0,0,0.3); padding: 15px; border-radius: 12px; border: 1px solid #1e3a2f;">
                <span style="color: #00ff87; font-weight: bold; font-size: 0.85rem; letter-spacing: 1px;">PREDICCIÓN CENTRAL</span>
                <h1 style="color: #ffffff; font-size: 3.5rem; margin: 0; line-height: 1;">{top_m['loc']} - {top_m['vis']}</h1>
                <span style="color: #cbd5e0; font-size: 0.85rem;">Probabilidad: <strong>{top_m['prob']:.1f}%</strong></span>
            </div>
            <div style="flex: 1;" class="crest-container">
                <img src="{eq_vis.get('crest', '')}"/><br>
                <h2 style="margin: 10px 0 0 0; color: #ffffff;">{visitante_nom}</h2>
                <span style="color: #a0aec0; font-size: 0.9rem;">xG Est: {exp_vis:.2f}</span>
            </div>
        </div>
    </div>
""", unsafe_allow_html=True)

# PESTAÑAS DE ANÁLISIS
tab_pred, tab_value, tab_mkt = st.tabs(["📊 Probabilidades 1X2", "💰 Calculadora +EV & Banca", "🎯 Marcadores Exactos"])

with tab_pred:
    col1, col2, col3 = st.columns(3)
    c1_cuota = 100 / probs_1x2['1'] if probs_1x2['1'] > 0 else 99
    cX_cuota = 100 / probs_1x2['X'] if probs_1x2['X'] > 0 else 99
    c2_cuota = 100 / probs_1x2['2'] if probs_1x2['2'] > 0 else 99

    col1.metric(f"Gana {local_nom} (1)", f"{probs_1x2['1']:.1f}%", f"Cuota Justa: @{c1_cuota:.2f}")
    col2.metric("Empate (X)", f"{probs_1x2['X']:.1f}%", f"Cuota Justa: @{cX_cuota:.2f}")
    col3.metric(f"Gana {visitante_nom} (2)", f"{probs_1x2['2']:.1f}%", f"Cuota Justa: @{c2_cuota:.2f}")

with tab_value:
    st.subheader("🧮 Comprobar Apuesta de Valor (+EV) y Criterio de Kelly")
    st.write("Ingresa la cuota ofrecida por tu casa de apuestas para verificar si el algoritmo detecta ventaja matemáticas.")

    col_val1, col_val2, col_val3 = st.columns(3)
    with col_val1:
        opcion_apuesta = st.selectbox("Selecciona Mercado", [f"Victoria {local_nom}", "Empate", f"Victoria {visitante_nom}"])
        prob_modelo = probs_1x2['1'] if "Victoria " + local_nom in opcion_apuesta else (probs_1x2['X'] if opcion_apuesta == "Empate" else probs_1x2['2'])
    
    with col_val2:
        cuota_casa = st.number_input("Cuota de la Casa de Apuestas", min_value=1.01, value=round(100/prob_modelo * 1.1, 2), step=0.05)
    
    with col_val3:
        banca_total = st.number_input("Tu Banca Total (€)", min_value=10.0, value=500.0, step=50.0)

    # Cálculo EV & Kelly
    p_win = prob_modelo / 100.0
    ev = (p_win * cuota_casa) - 1.0
    
    # Kelly fraccionado (Quarter Kelly para seguridad)
    b_odds = cuota_casa - 1.0
    f_kelly = max(0.0, (b_odds * p_win - (1 - p_win)) / b_odds) * 0.25
    apuesta_sugerida = banca_total * f_kelly

    st.divider()
    if ev > 0:
        st.success(f"🔥 **¡APUESTA CON VALOR POSITIVO (+EV)!**\n\n- **EV Estimado:** +{ev*100:.2f}%\n- **Stake Recomendado (Quarter Kelly):** {f_kelly*100:.2f}% de tu banca (**{apuesta_sugerida:.2f} €**)")
    else:
        st.error(f"⚠️ **SIN VALOR MATEMÁTICO (EV Negativo)**\n\n- **EV Estimado:** {ev*100:.2f}%\n- La cuota mínima aceptable para apostar a este mercado es **@{1/p_win:.2f}**.")

with tab_mkt:
    st.subheader("Top 6 Marcadores Más Probables")
    df_m = pd.DataFrame(marcadores[:6])[["score", "prob"]]
    df_m.columns = ["Marcador Exacto", "Probabilidad (%)"]
    df_m["Cuota Justa"] = df_m["Probabilidad (%)"].apply(lambda p: f"@{100/p:.2f}" if p > 0 else "@99")
    st.dataframe(df_m, use_container_width=True, hide_index=True)
