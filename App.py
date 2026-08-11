import math
import datetime
import requests
import pandas as pd
import streamlit as st

# -----------------------------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA Y ESTILOS
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Predictor Profesional Pro",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .match-card {
        background: linear-gradient(135deg, #0e1117 0%, #1a1f2c 100%);
        border: 1px solid #2d3748;
        border-radius: 12px;
        padding: 20px;
        color: white;
        margin-bottom: 20px;
    }
    .crest-img {
        max-height: 80px;
        max-width: 80px;
        object-fit: contain;
    }
    .stMetric {
        background-color: #1e2430;
        padding: 10px;
        border-radius: 8px;
    }
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 1. AUTENTICACIÓN API
# -----------------------------------------------------------------------------
try:
    API_KEY = st.secrets["FOOTBALL_API_KEY"]
except KeyError:
    st.error("⚠️ No se encontró la API Key. Añade 'FOOTBALL_API_KEY' en los Secrets de Streamlit Cloud.")
    st.stop()

HEADERS = {"X-Auth-Token": API_KEY}
BASE_URL = "https://api.football-data.org/v4/"

LIGAS = {
    "PD": "🇪🇸 LaLiga (España)",
    "PL": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League (Inglaterra)",
    "SA": "🇮🇹 Serie A (Italia)",
    "BL1": "🇩🇪 Bundesliga (Alemania)",
    "FL1": "🇫🇷 Ligue 1 (Francia)",
    "DED": "🇳🇱 Eredivisie (Países Bajos)",
    "PPL": "🇵🇹 Primeira Liga (Portugal)",
    "ELC": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Championship (Inglaterra 2ª)",
    "BSA": "🇧🇷 Serie A (Brasil)",
    "CL": "🇪🇺 UEFA Champions League"
}

# -----------------------------------------------------------------------------
# 2. OBTENCIÓN DE DATOS HISTÓRICOS
# -----------------------------------------------------------------------------
@st.cache_data(ttl=86400)
def obtener_equipos_liga(liga_code):
    url = f"{BASE_URL}competitions/{liga_code}/teams"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return []
        teams_data = res.json().get("teams", [])
        equipos = [
            {
                "id": t["id"],
                "nombre": t["name"],
                "shortName": t.get("shortName", t["name"]),
                "crest": t.get("crest", "")
            }
            for t in teams_data
        ]
        return sorted(equipos, key=lambda x: x["nombre"])
    except Exception:
        return []

@st.cache_data(ttl=7200)
def obtener_partidos_historico_2anos(liga_code):
    anio_actual = datetime.datetime.now().year
    anio_base = anio_actual - 1 if datetime.datetime.now().month < 7 else anio_actual
    seasons = [anio_base, anio_base - 1, anio_base - 2]
    
    todos_jugados, partidos_programados = [], []

    for idx, season in enumerate(seasons):
        url = f"{BASE_URL}competitions/{liga_code}/matches?season={season}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                matches = res.json().get("matches", [])
                if idx == 0:
                    partidos_programados = [m for m in matches if m.get("status") in ["SCHEDULED", "TIMED", "LIVE"]]
                todos_jugados.extend([m for m in matches if m.get("status") == "FINISHED"])
        except Exception:
            continue

    return todos_jugados, partidos_programados

# -----------------------------------------------------------------------------
# 3. CÁLCULO DE MÉTRICAS PONDERADAS (DECAIMIENTO EXPONENCIAL + xG SINTÉTICO)
# -----------------------------------------------------------------------------
def calcular_metricas_avanzadas(equipo_id, partidos_jugados, es_local=True, peso_forma_reciente=True):
    partidos = [
        m for m in partidos_jugados
        if m["homeTeam"]["id"] == equipo_id or m["awayTeam"]["id"] == equipo_id
    ]
    partidos.sort(key=lambda x: x["utcDate"], reverse=True)

    if not partidos:
        return {"atq": 1.2, "def": 1.2, "xg_prom": 1.3, "forma_5": 50.0}

    gf_weighted, gc_weighted = 0.0, 0.0
    peso_total = 0.0
    puntos_ultimos_5 = 0

    for idx, m in enumerate(partidos[:25]): # Muestra amplia pero fuertemente ponderada al inicio
        is_home = m["homeTeam"]["id"] == equipo_id
        score = m["score"]["fullTime"]
        gf = score["home"] if is_home else score["away"]
        gc = score["away"] if is_home else score["home"]

        if gf is None or gc is None:
            continue

        # Decaimiento Exponencial: Los primeros 5-7 partidos tienen el 70% del peso total
        if peso_forma_reciente:
            peso = math.exp(-0.15 * idx) 
        else:
            peso = 1.0 / (1.0 + 0.05 * idx)

        peso_total += peso
        gf_weighted += gf * peso
        gc_weighted += gc * peso

        if idx < 5:
            if gf > gc: puntos_ultimos_5 += 3
            elif gf == gc: puntos_ultimos_5 += 1

    atq_prom = gf_weighted / peso_total if peso_total > 0 else 1.2
    def_prom = gc_weighted / peso_total if peso_total > 0 else 1.2

    # Estimación de xG sintético basada en rendimiento relativo de ataque
    xg_sintetico = (atq_prom * 0.85) + (gf_weighted / (peso_total * 1.1) if peso_total > 0 else 0)

    return {
        "atq": atq_prom,
        "def": def_prom,
        "xg_prom": xg_sintetico,
        "forma_5": (puntos_ultimos_5 / 15.0) * 100
    }

