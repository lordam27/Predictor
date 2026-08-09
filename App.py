import math
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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

# Ligas disponibles en el plan gratuito de la API
LIGAS = {
    "PD": "🇪🇸 LaLiga (España)",
    "PL": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League (Inglaterra)",
    "SA": "🇮🇹 Serie A (Italia)",
    "BL1": "🇩🇪 Bundesliga (Alemania)",
    "FL1": "🇫🇷 Ligue 1 (Francia)"
}

# -----------------------------------------------------------------------------
# 2. FUNCIONES DE API CON CACHÉ
# -----------------------------------------------------------------------------
@st.cache_data(ttl=86400)
def obtener_equipos_liga(liga_code):
    """Obtiene la lista completa de equipos participantes en la liga seleccionada."""
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
    """Calcula rendimiento reciente: media de goles marcados/encajados y porcentaje de forma."""
    url = f"{BASE_URL}teams/{equipo_id}/matches?status=FINISHED&limit={limite}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return {"atq": 1.2, "def": 1.2, "forma_pct": 50.0, "partidos": 0}
        
        matches = res.json().get("matches", [])
        if not matches:
            return {"atq": 1.2, "def": 1.2, "forma_pct": 50.0, "partidos": 0}

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
            "forma_pct": round((puntos / (total * 3)) * 100, 1),
            "partidos": total
        }
    except Exception:
        return {"atq": 1.2, "def": 1.2, "forma_pct": 50.0, "partidos": 0}

# -----------------------------------------------------------------------------
# 3. MODELO DE POISSON
# -----------------------------------------------------------------------------
def poisson_pmf(lmbda, k):
    """Calcula la probabilidad de que ocurran k goles según Poisson."""
    if lmbda <= 0:
        return 0.0
    return (lmbda ** k) * math.exp(-lmbda) / math.factorial(k)

def generar_matriz_poisson(exp_local, exp_vis):
    """
    Construye la matriz completa de probabilidades para marcadores de 0-0 a 5-5.
    Retorna: DataFrame de matriz, lista de marcadores más probables y probabilidades 1X2.
    """
    matriz = []
    lista_marcadores = []
    prob_1, prob_x, prob_2 = 0.0, 0.0, 0.0

    for g_loc in range(6):
        fila = []
        for g_vis in range(6):
            p = poisson_pmf(exp_local, g_loc) * poisson_pmf(exp_vis, g_vis) * 100
            fila.append(p)
            
            # Acumulador 1X2
            if g_loc > g_vis:
                prob_1 += p
            elif g_loc == g_vis:
                prob_x += p
            else:
                prob_2 += p

            lista_marcadores.append({
                "Marcador": f"{g_loc} - {g_vis}",
                "Probabilidad": p,
                "Goles Local": g_loc,
                "Goles Visitante": g_vis
            })
        matriz.append(fila)

    df_matriz = pd.DataFrame(
        matriz, 
        index=[f"{i} Goles Loc" for i in range(6)], 
        columns=[f"{j} Goles Vis" for j in range(6)]
    )
    
    df_marcadores = pd.DataFrame(lista_marcadores).sort_values(by="Probabilidad", ascending=False)
    
    return df_matriz, df_marcadores, (prob_1, prob_x, prob_2)

# -----------------------------------------------------------------------------
# 4. INTERFAZ DE USUARIO
# -----------------------------------------------------------------------------
st.title("⚽ Predictor Avanzado de Partidos")
st.write("Selecciona cualquier liga y cruza dos equipos para analizar sus momentos de forma y la probabilidad detallada de cada marcador.")

# Sidebar: Selector de Liga y Equipos
st.sidebar.header("⚙️ Configuración del Partido")
liga_sel = st.sidebar.selectbox("1. Selecciona Competición", list(LIGAS.keys()), format_func=lambda x: LIGAS[x])

equipos = obtener_equipos_liga(liga_sel)

if not equipos:
    st.error("No se pudieron cargar los equipos de esta liga. Verifica tu conexión o el estado de la API Key.")
    st.stop()

nombres_equipos = [e["nombre"] for e in equipos]
id_map = {e["nombre"]: e["id"] for e in equipos}

local_nom = st.sidebar.selectbox("2. Equipo Local", nombres_equipos, index=0)
# Filtrar para evitar que elija el mismo equipo como visitante
visitante_opciones = [n for n in nombres_equipos if n != local_nom]
visitante_nom = st.sidebar.selectbox("3. Equipo Visitante", visitante_opciones, index=0)

