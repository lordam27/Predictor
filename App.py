import math
import datetime
import requests
import pandas as pd
import streamlit as st

# -----------------------------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA Y ESTILOS
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Predictor Profesional de Fútbol",
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
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 1. API Y AUTENTICACIÓN
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
    "CL": "🇪🇺 UEFA Champions League",
    "EC": "🇪🇺 Eurocopa (UEFA)",
    "WC": "🌍 Copa del Mundo (FIFA)"
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
            st.warning("⚠️ Límite de peticiones de la API alcanzado. Espera 60 segundos.")
            return []
        if res.status_code != 200:
            st.error(f"Error {res.status_code} al obtener equipos de la API.")
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
    except Exception as e:
        st.error(f"Error de conexión: {e}")
        return []

@st.cache_data(ttl=7200)
def obtener_partidos_historico_2anos(liga_code):
    """
    Obtiene el histórico de partidos de la temporada actual y las 2 temporadas previas.
    """
    anio_actual = datetime.datetime.now().year
    # En verano/otoño la temporada puede iniciarse el año anterior
    if datetime.datetime.now().month < 7:
        anio_base = anio_actual - 1
    else:
        anio_base = anio_actual

    seasons_to_fetch = [anio_base, anio_base - 1, anio_base - 2]
    
    todos_jugados = []
    partidos_programados = []

    for idx, season in enumerate(seasons_to_fetch):
        url = f"{BASE_URL}competitions/{liga_code}/matches?season={season}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                matches = res.json().get("matches", [])
                
                # De la temporada actual guardamos también los programados
                if idx == 0:
                    partidos_programados = [m for m in matches if m.get("status") in ["SCHEDULED", "TIMED", "LIVE"]]
                
                jugados = [m for m in matches if m.get("status") == "FINISHED"]
                todos_jugados.extend(jugados)
        except Exception:
            continue

    return todos_jugados, partidos_programados

def calcular_metricas_equipo(equipo_id, partidos_jugados, es_local=True, limite=20):
    """
    Calcula métricas ponderadas utilizando una muestra extendida de hasta 'limite' partidos (20 partidos).
    """
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

    def extraer_estadisticas(lista):
        if not lista:
            return 1.2, 1.2, 50.0, 0
        
        gf_tot, gc_tot, pts = 0, 0, 0
        peso_total = 0.0

        for idx, m in enumerate(lista):
            is_home = m["homeTeam"]["id"] == equipo_id
            score = m["score"]["fullTime"]
            gf = score["home"] if is_home else score["away"]
            gc = score["away"] if is_home else score["home"]
            if gf is None or gc is None:
                continue

            # Ponderación temporal: Partidos más recientes pesan un poco más
            peso = 1.0 / (1.0 + 0.05 * idx)
            peso_total += peso

            gf_tot += gf * peso
            gc_tot += gc * peso
            
            if gf > gc:
                pts += 3 * peso
            elif gf == gc:
                pts += 1 * peso

        if peso_total == 0:
            return 1.2, 1.2, 50.0, 0

        n = len(lista)
        return gf_tot / peso_total, gc_tot / peso_total, round((pts / (peso_total * 3)) * 100, 1), n

    atq_gen, def_gen, forma_gen, n_gen = extraer_estadisticas(ultimos_gen)
    atq_cond, def_cond, forma_cond, n_cond = extraer_estadisticas(ultimos_cond)

    atq_final = (atq_cond * 0.60) + (atq_gen * 0.40)
    def_final = (def_cond * 0.60) + (def_gen * 0.40)

    return {
        "atq_final": atq_final,
        "def_final": def_final,
        "atq_cond": atq_cond,
        "def_cond": def_cond,
        "forma_gen": forma_gen,
        "forma_cond": forma_cond,
        "partidos_gen": n_gen,
        "partidos_cond": n_cond
    }

# -----------------------------------------------------------------------------
# 3. MODELO DE POISSON CON AJUSTE DIXON-COLES
# -----------------------------------------------------------------------------
def poisson_pmf(lmbda, k):
    if lmbda <= 0:
        return 0.0
    return (lmbda ** k) * math.exp(-lmbda) / math.factorial(k)

def dixon_coles_tau(x, y, lmbda, mu, rho=-0.11):
    if x == 0 and y == 0:
        return 1.0 - (lmbda * mu * rho)
    elif x == 1 and y == 0:
        return 1.0 + (mu * rho)
    elif x == 0 and y == 1:
        return 1.0 + (lmbda * rho)
    elif x == 1 and y == 1:
        return 1.0 - rho
    else:
        return 1.0

