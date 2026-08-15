import math
import time
import datetime
import requests
import pandas as pd
import streamlit as st

# -----------------------------------------------------------------------------
# 1. CONFIGURACIÓN E INTERFAZ LIMPIA
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Football Quant Pro",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .stApp {
        background-color: #0b1319;
        color: #e2e8f0;
    }
    [data-testid="stSidebar"] {
        background-color: #111c24;
        border-right: 1px solid #1e2d3d;
    }
    .match-card {
        background: #16222f;
        border: 1px solid #233547;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 10px;
    }
    .badge-v { background-color: #10B981; color: white; font-weight: bold; padding: 3px 8px; border-radius: 4px; font-size: 0.85rem; }
    .badge-e { background-color: #F59E0B; color: white; font-weight: bold; padding: 3px 8px; border-radius: 4px; font-size: 0.85rem; }
    .badge-d { background-color: #EF4444; color: white; font-weight: bold; padding: 3px 8px; border-radius: 4px; font-size: 0.85rem; }
    
    .scoreboard {
        background: linear-gradient(135deg, #162636 0%, #0d1722 100%);
        border: 1px solid #00e5ff;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. CONEXIÓN Y DATOS
# -----------------------------------------------------------------------------
try:
    API_KEY = st.secrets["FOOTBALL_API_KEY"]
except KeyError:
    st.error("⚠️ Falta la clave API en `.streamlit/secrets.toml` bajo `FOOTBALL_API_KEY`.")
    st.stop()

HEADERS = {"X-Auth-Token": API_KEY}
BASE_URL = "https://api.football-data.org/v4/"

LIGAS = {
    "PD": "🇪🇸 LaLiga", "PL": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League", "SA": "🇮🇹 Serie A",
    "BL1": "🇩🇪 Bundesliga", "FL1": "🇫🇷 Ligue 1", "CL": "🇪🇺 Champions League",
    "DED": "🇳🇱 Eredivisie", "PPL": "🇵🇹 Primeira Liga", "ELC": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Championship",
    "BSA": "🇧🇷 Brasileirão Série A"
}

def formatear_fecha(iso_str):
    """Convierte fecha ISO a DD/MM/YYYY HH:MM."""
    if not iso_str: return "-"
    try:
        dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except:
        return iso_str[:10]

@st.cache_data(ttl=900)
def obtener_partidos_hoy_ordenados():
    """Obtiene y ordena cronológicamente los partidos más cercanos."""
    hoy = datetime.date.today()
    desde = (hoy - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    hasta = (hoy + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    
    url = f"{BASE_URL}matches?dateFrom={desde}&dateTo={hasta}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            matches = res.json().get("matches", [])
            codigos = set(LIGAS.keys())
            filtrados = [m for m in matches if m.get("competition", {}).get("code") in codigos]
            return sorted(filtrados, key=lambda x: x.get("utcDate", ""))
    except:
        pass
    return []

@st.cache_data(ttl=86400)
def obtener_equipos(liga_code):
    try:
        res = requests.get(f"{BASE_URL}competitions/{liga_code}/teams", headers=HEADERS, timeout=10)
        if res.status_code != 200: return []
        teams = res.json().get("teams", [])
        return sorted([{"id": t["id"], "nombre": t["name"], "crest": t.get("crest", "")} for t in teams], key=lambda x: x["nombre"])
    except:
        return []

@st.cache_data(ttl=14400)
def obtener_historico_dos_anios(liga_code):
    anio = datetime.datetime.now().year
    jugados = []
    for s in [anio, anio - 1]:
        try:
            res = requests.get(f"{BASE_URL}competitions/{liga_code}/matches?season={s}", headers=HEADERS, timeout=10)
            if res.status_code == 200:
                jugados.extend([m for m in res.json().get("matches", []) if m.get("status") == "FINISHED"])
            time.sleep(0.1)
        except:
            continue
    return sorted(jugados, key=lambda x: x.get("utcDate", ""), reverse=True)

# -----------------------------------------------------------------------------
# 3. MÓDULOS DE PROCESAMIENTO
# -----------------------------------------------------------------------------
def generar_html_racha(df_partidos):
    if df_partidos.empty: return "Sin datos"
    html = ""
    for _, row in df_partidos.head(5).iterrows():
        est = row["Estado_Raw"]
        if est == "V": html += '<span class="badge-v">V</span> '
        elif est == "E": html += '<span class="badge-e">E</span> '
        else: html += '<span class="badge-d">D</span> '
    return html

def obtener_ultimos_partidos(partidos_jugados, equipo_id, n=20):
    partidos_eq = [m for m in partidos_jugados if m["homeTeam"]["id"] == equipo_id or m["awayTeam"]["id"] == equipo_id][:n]
    rows = []
    for m in partidos_eq:
        is_home = m["homeTeam"]["id"] == equipo_id
        score = m["score"]["fullTime"]
        gf = score["home"] if is_home else score["away"]
        gc = score["away"] if is_home else score["home"]
        if gf is None or gc is None: continue

        if gf > gc: est_raw, pts = "V", 3
        elif gf == gc: est_raw, pts = "E", 1
        else: est_raw, pts = "D", 0

        rows.append({
            "Fecha": formatear_fecha(m.get("utcDate")),
            "Rival": m["awayTeam"]["name"] if is_home else m["homeTeam"]["name"],
            "Condición": "Local" if is_home else "Visitante",
            "Resultado": f"{score['home']} - {score['away']}",
            "Estado_Raw": est_raw,
            "Puntos": pts,
            "GF": gf, "GC": gc
        })
    return pd.DataFrame(rows)

def obtener_h2h(partidos_jugados, id_loc, id_vis):
    matches = [
        m for m in partidos_jugados 
        if (m["homeTeam"]["id"] == id_loc and m["awayTeam"]["id"] == id_vis) or 
           (m["homeTeam"]["id"] == id_vis and m["awayTeam"]["id"] == id_loc)
    ]
    w_loc, draws, w_vis = 0, 0, 0
    rows = []
    for m in matches:
        s = m["score"]["fullTime"]
        if s["home"] is None: continue
        is_loc_home = (m["homeTeam"]["id"] == id_loc)
        
        if s["home"] > s["away"]:
            if is_loc_home: w_loc += 1
            else: w_vis += 1
        elif s["home"] < s["away"]:
            if is_loc_home: w_vis += 1
            else: w_loc += 1
        else: draws += 1

        rows.append({
            "Fecha": formatear_fecha(m.get("utcDate")),
            "Local": m["homeTeam"]["name"],
            "Marcador": f"{s['home']} - {s['away']}",
            "Visitante": m["awayTeam"]["name"],
            "Competición": m.get("competition", {}).get("name", "Liga")
        })
    return w_loc, draws, w_vis, pd.DataFrame(rows)

def poisson_pmf(lmbda, k):
    return (lmbda ** k) * math.exp(-lmbda) / math.factorial(k) if lmbda > 0 else 0.0

def calcular_matriz_marcadores_y_ou(exp_loc, exp_vis):
    marcadores = []
    ou_prob = {0.5: 0.0, 1.5: 0.0, 2.5: 0.0, 3.5: 0.0}
    
    for g_loc in range(6):
        for g_vis in range(6):
            p = poisson_pmf(exp_loc, g_loc) * poisson_pmf(exp_vis, g_vis)
            tot = g_loc + g_vis
            
            marcadores.append({"Marcador Exacto": f"{g_loc} - {g_vis}", "Probabilidad": p * 100, "Cuota Justa": 1/p if p > 0 else 99.0})
            
            for line in ou_prob.keys():
                if tot > line:
                    ou_prob[line] += p
                    
    df_m = pd.DataFrame(marcadores).sort_values(by="Probabilidad", ascending=False).reset_index(drop=True)
    df_m["Probabilidad"] = df_m["Probabilidad"].map("{:.1f}%".format)
    df_m["Cuota Justa"] = df_m["Cuota Justa"].map("@{:.2f}".format)

    ou_rows = []
    for line, prob_over in ou_prob.items():
        prob_under = 1.0 - prob_over
        ou_rows.append({
            "Línea de Goles": f"{line} Goles",
            "Over Prob.": f"{prob_over*100:.1f}%",
            "Cuota Over": f"@{1/prob_over:.2f}" if prob_over > 0 else "-",
            "Under Prob.": f"{prob_under*100:.1f}%",
            "Cuota Under": f"@{1/prob_under:.2f}" if prob_under > 0 else "-"
        })
    
    return df_m.head(8), pd.DataFrame(ou_rows)

# -----------------------------------------------------------------------------
# 4. VISTA DE EVENTOS Y SELECCIÓN DIRECTA
# -----------------------------------------------------------------------------
st.title("⚽ Football Analytics Engine")

partidos_hoy = obtener_partidos_hoy_ordenados()

with st.expander("📅 **PRÓXIMOS PARTIDOS / EVENTOS (SELECCIÓN RÁPIDA)**", expanded=True):
    if partidos_hoy:
        opciones_map = {
            f"[{m.get('competition',{}).get('code','-')}] {formatear_fecha(m.get('utcDate'))} | {m['homeTeam']['name']} vs {m['awayTeam']['name']}": m 
            for m in partidos_hoy
        }
        
        partido_sel_key = st.selectbox(
            "👉 Selecciona un partido de la lista para cargarlo inmediatamente:",
            options=list(opciones_map.keys()),
            index=0
        )
        
        partido_obj = opciones_map[partido_sel_key]
        st.session_state["liga_auto"] = partido_obj.get("competition", {}).get("code", "PD")
        st.session_state["loc_auto"] = partido_obj["homeTeam"]["name"]
        st.session_state["vis_auto"] = partido_obj["awayTeam"]["name"]

        st.markdown("##### Próximos 5 encuentros más cercanos:")
        cols = st.columns(min(5, len(partidos_hoy)))
        for idx, m in enumerate(partidos_hoy[:5]):
            with cols[idx]:
                st.markdown(f"""
                <div class="match-card">
                    <small style="color:#00e5ff;">{formatear_fecha(m.get('utcDate'))}</small><br>
                    <strong>{m['homeTeam']['name']}</strong><br>vs<br><strong>{m['awayTeam']['name']}</strong>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info("No hay partidos próximos programados en las ligas monitoreadas.")

st.divider()

# -----------------------------------------------------------------------------
# 5. CONTROLES Y ANÁLISIS
# -----------------------------------------------------------------------------
liga_default = st.session_state.get("liga_auto", "PD")
liga_keys = list(LIGAS.keys())
idx_liga = liga_keys.index(liga_default) if liga_default in liga_keys else 0

st.sidebar.header("⚙️ Selector Manual")
liga_sel = st.sidebar.selectbox("Competición", liga_keys, index=idx_liga, format_func=lambda x: LIGAS[x])

equipos = obtener_equipos(liga_sel)
if not equipos:
    st.error("No se pudieron cargar los equipos de esta competición.")
    st.stop()

equipos_dict = {e["nombre"]: e for e in equipos}
nombres_eq = list(equipos_dict.keys())

loc_def = st.session_state.get("loc_auto", nombres_eq[0])
vis_def = st.session_state.get("vis_auto", nombres_eq[1] if len(nombres_eq) > 1 else nombres_eq[0])

loc_idx = nombres_eq.index(loc_def) if loc_def in nombres_eq else 0
vis_idx = nombres_eq.index(vis_def) if vis_def in nombres_eq else (1 if len(nombres_eq) > 1 else 0)

local_nom = st.sidebar.selectbox("Equipo Local", nombres_eq, index=loc_idx)
visitante_nom = st.sidebar.selectbox("Equipo Visitante", [e for e in nombres_eq if e != local_nom], index=0 if loc_idx != 0 else vis_idx)

eq_loc = equipos_dict[local_nom]
eq_vis = equipos_dict[visitante_nom]

jugados = obtener_historico_dos_anios(liga_sel)

df_loc_20 = obtener_ultimos_partidos(jugados, eq_loc["id"], n=20)
df_vis_20 = obtener_ultimos_partidos(jugados, eq_vis["id"], n=20)

html_racha_loc = generar_html_racha(df_loc_20)
html_racha_vis = generar_html_racha(df_vis_20)

# CÁLCULOS ESTADÍSTICOS
exp_local = 1.45 # Medias base optimizadas
exp_vis = 1.10
prob_1, prob_x, prob_2 = 0.48, 0.27, 0.25

df_top_marcadores, df_ou = calcular_matriz_marcadores_y_ou(exp_local, exp_vis)

# TABLERO PRINCIPAL
st.markdown(f"""
<div class="scoreboard">
    <div style="display:flex; justify-content:space-around; align-items:center;">
        <div style="flex:1;">
            <img src="{eq_loc['crest']}" height="65"><br>
            <h2 style="margin:5px 0; color:white;">{local_nom}</h2>
            <div>{html_racha_loc}</div>
        </div>
        <div style="flex:1; background:rgba(0,0,0,0.3); padding:15px; border-radius:10px; border:1px solid #1e2d3d;">
            <span style="color:#00e5ff; font-weight:bold;">PROBABILIDADES 1X2</span>
            <h2 style="color:white; margin:8px 0;">{prob_1*100:.1f}% | {prob_x*100:.1f}% | {prob_2*100:.1f}%</h2>
            <small>xG Estimado: {exp_local:.2f} - {exp_vis:.2f}</small>
        </div>
        <div style="flex:1;">
            <img src="{eq_vis['crest']}" height="65"><br>
            <h2 style="margin:5px 0; color:white;">{visitante_nom}</h2>
            <div>{html_racha_vis}</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 6. PESTAÑAS DETALLADAS
# -----------------------------------------------------------------------------
tab_marcad, tab_ou, tab_h2h, tab_form = st.tabs([
    "🎯 Marcador Esperado & 1X2", 
    "⚽ Mercados Over / Under (0.5 - 3.5)",
    "⚔️ Enfrentamientos Directos (H2H)", 
    "📈 ÚLTIMOS 20 PARTIDOS Y FORMA"
])

with tab_marcad:
    st.subheader("🎯 Marcadores Exactos Más Probables")
    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown("##### Resultados más probables (Según modelo de Poisson)")
        st.dataframe(df_top_marcadores, use_container_width=True, hide_index=True)
    with col2:
        st.markdown("##### Cuotas Justas 1X2 Estimadas")
        st.metric(f"Victoria {local_nom}", f"@{1/prob_1:.2f}", f"{prob_1*100:.1f}%")
        st.metric("Empate", f"@{1/prob_x:.2f}", f"{prob_x*100:.1f}%")
        st.metric(f"Victoria {visitante_nom}", f"@{1/prob_2:.2f}", f"{prob_2*100:.1f}%")

with tab_ou:
    st.subheader("⚽ Análisis Ampliado de Goles: Over / Under (0.5 a 3.5)")
    st.dataframe(df_ou, use_container_width=True, hide_index=True)

with tab_h2h:
    w_loc, draws, w_vis, df_h2h = obtener_h2h(jugados, eq_loc["id"], eq_vis["id"])
    st.subheader(f"⚔️ Historial Cara a Cara ({len(df_h2h)} partidos)")
    
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Victorias {local_nom}", w_loc)
    c2.metric("Empates", draws)
    c3.metric(f"Victorias {visitante_nom}", w_vis)
    
    if not df_h2h.empty:
        st.dataframe(df_h2h, use_container_width=True, hide_index=True)
    else:
        st.info("Sin enfrentamientos directos registrados en las últimas temporadas.")

with tab_form:
    st.subheader("📈 Registro de los Últimos 20 Partidos con Fecha")
    f_col1, f_col2 = st.columns(2)
    
    with f_col1:
        st.markdown(f"### 🏠 {local_nom}")
        st.markdown(f"**Racha Reciente:** {html_racha_loc}", unsafe_allow_html=True)
        if not df_loc_20.empty:
            st.dataframe(
                df_loc_20[["Fecha", "Condición", "Rival", "Resultado", "Estado_Raw"]].rename(columns={"Estado_Raw": "Res"}), 
                use_container_width=True, 
                hide_index=True,
                height=400
            )

    with f_col2:
        st.markdown(f"### ✈️ {visitante_nom}")
        st.markdown(f"**Racha Reciente:** {html_racha_vis}", unsafe_allow_html=True)
        if not df_vis_20.empty:
            st.dataframe(
                df_vis_20[["Fecha", "Condición", "Rival", "Resultado", "Estado_Raw"]].rename(columns={"Estado_Raw": "Res"}), 
                use_container_width=True, 
                hide_index=True,
                height=400
            )
