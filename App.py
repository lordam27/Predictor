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
    .value-badge-positive {
        background-color: #28a745;
        color: white;
        padding: 4px 8px;
        border-radius: 6px;
        font-weight: bold;
    }
    .value-badge-negative {
        background-color: #dc3545;
        color: white;
        padding: 4px 8px;
        border-radius: 6px;
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
    "FL1": "🇫🇷 Ligue 1 (Francia)"
}

# -----------------------------------------------------------------------------
# 2. FUNCIONES DE API OPTIMIZADAS
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

@st.cache_data(ttl=3600)
def obtener_partidos_liga(liga_code):
    """
    Obtiene todos los partidos de la temporada (jugados y programados) en una única llamada API.
    """
    url_actual = f"{BASE_URL}competitions/{liga_code}/matches"
    try:
        res = requests.get(url_actual, headers=HEADERS, timeout=10)
        if res.status_code == 429:
            st.warning("⚠️ Límite de peticiones alcanzado en la API (10 req/min). Espera 1 minuto.")
            return [], []
        
        matches = []
        if res.status_code == 200:
            matches = res.json().get("matches", [])

        partidos_jugados = [m for m in matches if m.get("status") == "FINISHED"]
        partidos_programados = [m for m in matches if m.get("status") in ["SCHEDULED", "TIMED", "LIVE"]]

        # Fallback a temporada anterior si la actual está empezando
        if len(partidos_jugados) < 20:
            anio_previo = datetime.datetime.now().year - 1
            url_prev = f"{BASE_URL}competitions/{liga_code}/matches?status=FINISHED&season={anio_previo}"
            res_prev = requests.get(url_prev, headers=HEADERS, timeout=10)
            if res_prev.status_code == 200:
                prev_matches = res_prev.json().get("matches", [])
                partidos_jugados.extend(prev_matches)

        return partidos_jugados, partidos_programados
    except Exception as e:
        st.error(f"Error al conectar con la API: {e}")
        return [], []

def calcular_metricas_equipo(equipo_id, partidos_jugados, es_local=True, limite=8):
    """
    Calcula métricas ponderadas: 60% rendimiento específico (Casa/Fuera) + 40% forma general.
    """
    # 1. Rendimiento General
    partidos_general = [
        m for m in partidos_jugados
        if m["homeTeam"]["id"] == equipo_id or m["awayTeam"]["id"] == equipo_id
    ]
    partidos_general.sort(key=lambda x: x["utcDate"], reverse=True)
    ultimos_gen = partidos_general[:limite]

    # 2. Rendimiento en su Condición (Local o Visitante)
    partidos_condicion = [
        m for m in partidos_jugados
        if (m["homeTeam"]["id"] == equipo_id if es_local else m["awayTeam"]["id"] == equipo_id)
    ]
    partidos_condicion.sort(key=lambda x: x["utcDate"], reverse=True)
    ultimos_cond = partidos_condicion[:limite]

    def extraer_estadisticas(lista):
        gf_tot, gc_tot, pts = 0, 0, 0
        for m in lista:
            is_home = m["homeTeam"]["id"] == equipo_id
            score = m["score"]["fullTime"]
            gf = score["home"] if is_home else score["away"]
            gc = score["away"] if is_home else score["home"]
            if gf is None or gc is None:
                continue
            gf_tot += gf
            gc_tot += gc
            if gf > gc:
                pts += 3
            elif gf == gc:
                pts += 1
        n = len(lista)
        if n == 0:
            return 1.2, 1.2, 50.0, 0
        return gf_tot / n, gc_tot / n, round((pts / (n * 3)) * 100, 1), n

    atq_gen, def_gen, forma_gen, n_gen = extraer_estadisticas(ultimos_gen)
    atq_cond, def_cond, forma_cond, n_cond = extraer_estadisticas(ultimos_cond)

    # Ponderación
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
    """Ajuste de Dixon-Coles para corregir la frecuencia de empates bajos (0-0, 1-1, 1-0, 0-1)."""
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