def generar_modelo_completo(exp_local, exp_vis, usar_dixon=True, rho=-0.11):
    raw_matrix = []
    total_prob = 0.0

    for g_loc in range(6):
        fila = []
        for g_vis in range(6):
            p_raw = poisson_pmf(exp_local, g_loc) * poisson_pmf(exp_vis, g_vis)
            tau = dixon_coles_tau(g_loc, g_vis, exp_local, exp_vis, rho) if usar_dixon else 1.0
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

            if g_loc > g_vis:
                prob_1 += p
            elif g_loc == g_vis:
                prob_x += p
            else:
                prob_2 += p

            tot = g_loc + g_vis
            if tot > 1.5:
                over_15 += p
            if tot > 2.5:
                over_25 += p
            if tot > 3.5:
                over_35 += p

            if g_loc >= 1 and g_vis >= 1:
                btts_si += p

            lista_marcadores.append({
                "Marcador": f"{g_loc} - {g_vis}",
                "Probabilidad (%)": round(p, 2),
                "Goles Local": g_loc,
                "Goles Visitante": g_vis
            })
        matriz_norm.append(fila)

    df_matriz = pd.DataFrame(
        matriz_norm, 
        index=[f"{i} Gol(es) Loc" for i in range(6)], 
        columns=[f"{j} Gol(es) Vis" for j in range(6)]
    )
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
    if prob_pct <= 0:
        return 999.00
    return round(100.0 / prob_pct, 2)

# -----------------------------------------------------------------------------
# 4. INTERFAZ DE USUARIO PRINCIPAL
# -----------------------------------------------------------------------------
st.title("⚽ Predictor Profesional de Fútbol")
st.caption("Análisis cuantitativo con Histórico Extendido (2 Años), Distribución de Poisson y Ajuste Dixon-Coles.")

if "calculado" not in st.session_state:
    st.session_state.calculado = False

st.sidebar.header("⚙️ Configuración")
liga_sel = st.sidebar.selectbox("1. Competición", list(LIGAS.keys()), format_func=lambda x: LIGAS[x])

equipos = obtener_equipos_liga(liga_sel)

if not equipos:
    st.error("No se pudieron obtener datos de la competición seleccionada. Intenta de nuevo en unos segundos.")
    st.stop()

equipos_dict = {e["nombre"]: e for e in equipos}
nombres_equipos = list(equipos_dict.keys())

# Cargar partidos con histórico de 2 años
partidos_jugados, partidos_programados = obtener_partidos_historico_2anos(liga_sel)

# Selector de modo
modo_seleccion = st.sidebar.radio("2. Modo de Selección", ["📅 Próxima Jornada", "✏️ Personalizado"])

local_nom, visitante_nom = nombres_equipos[0], nombres_equipos[1]

if modo_seleccion == "📅 Próxima Jornada" and partidos_programados:
    opciones_partidos = []
    for m in partidos_programados[:15]:
        fecha_str = m.get("utcDate", "")[:10]
        loc = m["homeTeam"]["name"]
        vis = m["awayTeam"]["name"]
        opciones_partidos.append(f"{fecha_str} | {loc} vs {vis}")

    if opciones_partidos:
        partido_sel = st.sidebar.selectbox("Selecciona Partido Programado", opciones_partidos)
        partido_idx = opciones_partidos.index(partido_sel)
        m_sel = partidos_programados[partido_idx]
        local_nom = m_sel["homeTeam"]["name"]
        visitante_nom = m_sel["awayTeam"]["name"]
else:
    local_nom = st.sidebar.selectbox("Equipo Local", nombres_equipos, index=0)
    vis_opciones = [n for n in nombres_equipos if n != local_nom]
    visitante_nom = st.sidebar.selectbox("Equipo Visitante", vis_opciones, index=0)

muestra_partidos = st.sidebar.slider("Tamaño del Histórico (Últimos N Partidos)", 5, 25, 20)
factor_campo = st.sidebar.slider("Ventaja de Localia (+%)", 0, 30, 15) / 100.0 + 1.0
usar_dixon = st.sidebar.checkbox("Ajuste Dixon-Coles (Empates)", value=True)

def ejecutar_calculo():
    st.session_state.calculado = True

st.sidebar.button("🚀 Calcular Predicción", type="primary", on_click=ejecutar_calculo)

