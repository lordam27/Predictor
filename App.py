import math
import datetime
import requests
import pandas as pd
import streamlit as st

# -----------------------------------------------------------------------------
# 1. CONFIGURACIÓN Y ESTILOS DE INTERFAZ
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Football Quant Pro & Matchday Hub",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .stApp {
        background: radial-gradient(circle at 50% 10%, #112d23 0%, #08120e 100%);
        color: #e2e8f0;
    }
    [data-testid="stSidebar"] {
        background-color: #0d1b15;
        border-right: 1px solid #1e3a2f;
    }
    .match-today-card {
        background: rgba(18, 37, 28, 0.7);
        border: 1px solid #1e3a2f;
        border-radius: 12px;
        padding: 12px 16px;
        margin-bottom: 10px;
        transition: transform 0.2s;
    }
    .match-today-card:hover {
        border-color: #00ff87;
        transform: translateY(-2px);
    }
    .scoreboard-card {
        background: rgba(15, 30, 23, 0.85);
        backdrop-filter: blur(12px);
        border: 1px solid #00ff87;
        box-shadow: 0 8px 32px 0 rgba(0, 255, 135, 0.15);
        border-radius: 16px;
        padding: 20px;
        margin-bottom: 20px;
    }
    .crest-container img {
        max-height: 75px;
        filter: drop-shadow(0px 4px 8px rgba(0,0,0,0.6));
    }
    [data-testid="stMetricValue"] {
        color: #00ff87 !important;
        font-family: 'Trebuchet MS', sans-serif;
    }
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. CONEXIÓN Y DATOS (12 LIGAS + PARTIDOS DE HOY)
# -----------------------------------------------------------------------------
try:
    API_KEY = st.secrets["FOOTBALL_API_KEY"]
except KeyError:
    st.error("⚠️ Falta la clave API en `.streamlit/secrets.toml` bajo el nombre `FOOTBALL_API_KEY`.")
    st.stop()

HEADERS = {"X-Auth-Token": API_KEY}
BASE_URL = "https://api.football-data.org/v4/"

# LAS 12 COMPETICIONES DEL PLAN GRATUITO DE FOOTBALL-DATA.ORG
LIGAS = {
    "PD": "🇪🇸 LaLiga",
    "PL": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League",
    "SA": "🇮🇹 Serie A",
    "BL1": "🇩🇪 Bundesliga",
    "FL1": "🇫🇷 Ligue 1",
    "CL": "🇪🇺 Champions League",
    "DED": "🇳🇱 Eredivisie",
    "PPL": "🇵🇹 Primeira Liga",
    "ELC": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Championship",
    "BSA": "🇧🇷 Brasileirão Série A",
    "WC": "🏆 Copa del Mundo",
    "EC": "🇪🇺 Eurocopa"
}

@st.cache_data(ttl=1800)
def obtener_partidos_hoy():
    """Consulta la agenda de partidos programados para la fecha actual."""
    hoy = datetime.date.today().strftime("%Y-%m-%d")
    url = f"{BASE_URL}matches?dateFrom={hoy}&dateTo={hoy}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            return res.json().get("matches", [])
    except:
        pass
    return []

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

@st.cache_data(ttl=14400)
def obtener_historico_dos_anios(liga_code):
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
# 3. MOTOR MATEMÁTICO & POWER RANKING
# -----------------------------------------------------------------------------
def calcular_metricas_equipo(equipo_id, partidos_jugados, limite=40):
    partidos = [m for m in partidos_jugados if m["homeTeam"]["id"] == equipo_id or m["awayTeam"]["id"] == equipo_id][:limite]
    if not partidos:
        return 1.2, 1.1, 1.0

    gf_weighted, gc_weighted, peso_total = 0.0, 0.0, 0.0
    puntos_totales = 0

    for idx, m in enumerate(partidos):
        is_home = m["homeTeam"]["id"] == equipo_id
        score = m["score"]["fullTime"]
        gf = score["home"] if is_home else score["away"]
        gc = score["away"] if is_home else score["home"]
        if gf is None or gc is None: continue

        if gf > gc: puntos_totales += 3
        elif gf == gc: puntos_totales += 1

        peso = math.exp(-0.04 * idx)
        peso_total += peso
        gf_weighted += gf * peso
        gc_weighted += gc * peso

    return (gf_weighted / peso_total), (gc_weighted / peso_total), (puntos_totales / len(partidos))

