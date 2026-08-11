import math
import datetime
import requests
import pandas as pd
import streamlit as st

# -----------------------------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA Y ESTILOS UI
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Predictor Profesional de Fútbol Pro",
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
# 2. FUNCIONES DE API CON HISTÓRICO EXTENDIDO DE 2 AÑOS
# -----------------------------------------------------------------------------
@st.cache_data(ttl=86400)
def obtener_equipos_liga(liga_code):
    """Obtiene equipos, nombres cortos y URL de escudos."""
    url = f"{BASE_URL}competitions/{liga_code}/teams"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 429:
            st.warning("⚠️ Límite de peticiones alcanzado. Espera unos segundos.")
            return []
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
    """Obtiene histórico de partidos jugados de 2-3 temporadas y próximos programados."""
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
# 3. CÁLCULO DE MÉTRICAS (CONDICIÓN + DECAIMIENTO EXPONENCIAL + xG)
# -----------------------------------------------------------------------------
def calcular_metricas_completas(equipo_id, partidos_jugados, es_local=True, limite=20):
    partidos_general = [
        m for m in partidos_jugados
        if m["homeTeam"]["id"] == equipo_id or m["awayTeam"]["id"] == equipo_id
    ]
    partidos_general.sort(key=lambda x: x["utcDate"], reverse=True)
    ultimos_gen = partidos_general[:limite]

    partidos_condicion = [
        m for m in partidos_jugados
        if (m["homeTeam"]["id"] == equipo_id if es_local else m["awayTeam"]["id"] == equipo_id)
    ]
    partidos_condicion.sort(key=lambda x: x["utcDate"], reverse=True)
    ultimos_cond = partidos_condicion[:limite]

    def procesar_muestra(lista):
        if not lista:
            return 1.2, 1.2, 50.0, 0
        
        gf_weighted, gc_weighted, pts_weighted = 0.0, 0.0, 0.0
        peso_total = 0.0

        for idx, m in enumerate(lista):
            is_home = m["homeTeam"]["id"] == equipo_id
            score = m["score"]["fullTime"]
            gf = score["home"] if is_home else score["away"]
            gc = score["away"] if is_home else score["home"]

            if gf is None or gc is None:
                continue

            # Decaimiento Exponencial: Los últimos 5-7 partidos tienen el máximo peso
            peso = math.exp(-0.12 * idx)
            peso_total += peso

            gf_weighted += gf * peso
            gc_weighted += gc * peso

            if gf > gc: pts_weighted += 3 * peso
            elif gf == gc: pts_weighted += 1 * peso

        if peso_total == 0:
            return 1.2, 1.2, 50.0, 0

        atq_p = gf_weighted / peso_total
        def_p = gc_weighted / peso_total
        forma_p = round((pts_weighted / (peso_total * 3)) * 100, 1)

        return atq_p, def_p, forma_p, len(lista)

    atq_gen, def_gen, forma_gen, n_gen = procesar_muestra(ultimos_gen)
    atq_cond, def_cond, forma_cond, n_cond = procesar_muestra(ultimos_cond)

    # Combinación ponderada (60% condición local/visitante + 40% forma global)
    atq_final = (atq_cond * 0.60) + (atq_gen * 0.40)
    def_final = (def_cond * 0.60) + (def_gen * 0.40)

    # xG sintético ajustado por volumen reciente
    xg_sintetico = (atq_final * 0.85) + (atq_gen * 0.15)

    return {
        "atq_final": atq_final,
        "def_final": def_final,
        "atq_cond": atq_cond,
        "def_cond": def_cond,
        "xg_sintetico": xg_sintetico,
        "forma_gen": forma_gen,
        "forma_cond": forma_cond,
        "partidos_gen": n_gen,
        "partidos_cond": n_cond
    }

# -----------------------------------------------------------------------------
# 4. MODELOS MATEMÁTICOS DE POISSON Y DIXON-COLES
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