if st.session_state.calculado:
    eq_loc = equipos_dict.get(local_nom, {})
    eq_vis = equipos_dict.get(visitante_nom, {})

    id_local = eq_loc.get("id")
    id_vis = eq_vis.get("id")

    with st.spinner(f"Analizando histórico de 2 años ({len(partidos_jugados)} partidos procesados)..."):
        stats_loc = calcular_metricas_equipo(id_local, partidos_jugados, es_local=True, limite=muestra_partidos)
        stats_vis = calcular_metricas_equipo(id_vis, partidos_jugados, es_local=False, limite=muestra_partidos)

        media_liga = 1.35
        lambda_loc = max(0.2, (stats_loc["atq_final"] * stats_vis["def_final"] / media_liga) * factor_campo)
        lambda_vis = max(0.2, (stats_vis["atq_final"] * stats_loc["def_final"] / media_liga))

        df_matriz, df_marcadores, res_1x2, res_ou, res_btts = generar_modelo_completo(
            lambda_loc, lambda_vis, usar_dixon=usar_dixon
        )
        marcador_top = df_marcadores.iloc[0]

    # TARJETA DEL PARTIDO CON ESCUDOS
    st.markdown(f"""
        <div class="match-card">
            <div style="display: flex; justify-content: space-around; align-items: center; text-align: center;">
                <div style="flex: 1;">
                    <img src="{eq_loc.get('crest', '')}" class="crest-img"/><br>
                    <h2 style="margin: 5px 0;">{local_nom}</h2>
                    <span style="color: #cbd5e0;">(LOCAL)</span>
                </div>
                <div style="flex: 0.8;">
                    <h3 style="color: #a0aec0; margin: 0;">VS</h3>
                    <h1 style="color: #48bb78; font-size: 2.8rem; margin: 10px 0;">
                        {marcador_top['Goles Local']} - {marcador_top['Goles Visitante']}
                    </h1>
                    <span style="background: #2b6cb0; padding: 4px 12px; border-radius: 12px; font-weight: bold;">
                        Probabilidad: {marcador_top['Probabilidad (%)']:.1f}%
                    </span>
                </div>
                <div style="flex: 1;">
                    <img src="{eq_vis.get('crest', '')}" class="crest-img"/><br>
                    <h2 style="margin: 5px 0;">{visitante_nom}</h2>
                    <span style="color: #cbd5e0;">(VISITANTE)</span>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # SECCIONES EN PESTAÑAS
    tab1, tab2, tab3, tab4 = st.tabs([
        "🎯 Predicción & Marcadores", 
        "💰 Cuotas Justas & Valor (+EV)", 
        "⚔️ Historial Directo (H2H)", 
        "📊 Métricas Avanzadas"
    ])

    # PESTAÑA 1: PREDICCIÓN Y MARCADORES
    with tab1:
        st.subheader("🎲 Probabilidades Principales (1X2)")
        c1, c2, c3 = st.columns(3)
        c1.metric(f"Victoria {local_nom} (1)", f"{res_1x2['1']:.1f}%", f"Cuota Justa: @{calcular_cuota_justa(res_1x2['1']):.2f}")
        c2.metric("Empate (X)", f"{res_1x2['X']:.1f}%", f"Cuota Justa: @{calcular_cuota_justa(res_1x2['X']):.2f}")
        c3.metric(f"Victoria {visitante_nom} (2)", f"{res_1x2['2']:.1f}%", f"Cuota Justa: @{calcular_cuota_justa(res_1x2['2']):.2f}")

        st.divider()

        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("📊 Top 8 Marcadores Más Probables")
            df_top8 = df_marcadores.head(8).copy()
            df_top8["Cuota Justa"] = df_top8["Probabilidad (%)"].apply(lambda p: f"@{calcular_cuota_justa(p):.2f}")
            st.dataframe(
                df_top8[["Marcador", "Probabilidad (%)", "Cuota Justa"]], 
                use_container_width=True, 
                hide_index=True
            )
        with col_right:
            st.subheader("🔥 Rendimiento Esperado (Goles xG)")
            st.metric(f"xG Esperado {local_nom}", f"{lambda_loc:.2f} goles")
            st.metric(f"xG Esperado {visitante_nom}", f"{lambda_vis:.2f} goles")

        st.divider()
        st.subheader("🗺️ Matriz de Marcadores Exactos (%)")
        st.dataframe(df_matriz.style.highlight_max(axis=None, color="#2e7d32"), use_container_width=True)

    # PESTAÑA 2: CUOTAS JUSTAS Y APUESTAS DE VALOR (+EV)
    with tab2:
        st.subheader("💡 Guía de Cuotas Justas (Fair Odds)")
        st.info("💡 **Regla de Apuestas con Valor (+EV):** Compara la **Cuota Justa** calculada por la app con la cuota que paga tu casa de apuestas. Si la casa ofrece una cuota **MAYOR** que nuestra Cuota Justa, la apuesta tiene valor positivo.")

        st.markdown("### 1. Mercado Ganador del Partido (1X2)")
        df_1x2_val = pd.DataFrame([
            {
                "Mercado": f"Victoria {local_nom} (1)",
                "Probabilidad Modelo": f"{res_1x2['1']:.1f}%",
                "Cuota Justa del Modelo": f"@{calcular_cuota_justa(res_1x2['1']):.2f}",
                "Condición de Apuesta de Valor": f"Aposta si la casa te paga MÁS de @{calcular_cuota_justa(res_1x2['1']):.2f}"
            },
            {
                "Mercado": "Empate (X)",
                "Probabilidad Modelo": f"{res_1x2['X']:.1f}%",
                "Cuota Justa del Modelo": f"@{calcular_cuota_justa(res_1x2['X']):.2f}",
                "Condición de Apuesta de Valor": f"Aposta si la casa te paga MÁS de @{calcular_cuota_justa(res_1x2['X']):.2f}"
            },
            {
                "Mercado": f"Victoria {visitante_nom} (2)",
                "Probabilidad Modelo": f"{res_1x2['2']:.1f}%",
                "Cuota Justa del Modelo": f"@{calcular_cuota_justa(res_1x2['2']):.2f}",
                "Condición de Apuesta de Valor": f"Aposta si la casa te paga MÁS de @{calcular_cuota_justa(res_1x2['2']):.2f}"
            }
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

        st.markdown("### 🧮 Comprobador Rápido de Cuota Individual")
        col_in1, col_in2 = st.columns(2)
        cuota_ofrecida = col_in1.number_input("Cuota que te ofrece la Casa de Apuestas:", min_value=1.01, value=2.20, step=0.05, key="cuota_test")
        prob_analizada = col_in2.number_input("Probabilidad de tu modelo (%):", min_value=1.0, max_value=99.0, value=round(res_1x2['1'], 1), step=0.5, key="prob_test")

        ev = ((prob_analizada / 100.0) * cuota_ofrecida) - 1.0
        if ev > 0:
            st.success(f"✅ **¡Apuesta con Valor (+EV)!** Valor Esperado: **+{ev*100:.1f}%**. La cuota justa era @{100/prob_analizada:.2f} y te ofrecen @{cuota_ofrecida:.2f}.")
        else:
            st.error(f"❌ **Sin Valor (-EV).** Valor Esperado: **{ev*100:.1f}%**. Para esta probabilidad, necesitabas una cuota mínima de @{100/prob_analizada:.2f}.")

    # PESTAÑA 3: HISTORIAL DIRECTO (H2H)
    with tab3:
        st.subheader("⚔️ Enfrentamientos Directos Recientes (H2H de los últimos 2 años)")
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
            st.info("No se encontraron enfrentamientos directos en la muestra de los últimos 2 años.")

    # PESTAÑA 4: MÉTRICAS DETALLADAS
    with tab4:
        st.subheader("📋 Desglose de Forma con Ponderación Histórica Extendida")
        st.write(f"Muestra considerada: **últimos {muestra_partidos} partidos** extraídos del histórico de 2 años con decaimiento temporal en partidos antiguos.")

        col_st1, col_st2 = st.columns(2)
        with col_st1:
            st.markdown(f"### {local_nom} (Local)")
            st.write(f"• Goles Anotados en Casa (Promedio Ponderado): **{stats_loc['atq_cond']:.2f}**")
            st.write(f"• Goles Recibidos en Casa (Promedio Ponderado): **{stats_loc['def_cond']:.2f}**")
            st.write(f"• Forma como Local: **{stats_loc['forma_cond']:.1f}%**")
            st.write(f"• Muestra de Partidos Analizados: **{stats_loc['partidos_gen']}**")

        with col_st2:
            st.markdown(f"### {visitante_nom} (Visitante)")
            st.write(f"• Goles Anotados Fuera (Promedio Ponderado): **{stats_vis['atq_cond']:.2f}**")
            st.write(f"• Goles Recibidos Fuera (Promedio Ponderado): **{stats_vis['def_cond']:.2f}**")
            st.write(f"• Forma como Visitante: **{stats_vis['forma_cond']:.1f}%**")
            st.write(f"• Muestra de Partidos Analizados: **{stats_vis['partidos_gen']}**")