if st.sidebar.button("🚀 Calcular Predicción", type="primary"):
    id_local = id_map[local_nom]
    id_vis = id_map[visitante_nom]

    with st.spinner("Consultando últimos partidos y procesando modelo estadístico..."):
        stats_loc = calcular_metricas_equipo(id_local)
        stats_vis = calcular_metricas_equipo(id_vis)

        # Estimación de Goles Esperados (Lambda)
        media_liga = 1.35
        lambda_loc = max(0.2, (stats_loc["atq"] * stats_vis["def"] / media_liga) * 1.15)
        lambda_vis = max(0.2, (stats_vis["atq"] * stats_loc["def"] / media_liga))

        df_matriz, df_marcadores, (p1, px, p2) = generar_matriz_poisson(lambda_loc, lambda_vis)
        marcador_top = df_marcadores.iloc[0]

    # --- SECCIÓN: ESTADO DE FORMA ---
    st.subheader("🔥 Estado de Forma Reciente (Últimos partidos)")
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

    # --- SECCIÓN: PREDICCIÓN PRINCIPAL Y 1X2 ---
    st.subheader("🎯 Marcador Exacto Más Probable")
    st.success(f"### **{local_nom} {marcador_top['Goles Local']} - {marcador_top['Goles Visitante']} {visitante_nom}** (Probabilidad: **{marcador_top['Probabilidad']:.2f}%**)")

    st.subheader("🎲 Probabilidad General del Partido (1X2)")
    col_a, col_b, col_c = st.columns(3)
    col_a.metric(f"Victoria {local_nom} (1)", f"{p1:.1f}%")
    col_b.metric("Empate (X)", f"{px:.1f}%")
    col_c.metric(f"Victoria {visitante_nom} (2)", f"{p2:.1f}%")

    st.divider()

    # --- SECCIÓN: GRÁFICOS INTERACTIVOS ---
    st.subheader("📊 Ranking de Marcadores Exactos Más Probables")
    
    # Gráfico de Barras con Top 10 Marcadores
    top_10 = df_marcadores.head(10)
    fig_barras = px.bar(
        top_10,
        x="Marcador",
        y="Probabilidad",
        text_auto=".2f",
        title="Top 10 Marcadores con Mayor Probabilidad (%)",
        labels={"Probabilidad": "Probabilidad (%)", "Marcador": "Marcador Exacto (Local - Visitante)"},
        color="Probabilidad",
        color_continuous_scale="Blues"
    )
    fig_barras.update_traces(texttemplate='%{y:.2f}%', textposition='outside')
    fig_barras.update_layout(xaxis_title="Marcador Exacto", yaxis_title="Probabilidad (%)", showlegend=False)
    st.plotly_chart(fig_barras, use_container_width=True)

    # Gráfico Heatmap (Mapa de Calor de Marcadores)
    st.subheader("🗺️ Mapa de Calor de Marcadores (Matriz de Goles)")
    st.caption("Eje X: Goles del equipo visitante | Eje Y: Goles del equipo local")
    
    fig_heatmap = go.Figure(data=go.Heatmap(
        z=df_matriz.values,
        x=[f"{j} Vis" for j in range(6)],
        y=[f"{i} Loc" for i in range(6)],
        colorscale='YlOrRd',
        hovertemplate='Goles Local: %{y}<br>Goles Visitante: %{x}<br>Probabilidad: %{z:.2f}%<extra></extra>'
    ))
    fig_heatmap.update_layout(
        title=f"Matriz de Probabilidades ({local_nom} vs {visitante_nom})",
        xaxis_title=f"Goles de {visitante_nom}",
        yaxis_title=f"Goles de {local_nom}"
    )
    st.plotly_chart(fig_heatmap, use_container_width=True)

    # --- SECCIÓN: TABLA DETALLADA CON NÚMEROS ---
    with st.expander("🔢 Ver lista completa con todas las probabilidades de marcadores"):
        df_mostrar = df_marcadores.copy()
        df_mostrar["Probabilidad"] = df_mostrar["Probabilidad"].map("{:.2f}%".format)
        st.dataframe(df_mostrar[["Marcador", "Probabilidad"]], use_container_width=True)