def generar_power_ranking(equipos, partidos_jugados):
    ranking_data = []
    for eq in equipos:
        xg_atq, xg_def, ppm = calcular_metricas_equipo(eq["id"], partidos_jugados)
        raw_rating = (ppm * 25.0) + (xg_atq * 25.0) - (xg_def * 15.0)
        ranking_data.append({
            "Equipo": eq["nombre"],
            "xG Ataque": round(xg_atq, 2),
            "xG Defensa": round(xg_def, 2),
            "PPM": round(ppm, 2),
            "raw_score": raw_rating
        })

    df = pd.DataFrame(ranking_data)
    if df.empty: return df

    min_s, max_s = df["raw_score"].min(), df["raw_score"].max()
    df["Power Rating"] = ((df["raw_score"] - min_s) / (max_s - min_s) * 100).round(1) if max_s > min_s else 50.0
    df = df.sort_values(by="Power Rating", ascending=False).reset_index(drop=True)
    df.index = df.index + 1
    return df

def poisson_pmf(lmbda, k):
    return (lmbda ** k) * math.exp(-lmbda) / math.factorial(k) if lmbda > 0 else 0.0

def dixon_coles_tau(x, y, lmbda, mu, rho=-0.11):
    if x == 0 and y == 0: return 1.0 - (lmbda * mu * rho)
    elif x == 1 and y == 0: return 1.0 + (mu * rho)
    elif x == 0 and y == 1: return 1.0 + (lmbda * rho)
    elif x == 1 and y == 1: return 1.0 - rho
    return 1.0

def calcular_simulacion_completa(exp_loc, exp_vis):
    matrix, total_prob = [], 0.0
    for g_loc in range(7):
        fila = []
        for g_vis in range(7):
            p = max(0.0, poisson_pmf(exp_loc, g_loc) * poisson_pmf(exp_vis, g_vis) * dixon_coles_tau(g_loc, g_vis, exp_loc, exp_vis))
            fila.append(p)
            total_prob += p
        matrix.append(fila)

    prob_1, prob_x, prob_2, prob_over25, prob_btts = 0.0, 0.0, 0.0, 0.0, 0.0
    marcadores = []

    for g_loc in range(7):
        for g_vis in range(7):
            p_norm = matrix[g_loc][g_vis] / total_prob
            if g_loc > g_vis: prob_1 += p_norm
            elif g_loc == g_vis: prob_x += p_norm
            else: prob_2 += p_norm

            if (g_loc + g_vis) > 2.5: prob_over25 += p_norm
            if g_loc > 0 and g_vis > 0: prob_btts += p_norm
            marcadores.append({"score": f"{g_loc}-{g_vis}", "prob": p_norm * 100})

    marcadores = sorted(marcadores, key=lambda x: x["prob"], reverse=True)
    return {
        "1": prob_1, "X": prob_x, "2": prob_2,
        "over25": prob_over25, "under25": 1.0 - prob_over25,
        "btts_si": prob_btts, "btts_no": 1.0 - prob_btts
    }, marcadores

# -----------------------------------------------------------------------------
# 4. VISTA DE INICIO & EVENTOS DEL DÍA
# -----------------------------------------------------------------------------
st.title("⚽ Football Analytics & Matchday Hub")

partidos_hoy = obtener_partidos_hoy()

