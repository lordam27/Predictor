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
# 2. FUNCIONES DE API
# -----------------------------------------------------------------------------
@st.cache_data(ttl=86400)
def obtener_equipos_liga(liga_code):
    url = f"{BASE_URL}competitions/{liga_code}/teams"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return []
        teams_data = res.json().get("teams", [])
        equipos = [{"id": t["id"], "nombre": t["name"]} for t in teams_data]
        return sorted(equipos, key=lambda x: x["nombre"])
    except Exception:
        return []

@st.cache_data(ttl=3600)
def calcular_metricas_equipo(equipo_id, limite=6):
    url = f"{BASE_URL}teams/{equipo_id}/matches?status=FINISHED&limit={limite}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return {"atq": 1.2, "def": 1.2, "forma_pct": 50.0}
        
        matches = res.json().get("matches", [])
        if not matches:
            return {"atq": 1.2, "def": 1.2, "forma_pct": 50.0}

        goles_favor, goles_contra, puntos = 0, 0, 0

        for m in matches:
            es_local = m["homeTeam"]["id"] == equipo_id
            gf = m["score"]["fullTime"]["home"] if es_local else m["score"]["fullTime"]["away"]
            gc = m["score"]["fullTime"]["away"] if es_local else m["score"]["fullTime"]["home"]
            
            goles_favor += gf
            goles_contra += gc
            
            if gf > gc:
                puntos += 3
            elif gf == gc:
                puntos += 1

        total = len(matches)
        return {
            "atq": goles_favor / total,
            "def": goles_contra / total,
            "forma_pct": round((puntos / (total * 3)) * 100, 1)
        }
    except Exception:
        return {"atq": 1.2, "def": 1.2, "forma_pct": 50.0}

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
st.write("Selecciona cualquier liga y cruza dos equipos para analizar sus momentos de forma y la probabilidad de cada marcador.")

st.sidebar.header("⚙️ Configuración del Partido")
liga_sel = st.sidebar.selectbox("1. Selecciona Competición", list(LIGAS.keys()), format_func=lambda x: LIGAS[x])

equipos = obtener_equipos_liga(liga_sel)

if not equipos:
    st.error("No se pudieron cargar los equipos. Verifica la conexión o tu API Key.")
    st.stop()

nombres_equipos = [e["nombre"] for e in equipos]
id_map = {e["nombre"]: e["id"] for e in equipos}

local_nom = st.sidebar.selectbox("2. Equipo Local", nombres_equipos, index=0)
visitante_opciones = [n for n in nombres_equipos if n != local_nom]
visitante_nom = st.sidebar.selectbox("3. Equipo Visitante", visitante_opciones, index=0)

if st.sidebar.button("🚀 Calcular Predicción", type="primary"):
    id_local = id_map[local_nom]
    id_vis = id_map[visitante_nom]

    with st.spinner("Procesando modelo estadístico..."):
        stats_loc = calcular_metricas_equipo(id_local)
        stats_vis = calcular_metricas_equipo(id_vis)

        media_liga = 1.35
        lambda_loc = max(0.2, (stats_loc["atq"] * stats_vis["def"] / media_liga) * 1.15)
        lambda_vis = max(0.2, (stats_vis["atq"] * stats_loc["def"] / media_liga))

        df_matriz, df_marcadores, (p1, px, p2) = generar_matriz_poisson(lambda_loc, lambda_vis)
        marcador_top = df_marcadores.iloc[0]

    # ESTADO DE FORMA
    st.subheader("🔥 Estado de Forma Reciente")
    c1, c2 = st.columns(2)
    with c1:
        st.metric(f"Forma {local_nom}", f"{stats_loc['forma_pct']}%")
        st.progress(stats_loc["forma_pct"] / 100)
        st.caption(f"Ataque: **{stats_loc['atq']:.2f}** goles/partido | Defensa: **{stats_loc['def']:.2f}** encajados/partido")
    with c2:
        st.metric(f"Forma {visitante_nom}", f"{stats_vis['forma_pct']}%")
        st.progress(stats_vis["forma_pct"] / 100)
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

    # GRÁFICOS NATIVOS DE STREAMLIT (SIN LIBRERÍAS EXTERNAS)
    st.subheader("📊 Top 10 Marcadores con Mayor Probabilidad")
    top_10 = df_marcadores.head(10).set_index("Marcador")["Probabilidad (%)"]
    st.bar_chart(top_10)

    st.subheader("🗺️ Matriz Completa de Probabilidades (Mapa de Goles)")
    st.dataframe(df_matriz.style.highlight_max(axis=None, color="#90ee90"), use_container_width=True)
    
