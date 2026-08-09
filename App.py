import math
import requests
import streamlit as st

# Configuración de página de Streamlit
st.set_page_config(
    page_title="Predictor de Fútbol",
    page_icon="⚽",
    layout="wide"
)

# -----------------------------------------------------------------------------
# 1. AUTENTICACIÓN Y CONFIGURACIÓN DE LA API
# -----------------------------------------------------------------------------
# Obtiene la clave de forma segura desde los secretos de Streamlit
try:
    API_KEY = st.secrets["FOOTBALL_API_KEY"]
except KeyError:
    st.error("⚠️ No se encontró la API Key. Configura tu 'FOOTBALL_API_KEY' en los Secrets de Streamlit.")
    st.stop()

HEADERS = {"X-Auth-Token": API_KEY}
BASE_URL = "https://api.football-data.org/v4/"

# -----------------------------------------------------------------------------
# 2. FUNCIONES DE API CON CACHÉ
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def obtener_proximos_partidos(liga_code="PD"):
    """Recupera los próximos partidos programados."""
    url = f"{BASE_URL}competitions/{liga_code}/matches?status=SCHEDULED"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return []
        matches = res.json().get("matches", [])
        partidos = []
        for m in matches:
            partidos.append({
                "id": m["id"],
                "local_id": m["homeTeam"]["id"],
                "local_nombre": m["homeTeam"]["name"],
                "visitante_id": m["awayTeam"]["id"],
                "visitante_nombre": m["awayTeam"]["name"],
                "fecha": m["utcDate"][:10]
            })
        return partidos
    except Exception:
        return []

@st.cache_data(ttl=1800)
def calcular_metricas_equipo(equipo_id, limite=6):
    """Calcula goles a favor, en contra y forma reciente (% puntos)."""
    url = f"{BASE_URL}teams/{equipo_id}/matches?status=FINISHED&limit={limite}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return {"atq": 1.0, "def": 1.0, "forma_pct": 50.0}
        
        matches = res.json().get("matches", [])
        if not matches:
            return {"atq": 1.0, "def": 1.0, "forma_pct": 50.0}

        goles_favor = 0
        goles_contra = 0
        puntos = 0

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
        return {"atq": 1.0, "def": 1.0, "forma_pct": 50.0}

# -----------------------------------------------------------------------------
# 3. MODELO MATEMÁTICO (POISSON)
# -----------------------------------------------------------------------------
def poisson_pmf(lmbda, k):
    """Probabilidad de Poisson para 'k' goles."""
    if lmbda <= 0:
        return 0.0
    return (lmbda ** k) * math.exp(-lmbda) / math.factorial(k)

def calcular_matriz_poisson(exp_local, exp_vis):
    """Calcula el marcador exacto más probable y las opciones 1X2."""
    prob_1, prob_x, prob_2 = 0.0, 0.0, 0.0
    max_prob = 0.0
    marcador_probable = (0, 0)

    for g_loc in range(6):
        for g_vis in range(6):
            p = poisson_pmf(exp_local, g_loc) * poisson_pmf(exp_vis, g_vis)
            
            if g_loc > g_vis:
                prob_1 += p
            elif g_loc == g_vis:
                prob_x += p
            else:
                prob_2 += p
                
            if p > max_prob:
                max_prob = p
                marcador_probable = (g_loc, g_vis)

    return marcador_probable, max_prob * 100, (prob_1 * 100, prob_x * 100, prob_2 * 100)

# -----------------------------------------------------------------------------
# 4. INTERFAZ GRÁFICA (STREAMLIT)
# -----------------------------------------------------------------------------
st.title("⚽ Comparador y Predictor de Fútbol")
st.write("Analiza la forma reciente de los equipos y predice el resultado exacto mediante la **Distribución de Poisson**.")

# Menú lateral para elegir competición
ligas = {
    "PD": "LaLiga (España)",
    "PL": "Premier League (Inglaterra)",
    "SA": "Serie A (Italia)",
    "BL1": "Bundesliga (Alemania)",
    "FL1": "Ligue 1 (Francia)"
}
liga_sel = st.sidebar.selectbox("Selecciona Competición", list(ligas.keys()), format_func=lambda x: ligas[x])

partidos = obtener_proximos_partidos(liga_sel)

if not partidos:
    st.warning("No se encontraron partidos próximos o se ha excedido el límite de peticiones de la API.")
else:
    opciones = [f"{p['fecha']} | {p['local_nombre']} vs {p['visitante_nombre']}" for p in partidos]
    partido_idx = st.selectbox("Selecciona un encuentro:", range(len(opciones)), format_func=lambda i: opciones[i])
    partido = partidos[partido_idx]

    if st.button("📊 Comparar Forma y Predecir Resultado", type="primary"):
        with st.spinner("Consultando rendimiento reciente..."):
            stats_loc = calcular_metricas_equipo(partido["local_id"])
            stats_vis = calcular_metricas_equipo(partido["visitante_id"])

            # Cálculo de goles esperados (Ataque x Defensa rival con factor localía)
            media_liga = 1.35
            lambda_loc = max(0.2, (stats_loc["atq"] * stats_vis["def"] / media_liga) * 1.15)
            lambda_vis = max(0.2, (stats_vis["atq"] * stats_loc["def"] / media_liga))

            marcador, prob_marcador, (p1, px, p2) = calcular_matriz_poisson(lambda_loc, lambda_vis)

        # Visualización: Estado de Forma
        st.subheader("📈 Estado de Forma Reciente (Últimos 6 partidos)")
        col1, col2 = st.columns(2)
        with col1:
            st.metric(f"Forma {partido['local_nombre']}", f"{stats_loc['forma_pct']}%")
            st.caption(f"Promedio goles: **{stats_loc['atq']:.2f}** a favor | **{stats_loc['def']:.2f}** en contra")
        with col2:
            st.metric(f"Forma {partido['visitante_nombre']}", f"{stats_vis['forma_pct']}%")
            st.caption(f"Promedio goles: **{stats_vis['atq']:.2f}** a favor | **{stats_vis['def']:.2f}** en contra")

        st.divider()

        # Visualización: Predicción
        st.subheader("🎯 Marcador Exacto Predicho")
        st.success(f"### **{partido['local_nombre']} {marcador[0]} - {marcador[1]} {partido['visitante_nombre']}**")
        st.write(f"Confianza para este marcador exacto: **{prob_marcador:.1f}%**")

        st.subheader("🎲 Probabilidades globales del partido (1X2)")
        c_a, c_b, c_c = st.columns(3)
        c_a.metric("Victoria Local (1)", f"{p1:.1f}%")
        c_b.metric("Empate (X)", f"{px:.1f}%")
        c_c.metric("Victoria Visitante (2)", f"{p2:.1f}%")
