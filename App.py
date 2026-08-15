import math
import time
import datetime
import requests
import pandas as pd
import streamlit as st

# -----------------------------------------------------------------------------
# 1. CONFIGURACIÓN Y ESTILOS
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Football Quant Pro | H2H & Form Engine",
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
        border-radius: 10px;
        padding: 10px 14px;
        margin-bottom: 8px;
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
    .form-badge {
        font-weight: bold;
        padding: 4px 8px;
        border-radius: 6px;
        font-size: 0.9rem;
    }
    [data-testid="stMetricValue"] {
        color: #00ff87 !important;
        font-family: 'Trebuchet MS', sans-serif;
    }
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. CONEXIÓN API & CARGA DE DATOS ROBUTA
# -----------------------------------------------------------------------------
try:
    API_KEY = st.secrets["FOOTBALL_API_KEY"]
except KeyError:
    st.error("⚠️ Falta la clave API en `.streamlit/secrets.toml` bajo el nombre `FOOTBALL_API_KEY`.")
    st.stop()

HEADERS = {"X-Auth-Token": API_KEY}
BASE_URL = "https://api.football-data.org/v4/"

LIGAS = {
    "PD": "🇪🇸 LaLiga", "PL": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League", "SA": "🇮🇹 Serie A",
    "BL1": "🇩🇪 Bundesliga", "FL1": "🇫🇷 Ligue 1", "CL": "🇪🇺 Champions League",
    "DED": "🇳🇱 Eredivisie", "PPL": "🇵🇹 Primeira Liga", "ELC": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Championship",
    "BSA": "🇧🇷 Brasileirão Série A", "WC": "🏆 Copa del Mundo", "EC": "🇪🇺 Eurocopa"
}