# -----------------------------------------------------------------------------
# 4. MODELOS MATEMÁTICOS (GOLES, CÓRNERS, TARJETAS)
# -----------------------------------------------------------------------------
def poisson_pmf(lmbda, k):
    if lmbda <= 0: return 0.0
    return (lmbda ** k) * math.exp(-lmbda) / math.factorial(k)

def dixon_coles_tau(x, y, lmbda, mu, rho=-0.11):
    if x == 0 and y == 0: return 1.0 - (lmbda * mu * rho)
    elif x == 1 and y == 0: return 1.0 + (mu * rho)
    elif x == 0 and y == 1: return 1.0 + (lmbda * rho)
    elif x == 1 and y == 1: return 1.0 - rho
    return 1.0

def generar_modelo_completo(exp_local, exp_vis):
    raw_matrix = []
    total_prob = 0.0

    for g_loc in range(6):
        fila = []
        for g_vis in range(6):
            p_raw = poisson_pmf(exp_local, g_loc) * poisson_pmf(exp_vis, g_vis)
            tau = dixon_coles_tau(g_loc, g_vis, exp_local, exp_vis)
            p_adj = max(0.0, p_raw * tau)
            fila.append(p_adj)
            total_prob += p_adj
        raw_matrix.append(fila)

    norm_factor = 100.0 / total_prob if total_prob > 0 else 1.0

    matriz_norm = []
    lista_marcadores = []
    prob_1, prob_x, prob_2 = 0.0, 0.0, 0.0
    over_25 = 0.0
    btts_si = 0.0

    for g_loc in range(6):
        fila = []
        for g_vis in range(6):
            p = raw_matrix[g_loc][g_vis] * norm_factor
            fila.append(round(p, 2))

            if g_loc > g_vis: prob_1 += p
            elif g_loc == g_vis: prob_x += p
            else: prob_2 += p

            if (g_loc + g_vis) > 2.5: over_25 += p
            if g_loc >= 1 and g_vis >= 1: btts_si += p

            lista_marcadores.append({
                "Marcador": f"{g_loc} - {g_vis}",
                "Probabilidad (%)": round(p, 2),
                "Goles Local": g_loc,
                "Goles Visitante": g_vis
            })
        matriz_norm.append(fila)

    df_matriz = pd.DataFrame(matriz_norm, index=[f"{i} Loc" for i in range(6)], columns=[f"{j} Vis" for j in range(6)])
    df_marcadores = pd.DataFrame(lista_marcadores).sort_values(by="Probabilidad (%)", ascending=False)

    return df_matriz, df_marcadores, {"1": prob_1, "X": prob_x, "2": prob_2}, over_25, btts_si

def calcular_cuota_justa(prob):
    return round(100.0 / prob, 2) if prob > 0 else 999.00

# -----------------------------------------------------------------------------
# 5. INTERFAZ Y AJUSTES CONTEXTUALES
# -----------------------------------------------------------------------------
st.title("⚽ Predictor Profesional Pro (Ajuste Avanzado)")
st.caption("Modelo con xG Sintético, Decaimiento Exponencial (Últimos 5-7 partidos) y Factores Contextuales.")

st.sidebar.header("⚙️ 1. Competición y Selección")
liga_sel = st.sidebar.selectbox("Liga", list(LIGAS.keys()), format_func=lambda x: LIGAS[x])
equipos = obtener_equipos_liga(liga_sel)

if not equipos:
    st.error("Error al cargar equipos de la competición.")
    st.stop()

equipos_dict = {e["nombre"]: e for e in equipos}
nombres_equipos = list(equipos_dict.keys())
partidos_jugados, partidos_programados = obtener_partidos_historico_2anos(liga_sel)

modo_seleccion = st.sidebar.radio("Modo de Selección", ["📅 Próximos Partidos", "✏️ Personalizado"])

