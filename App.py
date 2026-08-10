import math
import requests
import pandas as pd
import streamlit as st

# -----------------------------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Predictor Avanzado de Fútbol",
    page_icon="⚽",
    layout="wide"
)

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
    url = f"{BASE_URL}competitions/{liga_code}/teams"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            st.error(f"Error {res.status_code} al obtener equipos de la API.")
            return []
        teams_data = res.json().get("teams", [])
        equipos = [{"id": t["id"], "nombre": t["name"]} for t in teams_data]
        return sorted(equipos, key=lambda x: x["nombre"])
    except Exception as e:
        st.error(f"Error de conexión: {e}")
        return []

@st.cache_data(ttl=3600)
def obtener_partidos_finalizados_liga(liga_code):
    """
    Descarga TODOS los partidos jugados de la liga en una sola llamada.
    Evita saturar el límite de peticiones de la API (HTTP 429).
    """
    url = f"{BASE_URL}competitions/{liga_code}/matches?status=FINISHED"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            st.error(f"Error {res.status_code} de la API al obtener partidos. Respuesta: {res.text}")
            return []
        return res.json().get("matches", [])
    except Exception as e:
        st.error(f"Error al conectar con la API: {e}")
        return []

def calcular_metricas_equipo(equipo_id, todos_partidos, limite=6):
    """
    Filtra en memoria local los últimos N partidos de un equipo.
    """
    partidos_equipo = [
        m for m in todos_partidos 
        if m["homeTeam"]["id"] == equipo_id or m["awayTeam"]["id"] == equipo_id
    ]
    
    # Ordenar por fecha descendente (más recientes primero)
    partidos_equipo.sort(key=lambda x: x["utcDate"], reverse=True)
    ultimos = partidos_equipo[:limite]

    if not ultimos:
        return {"atq": 1.2, "def": 1.2, "forma_pct": 50.0, "partidos": 0}

    goles_favor, goles_contra, puntos = 0, 0, 0

    for m in ultimos:
        es_local = m["homeTeam"]["id"] == equipo_id
        score = m["score"]["fullTime"]
        gf = score["home"] if es_local else score["away"]
        gc = score["away"] if es_local else score["home"]

        if gf is None or gc is None:
            continue

        goles_favor += gf
        goles_contra += gc

        if gf > gc:
            puntos += 3
        elif gf == gc:
            puntos += 1

    total = len(ultimos)
    if total == 0:
        return {"atq": 1.2, "def": 1.2, "forma_pct": 50.0, "partidos": 0}

    return {
        "atq": goles_favor / total,
        "def": goles_contra / total,
        "forma_pct": round((puntos / (total * 3)) * 100, 1),
        "partidos": total
    }

# -----------------------------------------------------------------------------
# 3. MODELO DE POISSON
# -----------------------------------------------------------------------------
def poisson_pmf(lmbda, k):
    if lmbda <= 0:
        return 0.0
    return (lmbda ** k) * math.exp(-lmbda) / math.factorial(k)

def generar_matriz_poisson(exp_local, exp_vis):
    matriz = []
    lista_marcadores = []
    prob_1, prob_x, prob_2 = 0.0, 0.0, 0.0

    for g_loc in range(6):
        fila = []
        for g_vis in range(6):
            p = poisson_pmf(exp_local, g_loc) * poisson_pmf(exp_vis, g_vis) * 100
            fila.append(round(p, 2))
            
            if g_loc > g_vis:
                prob_1 += p
            elif g_loc == g_vis:
                prob_x += p
            else:
                prob_2 += p

            lista_marcadores.append({
                "Marcador": f"{g_loc} - {g_vis}",
                "Probabilidad (%)": round(p, 2),
                "Goles Local": g_loc,
                "Goles Visitante": g_vis
            })
        matriz.append(fila)

    df_matriz = pd.DataFrame(
        matriz, 
        index=[f"{i} Gol(es) Loc" for i in range(6)], 
        columns=[f"{j} Gol(es) Vis" for j in range(6)]
    )
    
    df_marcadores = pd.DataFrame(lista_marcadores).sort_values(by="Probabilidad (%)", ascending=False)
    
    return df_matriz, df_marcadores, (prob_1, prob_x, prob_2)