with st.expander("📅 **EVENTOS DISPONIBLES HOY** (Haz clic para ver los partidos de la jornada)", expanded=True):
    if partidos_hoy:
        st.write(f"Se han encontrado **{len(partidos_hoy)} partido(s)** programados para el día de hoy:")
        cols_hoy = st.columns(min(3, len(partidos_hoy)))
        
        for idx, m in enumerate(partidos_hoy):
            col_idx = idx % min(3, len(partidos_hoy))
            comp_nom = m.get("competition", {}).get("name", "Liga")
            loc_n = m["homeTeam"]["name"]
            vis_n = m["awayTeam"]["name"]
            hora = m.get("utcDate", "")[11:16] + " UTC"
            
            cols_hoy[col_idx].markdown(f"""
                <div class="match-today-card">
                    <span style="color: #00ff87; font-size: 0.75rem; font-weight: bold;">{comp_nom} • {hora}</span><br>
                    <strong>{loc_n}</strong> vs <strong>{vis_n}</strong>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.info("ℹ️ No hay partidos de las 12 ligas soportadas programados para el día de hoy. Utiliza el selector lateral para analizar cualquier encuentro futuro de la temporada.")

st.divider()

# -----------------------------------------------------------------------------
# 5. CONTROLES EN SIDEBAR Y PREPARACIÓN DEL PARTIDO
# -----------------------------------------------------------------------------
st.sidebar.header("⚙️ Selector de Partido")
liga_sel = st.sidebar.selectbox("Competición (12 disponibles)", list(LIGAS.keys()), format_func=lambda x: LIGAS[x])

equipos = obtener_equipos(liga_sel)
if not equipos:
    st.error("No se pudieron cargar los datos de la liga seleccionada.")
    st.stop()

equipos_dict = {e["nombre"]: e for e in equipos}
jugados, programados = obtener_historico_dos_anios(liga_sel)

if programados:
    opciones_p = [f"{m['homeTeam']['name']} vs {m['awayTeam']['name']}" for m in programados[:20]]
    partido_opt = st.sidebar.selectbox("Próximos Encuentros", opciones_p)
    idx_p = opciones_p.index(partido_opt)
    local_nom = programados[idx_p]["homeTeam"]["name"]
    visitante_nom = programados[idx_p]["awayTeam"]["name"]
else:
    local_nom = st.sidebar.selectbox("Equipo Local", list(equipos_dict.keys()), index=0)
    visitante_nom = st.sidebar.selectbox("Equipo Visitante", [e for e in equipos_dict.keys() if e != local_nom], index=0)

eq_loc = equipos_dict.get(local_nom, {})
eq_vis = equipos_dict.get(visitante_nom, {})

atq_loc, def_loc, _ = calcular_metricas_equipo(eq_loc.get("id"), jugados)
atq_vis, def_vis, _ = calcular_metricas_equipo(eq_vis.get("id"), jugados)

exp_local = max(0.25, ((atq_loc * def_vis) / 1.30) * 1.10)
exp_vis = max(0.25, ((atq_vis * def_loc) / 1.30))

probs_mercados, marcadores = calcular_simulacion_completa(exp_local, exp_vis)
top_m = marcadores[0]

# MARCADOR PRINCIPAL
st.markdown(f"""
    <div class="scoreboard-card">
        <div style="display: flex; justify-content: space-around; align-items: center; text-align: center;">
            <div style="flex: 1;" class="crest-container">
                <img src="{eq_loc.get('crest', '')}"/><br>
                <h2 style="margin: 8px 0 0 0; color: #ffffff;">{local_nom}</h2>
                <span style="color: #00ff87; font-weight: bold;">xG Est: {exp_local:.2f}</span>
            </div>
            <div style="flex: 0.8; background: rgba(0,0,0,0.4); padding: 12px; border-radius: 12px; border: 1px solid #1e3a2f;">
                <span style="color: #a0aec0; font-size: 0.8rem; letter-spacing: 1px;">PREDICCIÓN CENTRAL</span>
                <h1 style="color: #ffffff; font-size: 3rem; margin: 0;">{top_m['score']}</h1>
                <span style="color: #00ff87; font-size: 0.85rem;">Probabilidad: {top_m['prob']:.1f}%</span>
            </div>
            <div style="flex: 1;" class="crest-container">
                <img src="{eq_vis.get('crest', '')}"/><br>
                <h2 style="margin: 8px 0 0 0; color: #ffffff;">{visitante_nom}</h2>
                <span style="color: #00ff87; font-weight: bold;">xG Est: {exp_vis:.2f}</span>
            </div>
        </div>
    </div>
""", unsafe_allow_html=True)

# PESTAÑAS DE ANÁLISIS
tab_cuotas, tab_rank, tab_value = st.tabs([
    "🎯 Cuotas Justas & Mercados", 
    "🏆 Power Ranking Liga", 
    "💰 Calculadora +EV"
])

with tab_cuotas:
    st.subheader("💵 Cuotas Justas (Fair Odds)")
    c1, c2, c3 = st.columns(3)
    c1.metric("Gana " + local_nom, f"@{1/probs_mercados['1']:.2f}", f"Prob: {probs_mercados['1']*100:.1f}%")
    c2.metric("Empate (X)", f"@{1/probs_mercados['X']:.2f}", f"Prob: {probs_mercados['X']*100:.1f}%")
    c3.metric("Gana " + visitante_nom, f"@{1/probs_mercados['2']:.2f}", f"Prob: {probs_mercados['2']*100:.1f}%")

    st.divider()
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        st.markdown("##### Mercado Goles (Over/Under 2.5)")
        st.write(f"• **Over 2.5 Goles:** Cuota Justa **@{1/probs_mercados['over25']:.2f}** ({probs_mercados['over25']*100:.1f}%)")
        st.write(f"• **Under 2.5 Goles:** Cuota Justa **@{1/probs_mercados['under25']:.2f}** ({probs_mercados['under25']*100:.1f}%)")
    with col_m2:
        st.markdown("##### Mercado Ambos Anotan (BTTS)")
        st.write(f"• **Ambos Anotan - SÍ:** Cuota Justa **@{1/probs_mercados['btts_si']:.2f}** ({probs_mercados['btts_si']*100:.1f}%)")
        st.write(f"• **Ambos Anotan - NO:** Cuota Justa **@{1/probs_mercados['btts_no']:.2f}** ({probs_mercados['btts_no']*100:.1f}%)")

with tab_rank:
    st.subheader(f"📊 Power Ranking - {LIGAS[liga_sel]}")
    with st.spinner("Calculando muestra a 2 temporadas..."):
        df_power = generar_power_ranking(equipos, jugados)
    if not df_power.empty:
        st.dataframe(df_power[["Equipo", "Power Rating", "xG Ataque", "xG Defensa", "PPM"]], use_container_width=True, height=450)

with tab_value:
    st.subheader("🧮 Comparador de Cuotas de Casas de Apuestas")
    col_v1, col_v2, col_v3 = st.columns(3)
    with col_v1:
        mercado_sel = st.selectbox("Mercado", ["1 (Local)", "X (Empate)", "2 (Visitante)", "Over 2.5", "Under 2.5", "BTTS Sí", "BTTS No"])
        mapa_prob = {
            "1 (Local)": probs_mercados['1'], "X (Empate)": probs_mercados['X'], "2 (Visitante)": probs_mercados['2'],
            "Over 2.5": probs_mercados['over25'], "Under 2.5": probs_mercados['under25'],
            "BTTS Sí": probs_mercados['btts_si'], "BTTS No": probs_mercados['btts_no']
        }
        p_est = mapa_prob[mercado_sel]
    with col_v2:
        cuota_bookie = st.number_input("Cuota de la Casa", min_value=1.01, value=round(1/p_est * 1.08, 2), step=0.05)
    with col_v3:
        banca = st.number_input("Banca Total (€)", min_value=10.0, value=1000.0, step=50.0)

    ev_val = (p_est * cuota_bookie) - 1.0
    cuota_corte = 1 / p_est

    st.divider()
    if ev_val > 0:
        st.success(f"🔥 **VALOR DETECTADO (+EV): +{ev_val*100:.2f}%**\n\nCuota mínima rentable: **@{cuota_corte:.2f}**")
    else:
        st.error(f"❌ **SIN VALOR (EV Negativo): {ev_val*100:.2f}%**\n\nRequiere cuota mayor a **@{cuota_corte:.2f}**.")