def generar_modelo_completo(exp_local, exp_vis, usar_dixon=True):
    raw_matrix = []
    total_prob = 0.0

    for g_loc in range(6):
        fila = []
        for g_vis in range(6):
            p_raw = poisson_pmf(exp_local, g_loc) * poisson_pmf(exp_vis, g_vis)
            tau = dixon_coles_tau(g_loc, g_vis, exp_local, exp_vis) if usar_dixon else 1.0
            p_adj = max(0.0, p_raw * tau)
            fila.append(p_adj)
            total_prob += p_adj
        raw_matrix.append(fila)

    norm_factor = 100.0 / total_prob if total_prob > 0 else 1.0

    matriz_norm = []
    lista_marcadores = []
    prob_1, prob_x, prob_2 = 0.0, 0.0, 0.0
    over_15, over_25, over_35 = 0.0, 0.0, 0.0
    btts_si = 0.0

    for g_loc in range(6):
        fila = []
        for g_vis in range(6):
            p = raw_matrix[g_loc][g_vis] * norm_factor
            fila.append(round(p, 2))

            if g_loc > g_vis: prob_1 += p
            elif g_loc == g_vis: prob_x += p
            else: prob_2 += p

            tot = g_loc + g_vis
            if tot > 1.5: over_15 += p
            if tot > 2.5: over_25 += p
            if tot > 3.5: over_35 += p

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

    res_1x2 = {"1": prob_1, "X": prob_x, "2": prob_2}
    res_ou = {
        "Over 1.5": over_15, "Under 1.5": 100 - over_15,
        "Over 2.5": over_25, "Under 2.5": 100 - over_25,
        "Over 3.5": over_35, "Under 3.5": 100 - over_35
    }
    res_btts = {"Sí": btts_si, "No": 100 - btts_si}

    return df_matriz, df_marcadores, res_1x2, res_ou, res_btts

def calcular_cuota_justa(prob_pct):
    if prob_pct <= 0: return 999.00
    return round(100.0 / prob_pct, 2)

# -----------------------------------------------------------------------------
# 5. INTERFAZ DE USUARIO PRINCIPAL
# -----------------------------------------------------------------------------
st.title("⚽ Predictor Profesional de Fútbol Pro")
st.caption("Análisis cuantitativo avanzado: Histórico de 2 años, Decaimiento Exponencial, xG, Factores Contextuales y Cuotas Justas (+EV).")

st.sidebar.header("⚙️ 1. Selección de Encuentro")
liga_sel = st.sidebar.selectbox("Competición", list(LIGAS.keys()), format_func=lambda x: LIGAS[x])

equipos = obtener_equipos_liga(liga_sel)
if not equipos:
    st.error("No se pudieron obtener datos de la competición seleccionada. Intenta de nuevo.")
    st.stop()

equipos_dict = {e["nombre"]: e for e in equipos}
nombres_equipos = list(equipos_dict.keys())
partidos_jugados, partidos_programados = obtener_partidos_historico_2anos(liga_sel)

modo_seleccion = st.sidebar.radio("Modo de Selección", ["📅 Próximos Partidos", "✏️ Personalizado"])

if modo_seleccion == "📅 Próximos Partidos" and partidos_programados:
    opciones = [f"{m.get('utcDate','')[:10]} | {m['homeTeam']['name']} vs {m['awayTeam']['name']}" for m in partidos_programados[:15]]
    partido_sel = st.sidebar.selectbox("Seleccionar Partido Programado", opciones)
    idx = opciones.index(partido_sel)
    local_nom = partidos_programados[idx]["homeTeam"]["name"]
    visitante_nom = partidos_programados[idx]["awayTeam"]["name"]
else:
    local_nom = st.sidebar.selectbox("Equipo Local", nombres_equipos, index=0)
    vis_opciones = [n for n in nombres_equipos if n != local_nom]
    visitante_nom = st.sidebar.selectbox("Equipo Visitante", vis_opciones, index=0)

# PANEL DE AJUSTES AVANZADOS Y CONTEXTUALES
st.sidebar.divider()
st.sidebar.header("🛠️ 2. Parámetros y Contexto")