@st.cache_data(ttl=900)
def obtener_partidos_hoy():
    """Obtiene partidos de hoy/mañana con ventana ampliada para evitar problemas de UTC."""
    hoy_dt = datetime.date.today()
    desde = (hoy_dt - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    hasta = (hoy_dt + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    
    url = f"{BASE_URL}matches?dateFrom={desde}&dateTo={hasta}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            matches = res.json().get("matches", [])
            # Filtrar solo las 12 ligas soportadas
            codigos_soportados = set(LIGAS.keys())
            return [m for m in matches if m.get("competition", {}).get("code") in codigos_soportados]
        elif res.status_code == 429:
            st.warning("⚠️ Límite de peticiones API alcanzado (10/min). Espera unos segundos y recarga.")
    except Exception as e:
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
            time.sleep(0.1) # Evitar Rate Limit
        except:
            continue
            
    # Ordenar partidos de más reciente a más antiguo
    jugados = sorted(jugados, key=lambda x: x.get("utcDate", ""), reverse=True)
    return jugados, programados

# -----------------------------------------------------------------------------
# 3. FUNCIONES DEDICADAS: H2H, ÚLTIMOS 20 Y FORMA ACTUAL
# -----------------------------------------------------------------------------
def obtener_ultimos_partidos(partidos_jugados, equipo_id, n=20):
    """Devuelve los últimos N partidos jugados por un equipo con detalle W/D/L."""
    partidos_eq = [m for m in partidos_jugados if m["homeTeam"]["id"] == equipo_id or m["awayTeam"]["id"] == equipo_id][:n]
    registros = []

    for m in partidos_eq:
        is_home = m["homeTeam"]["id"] == equipo_id
        score = m["score"]["fullTime"]
        gf = score["home"] if is_home else score["away"]
        gc = score["away"] if is_home else score["home"]
        
        if gf is None or gc is None: continue

        if gf > gc:
            res_str = "Victoria"
            badge = "🟢 V"
            pts = 3
        elif gf == gc:
            res_str = "Empate"
            badge = "🟡 E"
            pts = 1
        else:
            res_str = "Derrota"
            badge = "🔴 D"
            pts = 0

        rival = m["awayTeam"]["name"] if is_home else m["homeTeam"]["name"]
        
        registros.append({
            "Fecha": m.get("utcDate", "")[:10],
            "Rival": rival,
            "Condición": "Local" if is_home else "Visitante",
            "Resultado": f"{score['home']} - {score['away']}",
            "Estado": badge,
            "Puntos": pts,
            "GF": gf,
            "GC": gc
        })

    return pd.DataFrame(registros)

def calcular_forma_resumen(df_partidos):
    """Calcula la racha reciente (últimos 5 partidos) y puntos obtenidos."""
    if df_partidos.empty:
        return "Sin datos", 0.0

    ult_5 = df_partidos.head(5)
    racha = " ".join(ult_5["Estado"].tolist())
    ppm_5 = ult_5["Puntos"].sum() / len(ult_5)
    return racha, ppm_5

def obtener_enfrentamientos_h2h(partidos_jugados, id_loc, id_vis):
    """Calcula el historial cara a cara cara entre los dos equipos seleccionados."""
    h2h_matches = [
        m for m in partidos_jugados 
        if (m["homeTeam"]["id"] == id_loc and m["awayTeam"]["id"] == id_vis) or 
           (m["homeTeam"]["id"] == id_vis and m["awayTeam"]["id"] == id_loc)
    ]

    loc_wins, draws, vis_wins = 0, 0, 0
    registros_h2h = []

    for m in h2h_matches:
        score = m["score"]["fullTime"]
        g_home = score["home"]
        g_away = score["away"]
        if g_home is None or g_away is None: continue

        is_loc_home = (m["homeTeam"]["id"] == id_loc)

        if g_home > g_away:
            if is_loc_home: loc_wins += 1
            else: vis_wins += 1
        elif g_home < g_away:
            if is_loc_home: vis_wins += 1
            else: loc_wins += 1
        else:
            draws += 1

        registros_h2h.append({
            "Fecha": m.get("utcDate", "")[:10],
            "Local": m["homeTeam"]["name"],
            "Marcador": f"{g_home} - {g_away}",
            "Visitante": m["awayTeam"]["name"],
            "Competición": m.get("competition", {}).get("name", "Liga")
        })

    return loc_wins, draws, vis_wins, pd.DataFrame(registros_h2h)

# -----------------------------------------------------------------------------
# 4. MOTOR DE PREDICCIÓN (POISSON)
# -----------------------------------------------------------------------------
def calcular_metricas_base(equipo_id, partidos_jugados):
    partidos = [m for m in partidos_jugados if m["homeTeam"]["id"] == equipo_id or m["awayTeam"]["id"] == equipo_id][:30]
    if not partidos: return 1.2, 1.1
    
    gf_tot, gc_tot, peso_tot = 0.0, 0.0, 0.0
    for idx, m in enumerate(partidos):
        is_home = m["homeTeam"]["id"] == equipo_id
        score = m["score"]["fullTime"]
        gf = score["home"] if is_home else score["away"]
        gc = score["away"] if is_home else score["home"]
        if gf is None or gc is None: continue
        
        peso = math.exp(-0.05 * idx)
        peso_tot += peso
        gf_tot += gf * peso
        gc_tot += gc * peso
        
    return (gf_tot / peso_tot), (gc_tot / peso_tot)

def poisson_pmf(lmbda, k):
    return (lmbda ** k) * math.exp(-lmbda) / math.factorial(k) if lmbda > 0 else 0.0

def calcular_simulacion(exp_loc, exp_vis):
    prob_1, prob_x, prob_2 = 0.0, 0.0, 0.0
    for g_loc in range(6):
        for g_vis in range(6):
            p = poisson_pmf(exp_loc, g_loc) * poisson_pmf(exp_vis, g_vis)
            if g_loc > g_vis: prob_1 += p
            elif g_loc == g_vis: prob_x += p
            else: prob_2 += p
    tot = prob_1 + prob_x + prob_2
    return {"1": prob_1/tot, "X": prob_x/tot, "2": prob_2/tot}

# -----------------------------------------------------------------------------
# 5. VISTA DE INICIO & EVENTOS
# -----------------------------------------------------------------------------
st.title("⚽ Football Analytics Engine")

partidos_hoy = obtener_partidos_hoy()

with st.expander("📅 **PARTIDOS PRÓXIMOS / EN VIVO**", expanded=True):
    if partidos_hoy:
        st.write(f"Se han encontrado **{len(partidos_hoy)} partido(s)** disponibles en las ligas monitorizadas:")
        cols_hoy = st.columns(min(3, len(partidos_hoy)))
        
        for idx, m in enumerate(partidos_hoy[:6]):
            col_idx = idx % min(3, len(partidos_hoy))
            comp_nom = m.get("competition", {}).get("name", "Liga")
            loc_n = m["homeTeam"]["name"]
            vis_n = m["awayTeam"]["name"]
            estado = m.get("status", "")
            hora = m.get("utcDate", "")[11:16] + " UTC"
            
            cols_hoy[col_idx].markdown(f"""
                <div class="match-today-card">
                    <span style="color: #00ff87; font-size: 0.75rem; font-weight: bold;">{comp_nom} • {hora} ({estado})</span><br>
                    <strong>{loc_n}</strong> vs <strong>{vis_n}</strong>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.info("ℹ️ No hay partidos en directo o para hoy en las 12 ligas soportadas. Utiliza el selector lateral para analizar cualquier equipo.")

st.divider()

# -----------------------------------------------------------------------------
# 6. CONTROLES Y SELECCIÓN DE EQUIPOS
# -----------------------------------------------------------------------------
st.sidebar.header("⚙️ Selector de Encuentro")
liga_sel = st.sidebar.selectbox("Competición", list(LIGAS.keys()), format_func=lambda x: LIGAS[x])

equipos = obtener_equipos(liga_sel)
if not equipos:
    st.error("Error al cargar los datos de la liga seleccionada.")
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

id_loc = eq_loc.get("id")
id_vis = eq_vis.get("id")

# CÁLCULO DE DATOS E HISTORIALES
df_loc_20 = obtener_ultimos_partidos(jugados, id_loc, n=20)
df_vis_20 = obtener_ultimos_partidos(jugados, id_vis, n=20)

racha_loc, ppm_loc_5 = calcular_forma_resumen(df_loc_20)
racha_vis, ppm_vis_5 = calcular_forma_resumen(df_vis_20)

atq_l, def_l = calcular_metricas_base(id_loc, jugados)
atq_v, def_v = calcular_metricas_base(id_vis, jugados)

exp_local = max(0.2, ((atq_l * def_v) / 1.30) * 1.10)
exp_vis = max(0.2, ((atq_v * def_l) / 1.30))
probs = calcular_simulacion(exp_local, exp_vis)

# MARCADOR SUPERIOR
st.markdown(f"""
    <div class="scoreboard-card">
        <div style="display: flex; justify-content: space-around; align-items: center; text-align: center;">
            <div style="flex: 1;" class="crest-container">
                <img src="{eq_loc.get('crest', '')}"/><br>
                <h2 style="margin: 8px 0 0 0; color: #ffffff;">{local_nom}</h2>
                <span style="color: #00ff87;">Forma (U5): {racha_loc}</span>
            </div>
            <div style="flex: 0.8; background: rgba(0,0,0,0.4); padding: 12px; border-radius: 12px; border: 1px solid #1e3a2f;">
                <span style="color: #a0aec0; font-size: 0.8rem;">PROBABILIDADES 1X2</span>
                <h3 style="color: #ffffff; margin: 5px 0;">{probs['1']*100:.1f}% | {probs['X']*100:.1f}% | {probs['2']*100:.1f}%</h3>
                <span style="color: #00ff87; font-size: 0.85rem;">xG: {exp_local:.2f} vs {exp_vis:.2f}</span>
            </div>
            <div style="flex: 1;" class="crest-container">
                <img src="{eq_vis.get('crest', '')}"/><br>
                <h2 style="margin: 8px 0 0 0; color: #ffffff;">{visitante_nom}</h2>
                <span style="color: #00ff87;">Forma (U5): {racha_vis}</span>
            </div>
        </div>
    </div>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 7. PESTAÑAS PRINCIPALES: H2H, ÚLTIMOS 20 Y FORMA
# -----------------------------------------------------------------------------
tab_h2h, tab_form, tab_odds = st.tabs([
    "⚔️ Enfrentamientos H2H", 
    "📈 ÚLTIMOS 20 PARTIDOS Y FORMA", 
    "🎯 Cuotas Justas & +EV"
])

# --- TAB 1: ENFRENTAMIENTOS CARA A CARA (H2H) ---
with tab_h2h:
    st.subheader(f"⚔️ Historial Cara a Cara: {local_nom} vs {visitante_nom}")
    
    wins_loc, draws_h2h, wins_vis, df_h2h = obtener_enfrentamientos_h2h(jugados, id_loc, id_vis)
    
    c_h1, c_h2, c_h3, c_h4 = st.columns(4)
    tot_h2h = wins_loc + draws_h2h + wins_vis
    c_h1.metric("Partidos Registrados", tot_h2h)
    c_h2.metric(f"Victorias {local_nom}", wins_loc)
    c_h3.metric("Empates", draws_h2h)
    c_h4.metric(f"Victorias {visitante_nom}", wins_vis)

    st.divider()
    if not df_h2h.empty:
        st.markdown("##### Detalle de Enfrentamientos Directos Recientes")
        st.dataframe(df_h2h, use_container_width=True, hide_index=True)
    else:
        st.info("No se registraron enfrentamientos directos entre ambos equipos en las últimas 2 temporadas.")

# --- TAB 2: ÚLTIMOS 20 PARTIDOS Y FORMA ACTUAL ---
with tab_form:
    st.subheader("📊 Análisis de Forma Reciente y Registro de 20 Partidos")
    
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        st.markdown(f"### 🏠 {local_nom}")
        st.write(f"**Racha Reciente (Últimos 5):** {racha_loc}")
        st.write(f"**Promedio Puntos (U5):** `{ppm_loc_5:.2f} pts/partido`")
        st.markdown("##### Historial (Últimos 20 encuentros)")
        if not df_loc_20.empty:
            st.dataframe(
                df_loc_20[["Fecha", "Condición", "Rival", "Resultado", "Estado"]], 
                use_container_width=True, 
                hide_index=True,
                height=400
            )

    with col_f2:
        st.markdown(f"### ✈️ {visitante_nom}")
        st.write(f"**Racha Reciente (Últimos 5):** {racha_vis}")
        st.write(f"**Promedio Puntos (U5):** `{ppm_vis_5:.2f} pts/partido`")
        st.markdown("##### Historial (Últimos 20 encuentros)")
        if not df_vis_20.empty:
            st.dataframe(
                df_vis_20[["Fecha", "Condición", "Rival", "Resultado", "Estado"]], 
                use_container_width=True, 
                hide_index=True,
                height=400
            )

# --- TAB 3: CUOTAS JUSTAS Y +EV ---
with tab_odds:
    st.subheader("💵 Matriz de Cuotas Justas Estimadas")
    col_o1, col_o2, col_o3 = st.columns(3)
    col_o1.metric(f"Victoria {local_nom}", f"@{1/probs['1']:.2f}", f"{probs['1']*100:.1f}%")
    col_o2.metric("Empate", f"@{1/probs['X']:.2f}", f"{probs['X']*100:.1f}%")
    col_o3.metric(f"Victoria {visitante_nom}", f"@{1/probs['2']:.2f}", f"{probs['2']*100:.1f}%")