# -----------------------------------------------------------------------------
# 4. INTERFAZ DE USUARIO PRINCIPAL
# -----------------------------------------------------------------------------
st.title("⚽ Predictor Profesional de Fútbol")
st.caption("Análisis cuantitativo con Distribución de Poisson, Ajuste Dixon-Coles y Métricas Local/Visitante.")

st.sidebar.header("⚙️ Configuración")
liga_sel = st.sidebar.selectbox("1. Competición", list(LIGAS.keys()), format_func=lambda x: LIGAS[x])

equipos = obtener_equipos_liga(liga_sel)

if not equipos:
    st.error("No se pudieron obtener datos de la liga seleccionada. Intenta de nuevo en 1 minuto.")
    st.stop()

equipos_dict = {e["nombre"]: e for e in equipos}
nombres_equipos = list(equipos_dict.keys())

# Cargar partidos
partidos_jugados, partidos_programados = obtener_partidos_liga(liga_sel)

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

factor_campo = st.sidebar.slider("Ventaja de Localia (+%)", 0, 30, 15) / 100.0 + 1.0
usar_dixon = st.sidebar.checkbox("Ajuste Dixon-Coles (Empates)", value=True)

if st.sidebar.button("🚀 Calcular Predicción", type="primary"):
    eq_loc = equipos_dict.get(local_nom, {})
    eq_vis = equipos_dict.get(visitante_nom, {})

    id_local = eq_loc["id"]
    id_vis = eq_vis["id"]

    with st.spinner("Procesando histórico de la liga y ejecutando modelo estadístico..."):
        stats_loc = calcular_metricas_equipo(id_local, partidos_jugados, es_local=True)
        stats_vis = calcular_metricas_equipo(id_vis, partidos_jugados, es_local=False)

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
                    <img src="{eq_loc.get('crest', '')}" class="crest-img" KeyError/><br>
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
                    <img src="{eq_vis.get('crest', '')}" class="crest-img" KeyError/><br>
                    <h2 style="margin: 5px 0;">{visitante_nom}</h2>
                    <span style="color: #cbd5e0;">(VISITANTE)</span>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # SECCIONES EN PESTAÑAS
    tab1, tab2, tab3, tab4 = st.tabs([
        "🎯 Predicción & Marcadores", 
        "💰 Apuestas de Valor (+EV)", 
        "⚔️ Historial Directo (H2H)", 
        "📊 Métricas Avanzadas"
    ])

    # PESTAÑA 1: PREDICCIÓN Y MARCADORES
    with tab1:
        st.subheader("🎲 Probabilidades Principales (1X2)")
        c1, c2, c3 = st.columns(3)
        c1.metric(f"Victoria {local_nom} (1)", f"{res_1x2['1']:.1f}%")
        c2.metric("Empate (X)", f"{res_1x2['X']:.1f}%")
        c3.metric(f"Victoria {visitante_nom} (2)", f"{res_2 = res_1x2['2']:.1f}%" if False else f"{res_1x2['2']:.1f}%")

        st.divider()

        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("📊 Top 8 Marcadores Más Probables")
            st.dataframe(
                df_marcadores.head(8)[["Marcador", "Probabilidad (%)"]], 
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

    # PESTAÑA 2: APUESTAS DE VALOR (+EV) Y OTROS MERCADOS
    with tab2:
        st.subheader("📈 Comparador de Cuotas y Búsqueda de Valor (+EV)")
        st.write("Introduce las cuotas de tu casa de apuestas para detectar si existe valor matemático.")

        q1, qX, q2 = st.columns(3)
        cuota_1 = q1.number_input(f"Cuota Victoria {local_nom} (1)", min_value=1.01, value=2.10, step=0.05)
        cuota_X = qX.number_input("Cuota Empate (X)", min_value=1.01, value=3.40, step=0.05)
        cuota_2 = q2.number_input(f"Cuota Victoria {visitante_nom} (2)", min_value=1.01, value=3.60, step=0.05)

        # Cálculo de Valor
        ev_1 = (res_1x2['1'] / 100.0 * cuota_1) - 1.0
        ev_X = (res_1x2['X'] / 100.0 * cuota_X) - 1.0
        ev_2 = (res_1x2['2'] / 100.0 * cuota_2) - 1.0

        tabla_ev = pd.DataFrame([
            {
                "Resultado": f"Victoria {local_nom} (1)",
                "Prob. Modelo": f"{res_1x2['1']:.1f}%",
                "Cuota Casa": cuota_1,
                "Prob. Implícita": f"{(1/cuota_1)*100:.1f}%",
                "Valor (EV)": f"{ev_1*100:+.1f}%",
                "¿Hay Valor?": "✅ SÍ (+EV)" if ev_1 > 0 else "❌ NO"
            },
            {
                "Resultado": "Empate (X)",
                "Prob. Modelo": f"{res_1x2['X']:.1f}%",
                "Cuota Casa": cuota_X,
                "Prob. Implícita": f"{(1/cuota_X)*100:.1f}%",
                "Valor (EV)": f"{ev_X*100:+.1f}%",
                "¿Hay Valor?": "✅ SÍ (+EV)" if ev_X > 0 else "❌ NO"
            },
            {
                "Resultado": f"Victoria {visitante_nom} (2)",
                "Prob. Modelo": f"{res_1x2['2']:.1f}%",
                "Cuota Casa": cuota_2,
                "Prob. Implícita": f"{(1/cuota_2)*100:.1f}%",
                "Valor (EV)": f"{ev_2*100:+.1f}%",
                "¿Hay Valor?": "✅ SÍ (+EV)" if ev_2 > 0 else "❌ NO"
            }
        ])
        st.dataframe(tabla_ev, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("⚽ Mercados de Goles Secundarios")
        m1, m2 = st.columns(2)
        with m1:
            st.markdown("#### Líneas Over / Under")
            st.write(f"• **Over 1.5 Goles:** {res_ou['Over 1.5']:.1f}% | **Under 1.5:** {res_ou['Under 1.5']:.1f}%")
            st.write(f"• **Over 2.5 Goles:** {res_ou['Over 2.5']:.1f}% | **Under 2.5:** {res_ou['Under 2.5']:.1f}%")
            st.write(f"• **Over 3.5 Goles:** {res_ou['Over 3.5']:.1f}% | **Under 3.5:** {res_ou['Under 3.5']:.1f}%")
        with m2:
            st.markdown("#### Ambos Equipos Anotan (BTTS)")
            st.write(f"• **Ambos Anotan - SÍ:** {res_btts['Sí']:.1f}%")
            st.write(f"• **Ambos Anotan - NO:** {res_btts['No']:.1f}%")

    # PESTAÑA 3: HISTORIAL DIRECTO (H2H)
    with tab3:
        st.subheader("⚔️ Enfrentamientos Directos Recientes (H2H)")
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
            st.info("No se encontraron enfrentamientos directos recientes grabados en la muestra actual.")

    # PESTAÑA 4: MÉTRICAS DETALLADAS
    with tab4:
        st.subheader("📋 Desglose de Forma Local vs Visitante")
        st.write("El modelo asigna un **60% de peso a la condición específica** (jugar en casa o fuera) y un **40% a la forma general**.")

        col_st1, col_st2 = st.columns(2)
        with col_st1:
            st.markdown(f"### {local_nom} (Local)")
            st.write(f"• Goles Anotados en Casa (Promedio): **{stats_loc['atq_cond']:.2f}**")
            st.write(f"• Goles Recibidos en Casa (Promedio): **{stats_loc['def_cond']:.2f}**")
            st.write(f"• Forma como Local: **{stats_loc['forma_cond']:.1f}%**")
            st.write(f"• Forma General: **{stats_loc['forma_gen']:.1f}%**")

        with col_st2:
            st.markdown(f"### {visitante_nom} (Visitante)")
            st.write(f"• Goles Anotados Fuera (Promedio): **{stats_vis['atq_cond']:.2f}**")
            st.write(f"• Goles Recibidos Fuera (Promedio): **{stats_vis['def_cond']:.2f}**")
            st.write(f"• Forma como Visitante: **{stats_vis['forma_cond']:.1f}%**")
            st.write(f"• Forma General: **{stats_vis['forma_gen']:.1f}%**")