if modo_seleccion == "📅 Próximos Partidos" and partidos_programados:
    opciones = [f"{m.get('utcDate','')[:10]} | {m['homeTeam']['name']} vs {m['awayTeam']['name']}" for m in partidos_programados[:15]]
    partido_sel = st.sidebar.selectbox("Seleccionar Encuentro", opciones)
    idx = opciones.index(partido_sel)
    local_nom = partidos_programados[idx]["homeTeam"]["name"]
    visitante_nom = partidos_programados[idx]["awayTeam"]["name"]
else:
    local_nom = st.sidebar.selectbox("Equipo Local", nombres_equipos, index=0)
    vis_opciones = [n for n in nombres_equipos if n != local_nom]
    visitante_nom = st.sidebar.selectbox("Equipo Visitante", vis_opciones, index=0)

# PANEL DE AJUSTES AVANZADOS Y CONTEXTUALES
st.sidebar.divider()
st.sidebar.header("🛠️ 2. Factores Contextuales")

with st.sidebar.expander("🚨 Bajas y Sanciones"):
    baja_ataque_loc = st.slider(f"Impacto Bajas Ataque ({local_nom})", 0, 30, 0, step=5, help="% de reducción en potencia ofensiva") / 100.0
    baja_def_loc = st.slider(f"Impacto Bajas Defensa ({local_nom})", 0, 30, 0, step=5, help="% de reducción en solidez defensiva") / 100.0
    baja_ataque_vis = st.slider(f"Impacto Bajas Ataque ({visitante_nom})", 0, 30, 0, step=5) / 100.0
    baja_def_vis = st.slider(f"Impacto Bajas Defensa ({visitante_nom})", 0, 30, 0, step=5) / 100.0

with st.sidebar.expander("⚡ Fatiga y Calendario"):
    descanso_loc = st.select_slider(f"Días de Descanso ({local_nom})", options=[2, 3, 4, 5, 7], value=4)
    descanso_vis = st.select_slider(f"Días de Descanso ({visitante_nom})", options=[2, 3, 4, 5, 7], value=4)

with st.sidebar.expander("🎯 Motivación y Árbitro"):
    motivacion_loc = st.slider(f"Motivación/Necesidad Puntos ({local_nom})", -10, 10, 0, step=5) / 100.0
    motivacion_vis = st.slider(f"Motivación/Necesidad Puntos ({visitante_nom})", -10, 10, 0, step=5) / 100.0
    perfil_arbitro = st.selectbox("Perfil del Árbitro Assignado", ["Neutral / Promedio", "Estricto (Alta exigencia / Tarjetas)", "Permisivo (Deja jugar)"])