muestra_partidos = st.sidebar.slider("Partidos del Histórico a analizar", 5, 25, 20)
factor_campo = st.sidebar.slider("Ventaja de Localía (+%)", 0, 30, 15) / 100.0 + 1.0
usar_dixon = st.sidebar.checkbox("Ajuste Dixon-Coles (Empates)", value=True)

with st.sidebar.expander("🚨 Bajas y Sanciones"):
    baja_ataque_loc = st.slider(f"Bajas Ataque ({local_nom})", 0, 30, 0, step=5) / 100.0
    baja_def_loc = st.slider(f"Bajas Defensa ({local_nom})", 0, 30, 0, step=5) / 100.0
    baja_ataque_vis = st.slider(f"Bajas Ataque ({visitante_nom})", 0, 30, 0, step=5) / 100.0
    baja_def_vis = st.slider(f"Bajas Defensa ({visitante_nom})", 0, 30, 0, step=5) / 100.0

with st.sidebar.expander("⚡ Fatiga y Calendario"):
    descanso_loc = st.select_slider(f"Días de Descanso ({local_nom})", options=[2, 3, 4, 5, 7], value=4)
    descanso_vis = st.select_slider(f"Días de Descanso ({visitante_nom})", options=[2, 3, 4, 5, 7], value=4)

with st.sidebar.expander("🎯 Motivación y Árbitro"):
    motivacion_loc = st.slider(f"Motivación/Necesidad Puntos ({local_nom})", -10, 10, 0, step=5) / 100.0
    motivacion_vis = st.slider(f"Motivación/Necesidad Puntos ({visitante_nom})", -10, 10, 0, step=5) / 100.0
    perfil_arbitro = st.selectbox("Perfil del Árbitro", ["Neutral / Promedio", "Estricto (Alta exigencia / Tarjetas)", "Permisivo (Deja jugar)"])