# -----------------------------------------------------------------------------
# 4. INTERFAZ DE USUARIO
# -----------------------------------------------------------------------------
st.title("⚽ Predictor Avanzado de Partidos")
st.write("Analiza datos reales de la liga para predecir el resultado exacto mediante distribución de Poisson.")

st.sidebar.header("⚙️ Configuración del Partido")
liga_sel = st.sidebar.selectbox("1. Selecciona Competición", list(LIGAS.keys()), format_func=lambda x: LIGAS[x])

equipos = obtener_equipos_liga(liga_sel)

if not equipos:
    st.error("No se pudieron cargar los equipos de esta liga.")
    st.stop()

nombres_equipos = [e["nombre"] for e in equipos]
id_map = {e["nombre"]: e["id"] for e in equipos}

local_nom = st.sidebar.selectbox("2. Equipo Local", nombres_equipos, index=0)
visitante_opciones = [n for n in nombres_equipos if n != local_nom]
visitante_nom = st.sidebar.selectbox("3. Equipo Visitante", visitante_opciones, index=0)

if st.sidebar.button("🚀 Calcular Predicción", type="primary"):
    id_local = id_map[local_nom]
    id_vis = id_map[visitante_nom]

    with st.spinner("Cargando historial de la liga y procesando datos reales..."):
        # Descarga los partidos finalizados de toda la liga (una sola llamada API)
        partidos_liga = obtener_partidos_finalizados_liga(liga_sel)

        if not partidos_liga:
            st.warning("No se encontraron partidos finalizados en la liga seleccionada o la API falló.")
            st.stop()

        # Procesa en memoria local el rendimiento de cada equipo
        stats_loc = calcular_metricas_equipo(id_local, partidos_liga)
        stats_vis = calcular_metricas_equipo(id_vis, partidos_liga)

        media_liga = 1.35
        lambda_loc = max(0.2, (stats_loc["atq"] * stats_vis["def"] / media_liga) * 1.15)
        lambda_vis = max(0.2, (stats_vis["atq"] * stats_loc["def"] / media_liga))

        df_matriz, df_marcadores, (p1, px, p2) = generar_matriz_poisson(lambda_loc, lambda_vis)
        marcador_top = df_marcadores.iloc[0]

    # ESTADO DE FORMA RECIENTE
    st.subheader("🔥 Estado de Forma Reciente")
    c1, c2 = st.columns(2)
    with c1:
        st.metric(f"Forma {local_nom}", f"{stats_loc['forma_pct']}%")
        st.progress(stats_loc["forma_pct"] / 100)
        st.caption(f"Basado en sus últimos **{stats_loc['partidos']}** partidos jugados.")
        st.caption(f"Ataque: **{stats_loc['atq']:.2f}** goles/partido | Defensa: **{stats_loc['def']:.2f}** encajados/partido")
    with c2:
        st.metric(f"Forma {visitante_nom}", f"{stats_vis['forma_pct']}%")
        st.progress(stats_vis["forma_pct"] / 100)
        st.caption(f"Basado en sus últimos **{stats_vis['partidos']}** partidos jugados.")
        st.caption(f"Ataque: **{stats_vis['atq']:.2f}** goles/partido | Defensa: **{stats_vis['def']:.2f}** encajados/partido")

    st.divider()

    # PREDICCIÓN PRINCIPAL
    st.subheader("🎯 Marcador Exacto Más Probable")
    st.success(f"### **{local_nom} {marcador_top['Goles Local']} - {marcador_top['Goles Visitante']} {visitante_nom}** (Probabilidad: **{marcador_top['Probabilidad (%)']:.2f}%**)")

    st.subheader("🎲 Probabilidades del Encuentro (1X2)")
    col_a, col_b, col_c = st.columns(3)
    col_a.metric(f"Victoria {local_nom} (1)", f"{p1:.1f}%")
    col_b.metric("Empate (X)", f"{px:.1f}%")
    col_c.metric(f"Victoria {visitante_nom} (2)", f"{p2:.1f}%")

    st.divider()

    # GRÁFICOS
    st.subheader("📊 Top 10 Marcadores con Mayor Probabilidad")
    top_10 = df_marcadores.head(10).set_index("Marcador")["Probabilidad (%)"]
    st.bar_chart(top_10)

    st.subheader("🗺️ Matriz Completa de Probabilidades (Mapa de Goles)")
    st.dataframe(df_matriz.style.highlight_max(axis=None, color="#90ee90"), use_container_width=True)