# -----------------------------------------------------------------------------
# 6. PROCESAMIENTO Y RESULTADOS
# -----------------------------------------------------------------------------
if st.button("🚀 Calcular Predicción Ajustada", type="primary"):
    eq_loc = equipos_dict.get(local_nom, {})
    eq_vis = equipos_dict.get(visitante_nom, {})

    # Obtención de métricas base
    m_loc = calcular_metricas_avanzadas(eq_loc["id"], partidos_jugados, es_local=True)
    m_vis = calcular_metricas_avanzadas(eq_vis["id"], partidos_jugados, es_local=False)

    # Ajustes por Factores Contextuales
    # 1. Fatiga (Menos de 3 días penaliza 8%)
    mod_fatiga_loc = 0.92 if descanso_loc <= 2 else (0.96 if descanso_loc == 3 else 1.0)
    mod_fatiga_vis = 0.92 if descanso_vis <= 2 else (0.96 if descanso_vis == 3 else 1.0)

    # 2. Bajas y Motivación
    atq_loc_adj = m_loc["atq"] * (1.0 - baja_ataque_loc) * (1.0 + motivacion_loc) * mod_fatiga_loc
    def_loc_adj = m_loc["def"] * (1.0 + baja_def_loc) # Si la defensa empeora, recibe más goles
    atq_vis_adj = m_vis["atq"] * (1.0 - baja_ataque_vis) * (1.0 + motivacion_vis) * mod_fatiga_vis
    def_vis_adj = m_vis["def"] * (1.0 + baja_def_vis)

    # Ventaja de localía base (+12%)
    media_liga = 1.35
    exp_loc = max(0.2, ((atq_loc_adj * def_vis_adj) / media_liga) * 1.12)
    exp_vis = max(0.2, ((atq_vis_adj * def_loc_adj) / media_liga))

    # Matriz y Marcadores
    df_matriz, df_marcadores, res_1x2, over_25, btts_si = generar_modelo_completo(exp_loc, exp_vis)
    top_marcador = df_marcadores.iloc[0]

    # Mercados Secundarios (Estimaciones de Córners y Tarjetas)
    exp_corners_loc = round((exp_loc * 2.8) + 2.5, 1)
    exp_corners_vis = round((exp_vis * 2.5) + 2.0, 1)
    tot_corners = exp_corners_loc + exp_corners_vis

    mod_arbitro = 1.25 if perfil_arbitro == "Estricto (Alta exigencia / Tarjetas)" else (0.80 if perfil_arbitro == "Permisivo (Deja jugar)" else 1.0)
    tarjetas_est = round((4.2 + (abs(motivacion_loc) + abs(motivacion_vis)) * 2) * mod_arbitro, 1)

    # VISUALIZACIÓN DE RESULTADOS
    st.markdown(f"""
        <div class="match-card">
            <div style="display: flex; justify-content: space-around; align-items: center; text-align: center;">
                <div style="flex: 1;">
                    <img src="{eq_loc.get('crest', '')}" class="crest-img"/><br>
                    <h2 style="margin: 5px 0;">{local_nom}</h2>
                    <p>Forma Reciente (5p): <b>{m_loc['forma_5']:.0f}%</b></p>
                </div>
                <div style="flex: 0.8;">
                    <h3 style="color: #a0aec0; margin: 0;">PREDICCIÓN FINAL</h3>
                    <h1 style="color: #48bb78; font-size: 3rem; margin: 5px 0;">
                        {top_marcador['Goles Local']} - {top_marcador['Goles Visitante']}
                    </h1>
                    <span style="background: #2b6cb0; padding: 4px 12px; border-radius: 12px; font-weight: bold;">
                        Probabilidad: {top_marcador['Probabilidad (%)']:.1f}%
                    </span>
                </div>
                <div style="flex: 1;">
                    <img src="{eq_vis.get('crest', '')}" class="crest-img"/><br>
                    <h2 style="margin: 5px 0;">{visitante_nom}</h2>
                    <p>Forma Reciente (5p): <b>{m_vis['forma_5']:.0f}%</b></p>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["🎯 Probabilidades 1X2 & xG", "🚩 Mercados Secundarios (Córners/Tarjetas)", "📊 Desglose Técnico"])

    with tab1:
        c1, c2, c3 = st.columns(3)
        c1.metric(f"Victoria {local_nom}", f"{res_1x2['1']:.1f}%", f"Cuota Justa: @{calcular_cuota_justa(res_1x2['1']):.2f}")
        c2.metric("Empate (X)", f"{res_1x2['X']:.1f}%", f"Cuota Justa: @{calcular_cuota_justa(res_1x2['X']):.2f}")
        c3.metric(f"Victoria {visitante_nom}", f"{res_1x2['2']:.1f}%", f"Cuota Justa: @{calcular_cuota_justa(res_1x2['2']):.2f}")

        st.divider()
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("🔥 Expectativa de Goles (xG Sintético)")
            st.metric(f"xG Esperado {local_nom}", f"{exp_loc:.2f}")
            st.metric(f"xG Esperado {visitante_nom}", f"{exp_vis:.2f}")
        with col_b:
            st.subheader("💡 Líneas Populares")
            st.metric("Over 2.5 Goles", f"{over_25:.1f}%", f"Cuota Justa: @{calcular_cuota_justa(over_25):.2f}")
            st.metric("Ambos Equipos Anotan (BTTS)", f"{btts_si:.1f}%", f"Cuota Justa: @{calcular_cuota_justa(btts_si):.2f}")

    with tab2:
        st.subheader("🚩 Estimación de Saques de Esquina (Córners)")
        col_c1, col_c2, col_c3 = st.columns(3)
        col_c1.metric(f"Córners {local_nom}", f"{exp_corners_loc}")
        col_c2.metric(f"Córners {visitante_nom}", f"{exp_corners_vis}")
        col_c3.metric("Total Córners Esperados", f"{tot_corners:.1f}")

        st.divider()
        st.subheader("🟨 Estimación de Tarjetas (Amonestaciones)")
        st.metric("Total Tarjetas Esperadas", f"{tarjetas_est} Tarjetas", f"Ajuste por Árbitro ({perfil_arbitro})")

    with tab3:
        st.subheader("⚙️ Factores Aplicados a este Cálculo")
        st.json({
            "Ajustes_Local": {
                "Reducción Bajas Ataque": f"-{baja_ataque_loc*100}%",
                "Penalización Bajas Defensa": f"+{baja_def_loc*100}%",
                "Factor Fatiga (Días Rest)": f"{descanso_loc} días ({mod_fatiga_loc}x)",
                "Motivación Extra": f"{motivacion_loc*100}%"
            },
            "Ajustes_Visitante": {
                "Reducción Bajas Ataque": f"-{baja_ataque_vis*100}%",
                "Penalización Bajas Defensa": f"+{baja_def_vis*100}%",
                "Factor Fatiga (Días Rest)": f"{descanso_vis} días ({mod_fatiga_vis}x)",
                "Motivación Extra": f"{motivacion_vis*100}%"
            }
        })
    