# -----------------------------------------------------------------------------
# 6. EJECUCIÓN Y PRESENTACIÓN
# -----------------------------------------------------------------------------
if st.button("🚀 Calcular Predicción Profesional", type="primary"):
    eq_loc = equipos_dict.get(local_nom, {})
    eq_vis = equipos_dict.get(visitante_nom, {})

    id_local = eq_loc.get("id")
    id_vis = eq_vis.get("id")

    # Métricas base con decaimiento exponencial
    stats_loc = calcular_metricas_completas(id_local, partidos_jugados, es_local=True, limite=muestra_partidos)
    stats_vis = calcular_metricas_completas(id_vis, partidos_jugados, es_local=False, limite=muestra_partidos)

    # Modificadores Contextuales
    fatiga_loc = 0.92 if descanso_loc <= 2 else (0.96 if descanso_loc == 3 else 1.0)
    fatiga_vis = 0.92 if descanso_vis <= 2 else (0.96 if descanso_vis == 3 else 1.0)

    atq_loc_adj = stats_loc["atq_final"] * (1.0 - baja_ataque_loc) * (1.0 + motivacion_loc) * fatiga_loc
    def_loc_adj = stats_loc["def_final"] * (1.0 + baja_def_loc)

    atq_vis_adj = stats_vis["atq_final"] * (1.0 - baja_ataque_vis) * (1.0 + motivacion_vis) * fatiga_vis
    def_vis_adj = stats_vis["def_final"] * (1.0 + baja_def_vis)

    media_liga = 1.35
    exp_local = max(0.2, ((atq_loc_adj * def_vis_adj) / media_liga) * factor_campo)
    exp_vis = max(0.2, ((atq_vis_adj * def_loc_adj) / media_liga))

    # Matriz y Marcadores
    df_matriz, df_marcadores, res_1x2, res_ou, res_btts = generar_modelo_completo(exp_local, exp_vis, usar_dixon=usar_dixon)
    top_marcador = df_marcadores.iloc[0]

    # Mercados Secundarios (Córners & Tarjetas)
    exp_corners_loc = round((exp_local * 2.8) + 2.5, 1)
    exp_corners_vis = round((exp_vis * 2.5) + 2.0, 1)
    tot_corners = exp_corners_loc + exp_corners_vis

    mod_arbitro = 1.25 if perfil_arbitro == "Estricto (Alta exigencia / Tarjetas)" else (0.80 if perfil_arbitro == "Permisivo (Deja jugar)" else 1.0)
    tarjetas_est = round((4.2 + (abs(motivacion_loc) + abs(motivacion_vis)) * 2) * mod_arbitro, 1)

    # TARJETA PRINCIPAL DE PARTIDO CON ESCUDOS
    st.markdown(f"""
        <div class="match-card">
            <div style="display: flex; justify-content: space-around; align-items: center; text-align: center;">
                <div style="flex: 1;">
                    <img src="{eq_loc.get('crest', '')}" class="crest-img"/><br>
                    <h2 style="margin: 5px 0;">{local_nom}</h2>
                    <span style="color: #cbd5e0;">Forma Local: {stats_loc['forma_cond']:.0f}%</span>
                </div>
                <div style="flex: 0.8;">
                    <h3 style="color: #a0aec0; margin: 0;">MARCADOR MÁS PROBABLE</h3>
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
                    <span style="color: #cbd5e0;">Forma Visita: {stats_vis['forma_cond']:.0f}%</span>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # PESTAÑAS PRINCIPALES INTEGRADAS (4 PESTAÑAS)
    tab1, tab2, tab3, tab4 = st.tabs([
        "🎯 Predicción & Marcadores", 
        "💰 Cuotas Justas & Valor (+EV)", 
        "🚩 Mercados Secundarios", 
        "⚔️ H2H & Métricas Avanzadas"
    ])

    # PESTAÑA 1: PREDICCIÓN & MARCADORES
    with tab1:
        st.subheader("🎲 Probabilidades Principales (1X2)")
        c1, c2, c3 = st.columns(3)
        c1.metric(f"Victoria {local_nom} (1)", f"{res_1x2['1']:.1f}%", f"Cuota Justa: @{calcular_cuota_justa(res_1x2['1']):.2f}")
        c2.metric("Empate (X)", f"{res_1x2['X']:.1f}%", f"Cuota Justa: @{calcular_cuota_justa(res_1x2['X']):.2f}")
        c3.metric(f"Victoria {visitante_nom} (2)", f"{res_1x2['2']:.1f}%", f"Cuota Justa: @{calcular_cuota_justa(res_1x2['2']):.2f}")

        st.divider()

        col_l, col_r = st.columns(2)
        with col_l:
            st.subheader("📊 Top 8 Marcadores Más Probables")
            df_top8 = df_marcadores.head(8).copy()
            df_top8["Cuota Justa"] = df_top8["Probabilidad (%)"].apply(lambda p: f"@{calcular_cuota_justa(p):.2f}")
            st.dataframe(df_top8[["Marcador", "Probabilidad (%)", "Cuota Justa"]], use_container_width=True, hide_index=True)
        
        with col_r:
            st.subheader("🔥 Rendimiento Esperado (Goles xG)")
            st.metric(f"xG Ajustado {local_nom}", f"{exp_local:.2f} goles")
            st.metric(f"xG Ajustado {visitante_nom}", f"{exp_vis:.2f} goles")

        st.divider()
        st.subheader("🗺️ Matriz de Marcadores Exactos (%)")
        st.dataframe(df_matriz.style.highlight_max(axis=None, color="#2e7d32"), use_container_width=True)

    # PESTAÑA 2: CUOTAS JUSTAS Y APUESTAS DE VALOR (+EV)
    with tab2:
        st.subheader("💡 Guía de Cuotas Justas (Fair Odds)")
        st.info("💡 **Regla de Valor (+EV):** Compara la Cuota Justa calculada con la cuota de tu casa de apuestas. Si la casa paga una cuota mayor a nuestra Cuota Justa, la apuesta tiene valor positivo.")

        st.markdown("### 1. Mercado Ganador del Partido (1X2)")
        df_1x2_val = pd.DataFrame([
            {"Mercado": f"Victoria {local_nom} (1)", "Probabilidad": f"{res_1x2['1']:.1f}%", "Cuota Justa": f"@{calcular_cuota_justa(res_1x2['1']):.2f}", "Condición +EV": f"Aposta si la casa te paga MÁS de @{calcular_cuota_justa(res_1x2['1']):.2f}"},
            {"Mercado": "Empate (X)", "Probabilidad": f"{res_1x2['X']:.1f}%", "Cuota Justa": f"@{calcular_cuota_justa(res_1x2['X']):.2f}", "Condición +EV": f"Aposta si la casa te paga MÁS de @{calcular_cuota_justa(res_1x2['X']):.2f}"},
            {"Mercado": f"Victoria {visitante_nom} (2)", "Probabilidad": f"{res_1x2['2']:.1f}%", "Cuota Justa": f"@{calcular_cuota_justa(res_1x2['2']):.2f}", "Condición +EV": f"Aposta si la casa te paga MÁS de @{calcular_cuota_justa(res_1x2['2']):.2f}"}
        ])
        st.dataframe(df_1x2_val, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("### 2. Mercados de Goles (Over/Under y BTTS)")
        col_g1, col_g2 = st.columns(2)
        
        with col_g1:
            st.markdown("#### Líneas Over / Under")
            df_ou_val = pd.DataFrame([
                {"Línea": "Over 1.5 Goles", "Prob. Modelo": f"{res_ou['Over 1.5']:.1f}%", "Cuota Justa": f"@{calcular_cuota_justa(res_ou['Over 1.5']):.2f}"},
                {"Línea": "Under 1.5 Goles", "Prob. Modelo": f"{res_ou['Under 1.5']:.1f}%", "Cuota Justa": f"@{calcular_cuota_justa(res_ou['Under 1.5']):.2f}"},
                {"Línea": "Over 2.5 Goles", "Prob. Modelo": f"{res_ou['Over 2.5']:.1f}%", "Cuota Justa": f"@{calcular_cuota_justa(res_ou['Over 2.5']):.2f}"},
                {"Línea": "Under 2.5 Goles", "Prob. Modelo": f"{res_ou['Under 2.5']:.1f}%", "Cuota Justa": f"@{calcular_cuota_justa(res_ou['Under 2.5']):.2f}"},
                {"Línea": "Over 3.5 Goles", "Prob. Modelo": f"{res_ou['Over 3.5']:.1f}%", "Cuota Justa": f"@{calcular_cuota_justa(res_ou['Over 3.5']):.2f}"},
                {"Línea": "Under 3.5 Goles", "Prob. Modelo": f"{res_ou['Under 3.5']:.1f}%", "Cuota Justa": f"@{calcular_cuota_justa(res_ou['Under 3.5']):.2f}"}
            ])
            st.dataframe(df_ou_val, use_container_width=True, hide_index=True)

        with col_g2:
            st.markdown("#### Ambos Equipos Anotan (BTTS)")
            df_btts_val = pd.DataFrame([
                {"Resultado": "Ambos Anotan - SÍ", "Prob. Modelo": f"{res_btts['Sí']:.1f}%", "Cuota Justa": f"@{calcular_cuota_justa(res_btts['Sí']):.2f}"},
                {"Resultado": "Ambos Anotan - NO", "Prob. Modelo": f"{res_btts['No']:.1f}%", "Cuota Justa": f"@{calcular_cuota_justa(res_btts['No']):.2f}"}
            ])
            st.dataframe(df_btts_val, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("### 🧮 Comprobador Rápido de Cuotas")
        col_in1, col_in2 = st.columns(2)
        cuota_ofrecida = col_in1.number_input("Cuota ofrecida en tu casa de apuestas:", min_value=1.01, value=2.20, step=0.05)
        prob_analizada = col_in2.number_input("Probabilidad de tu modelo (%):", min_value=1.0, max_value=99.0, value=round(res_1x2['1'], 1), step=0.5)

        ev = ((prob_analizada / 100.0) * cuota_ofrecida) - 1.0
        if ev > 0:
            st.success(f"✅ **¡Apuesta de Valor (+EV)!** Valor Esperado: **+{ev*100:.1f}%**. Necesitabas cuota mínima @{100/prob_analizada:.2f} y te ofrecen @{cuota_ofrecida:.2f}.")
        else:
            st.error(f"❌ **Sin Valor (-EV).** Valor Esperado: **{ev*100:.1f}%**. Para esta probabilidad requerías mínimo cuota @{100/prob_analizada:.2f}.")

    # PESTAÑA 3: MERCADOS SECUNDARIOS
    with tab3:
        st.subheader("🚩 Estimación de Saques de Esquina (Córners)")
        col_c1, col_c2, col_c3 = st.columns(3)
        col_c1.metric(f"Córners {local_nom}", f"{exp_corners_loc}")
        col_c2.metric(f"Córners {visitante_nom}", f"{exp_corners_vis}")
        col_c3.metric("Total Córners Esperados", f"{tot_corners:.1f}")

        st.divider()
        st.subheader("🟨 Estimación de Tarjetas (Amonestaciones)")
        st.metric("Total Tarjetas Esperadas", f"{tarjetas_est} Tarjetas", f"Ajustado por árbitro: {perfil_arbitro}")

    # PESTAÑA 4: ENFRENTAMIENTOS DIRECTOS Y DESGROSE TÉCNICO
    with tab4:
        st.subheader("⚔️ Enfrentamientos Directos Recientes (H2H 2 Años)")
        partidos_h2h = [
            m for m in partidos_jugados
            if (m["homeTeam"]["id"] == id_local and m["awayTeam"]["id"] == id_vis) or
               (m["homeTeam"]["id"] == id_vis and m["awayTeam"]["id"] == id_local)
        ]
        
        if partidos_h2h:
            h2h_data = []
            v_loc, emp, v_vis = 0, 0, 0
            for m in partidos_h2h:
                fecha = m.get("utcDate", "")[:10]
                loc_m = m["homeTeam"]["name"]
                vis_m = m["awayTeam"]["name"]
                sc = m["score"]["fullTime"]
                gl, gv = sc["home"], sc["away"]
                
                if loc_m == local_nom:
                    if gl > gv: v_loc += 1
                    elif gl == gv: emp += 1
                    else: v_vis += 1
                else:
                    if gv > gl: v_loc += 1
                    elif gl == gv: emp += 1
                    else: v_vis += 1

                h2h_data.append({"Fecha": fecha, "Partido": f"{loc_m} {gl} - {gv} {vis_m}"})
            
            hc1, hc2, hc3 = st.columns(3)
            hc1.metric(f"Victorias {local_nom}", v_loc)
            hc2.metric("Empates", emp)
            hc3.metric(f"Victorias {visitante_nom}", v_vis)
            
            st.table(pd.DataFrame(h2h_data))
        else:
            st.info("No se encontraron enfrentamientos directos en la muestra del histórico.")

        st.divider()
        st.subheader("📋 Resumen de Ajustes de Contexto Aplicados")
        st.json({
            "Ajustes_Local": {
                "Goles Promedio Condición": f"{stats_loc['atq_cond']:.2f}",
                "Impacto Bajas Ataque": f"-{baja_ataque_loc*100}%",
                "Impacto Bajas Defensa": f"+{baja_def_loc*100}%",
                "Factor Fatiga": f"{descanso_loc} días descanso ({fatiga_loc}x)",
                "Motivación Extra": f"{motivacion_loc*100}%"
            },
            "Ajustes_Visitante": {
                "Goles Promedio Condición": f"{stats_vis['atq_cond']:.2f}",
                "Impacto Bajas Ataque": f"-{baja_ataque_vis*100}%",
                "Impacto Bajas Defensa": f"+{baja_def_vis*100}%",
                "Factor Fatiga": f"{descanso_vis} días descanso ({fatiga_vis}x)",
                "Motivación Extra": f"{motivacion_vis*100}%"
            }
        })
