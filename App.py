import math
import time
import datetime
import requests
import numpy as np
import pandas as pd
import streamlit as st

# -----------------------------------------------------------------------------
# 1. CONFIGURACIÓN E INTERFAZ
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Football Quant Pro | Advanced Analytics",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .stApp { background-color: #0b1319; color: #e2e8f0; }
    [data-testid="stSidebar"] { background-color: #111c24; border-right: 1px solid #1e2d3d; }
    .match-card {
        background: #16222f; border: 1px solid #233547;
        border-radius: 8px; padding: 10px 14px; margin-bottom: 8px;
    }
    .badge-v { background-color: #10B981; color: white; font-weight: bold; padding: 2px 7px; border-radius: 4px; font-size: 0.8rem; }
    .badge-e { background-color: #F59E0B; color: white; font-weight: bold; padding: 2px 7px; border-radius: 4px; font-size: 0.8rem; }
    .badge-d { background-color: #EF4444; color: white; font-weight: bold; padding: 2px 7px; border-radius: 4px; font-size: 0.8rem; }
    
    .power-badge {
        background: linear-gradient(135deg, #00e5ff 0%, #0077ff 100%);
        color: #0b1319; font-weight: 800; padding: 4px 10px; border-radius: 12px; font-size: 0.85rem;
    }

    .scoreboard {
        background: linear-gradient(135deg, #162636 0%, #0d1722 100%);
        border: 1px solid #00e5ff; border-radius: 12px;
        padding: 18px; text-align: center; margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. CONEXIÓN API & CARGA DE DATOS
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
    if not iso_str: return "-"
    try:
        dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except:
        return iso_str[:10]

@st.cache_data(ttl=900)
def obtener_partidos_hoy_ordenados():
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
# 3. MÓDULOS MATEMÁTICOS Y ESTADÍSTICOS
# -----------------------------------------------------------------------------
def obtener_ultimos_partidos(partidos_jugados, equipo_id, n=20, solo_condicion=None):
    rows = []
    for m in partidos_jugados:
        is_home = m["homeTeam"]["id"] == equipo_id
        is_away = m["awayTeam"]["id"] == equipo_id
        if not (is_home or is_away): continue
        
        if solo_condicion == "Local" and not is_home: continue
        if solo_condicion == "Visitante" and not is_away: continue

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
            "Puntos": pts, "GF": gf, "GC": gc
        })
        if len(rows) == n: break
    return pd.DataFrame(rows)

def calcular_power_rating(df_20):
    if df_20.empty: return 50.0
    ult_5 = df_20.head(5)
    ult_20 = df_20.head(20)
    ppm_5 = ult_5["Puntos"].mean() / 3.0
    ppm_20 = ult_20["Puntos"].mean() / 3.0
    diff_goles = (ult_20["GF"].sum() - ult_20["GC"].sum()) / len(ult_20)
    norm_diff_scaled = ((max(-1.0, min(1.0, diff_goles / 2.0))) + 1.0) / 2.0
    rating = (ppm_5 * 40) + (ppm_20 * 30) + (norm_diff_scaled * 30)
    return round(max(10.0, min(99.0, rating)), 1)

def generar_html_racha(df_partidos):
    if df_partidos.empty: return "Sin datos"
    html = ""
    for _, row in df_partidos.head(5).iterrows():
        est = row["Estado_Raw"]
        if est == "V": html += '<span class="badge-v">V</span> '
        elif est == "E": html += '<span class="badge-e">E</span> '
        else: html += '<span class="badge-d">D</span> '
    return html

def poisson_pmf(lmbda, k):
    return (lmbda ** k) * math.exp(-lmbda) / math.factorial(k) if lmbda > 0 else 0.0

def calcular_matrices_completas(exp_loc, exp_vis):
    marcadores = []
    ou_prob = {0.5: 0.0, 1.5: 0.0, 2.5: 0.0, 3.5: 0.0}
    btts_yes = 0.0
    prob_1, prob_x, prob_2 = 0.0, 0.0, 0.0
    
    for g_loc in range(7):
        for g_vis in range(7):
            p = poisson_pmf(exp_loc, g_loc) * poisson_pmf(exp_vis, g_vis)
            tot = g_loc + g_vis
            
            if g_loc > g_vis: prob_1 += p
            elif g_loc == g_vis: prob_x += p
            else: prob_2 += p

            if g_loc > 0 and g_vis > 0: btts_yes += p
            
            marcadores.append({"Marcador Exacto": f"{g_loc} - {g_vis}", "Probabilidad": p * 100, "Cuota Justa": 1/p if p > 0 else 99.0})
            
            for line in ou_prob.keys():
                if tot > line: ou_prob[line] += p
                    
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
        
    btts_no = 1.0 - btts_yes
    df_btts = pd.DataFrame([
        {"Mercado": "Ambos Anotan (Sí)", "Probabilidad": f"{btts_yes*100:.1f}%", "Cuota Justa": f"@{1/btts_yes:.2f}"},
        {"Mercado": "Ambos Anotan (No)", "Probabilidad": f"{btts_no*100:.1f}%", "Cuota Justa": f"@{1/btts_no:.2f}"}
    ])

    return prob_1, prob_x, prob_2, df_m.head(8), pd.DataFrame(ou_rows), df_btts

def ejecucion_monte_carlo(exp_loc, exp_vis, n_sims=10000):
    loc_goals = np.random.poisson(exp_loc, n_sims)
    vis_goals = np.random.poisson(exp_vis, n_sims)
    
    diffs = loc_goals - vis_goals
    goleada_loc = np.sum(diffs >= 3) / n_sims
    goleada_vis = np.sum(diffs <= -3) / n_sims
    
    loc_ht = np.random.poisson(exp_loc * 0.42, n_sims)
    vis_ht = np.random.poisson(exp_vis * 0.42, n_sims)
    ht_1 = np.sum(loc_ht > vis_ht) / n_sims
    ht_x = np.sum(loc_ht == vis_ht) / n_sims
    ht_2 = np.sum(loc_ht < vis_ht) / n_sims

    return goleada_loc, goleada_vis, ht_1, ht_x, ht_2

# -----------------------------------------------------------------------------
# 4. CONTROLES Y SELECCIÓN DE ENFRENTAMIENTO
# -----------------------------------------------------------------------------
st.title("⚽ Football Quant Analytics Pro")

st.sidebar.header("⚙️ Modo de Selección")
modo_sel = st.sidebar.radio("¿Qué deseas analizar?", ["📅 Partidos de Hoy", "🛠️ Selección Manual (Liga/Equipos)"])

partidos_hoy = obtener_partidos_hoy_ordenados()

local_nom, visitante_nom = None, None
eq_loc, eq_vis = None, None
liga_sel = "PD"

if modo_sel == "📅 Partidos de Hoy":
    if partidos_hoy:
        opciones_map = {
            f"[{m.get('competition',{}).get('code','-')}] {formatear_fecha(m.get('utcDate'))} | {m['homeTeam']['name']} vs {m['awayTeam']['name']}": m 
            for m in partidos_hoy
        }
        partido_sel_key = st.selectbox("👉 Selecciona el partido a analizar:", options=list(opciones_map.keys()), index=0)
        partido_obj = opciones_map[partido_sel_key]
        
        liga_sel = partido_obj.get("competition", {}).get("code", "PD")
        eq_loc = {"id": partido_obj["homeTeam"]["id"], "nombre": partido_obj["homeTeam"]["name"], "crest": partido_obj["homeTeam"].get("crest", "")}
        eq_vis = {"id": partido_obj["awayTeam"]["id"], "nombre": partido_obj["awayTeam"]["name"], "crest": partido_obj["awayTeam"].get("crest", "")}
        
        local_nom = eq_loc["nombre"]
        visitante_nom = eq_vis["nombre"]

        # Cartas visuales de partidos destacados
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
        st.warning("No se encontraron partidos programados para hoy en las ligas monitorizadas. Cambia a 'Selección Manual'.")
        modo_sel = "🛠️ Selección Manual (Liga/Equipos)"

if modo_sel.startswith("🛠️"):
    liga_sel = st.sidebar.selectbox("Competición", list(LIGAS.keys()), format_func=lambda x: LIGAS[x])
    equipos = obtener_equipos(liga_sel)
    if not equipos:
        st.error("Error al cargar equipos de la liga seleccionada.")
        st.stop()

    equipos_dict = {e["nombre"]: e for e in equipos}
    nombres_eq = list(equipos_dict.keys())

    col_s1, col_s2 = st.sidebar.columns(2)
    with col_s1:
        local_nom = st.selectbox("Equipo Local", nombres_eq, index=0)
    with col_s2:
        opciones_vis = [e for e in nombres_eq if e != local_nom]
        visitante_nom = st.selectbox("Equipo Visitante", opciones_vis, index=0)

    eq_loc = equipos_dict[local_nom]
    eq_vis = equipos_dict[visitante_nom]

filtro_condicion = st.sidebar.radio("Filtro de Historial", ["Global (Todos)", "Condición Específica (Casa/Fuera)"])

st.divider()

# -----------------------------------------------------------------------------
# 5. PROCESAMIENTO Y CÁLCULOS DINOAMICOS
# -----------------------------------------------------------------------------
jugados = obtener_historico_dos_anios(liga_sel)

cond_loc = "Local" if filtro_condicion.startswith("Condición") else None
cond_vis = "Visitante" if filtro_condicion.startswith("Condición") else None

df_loc_20 = obtener_ultimos_partidos(jugados, eq_loc["id"], n=20, solo_condicion=cond_loc)
df_vis_20 = obtener_ultimos_partidos(jugados, eq_vis["id"], n=20, solo_condicion=cond_vis)

pr_loc = calcular_power_rating(df_loc_20)
pr_vis = calcular_power_rating(df_vis_20)

html_racha_loc = generar_html_racha(df_loc_20)
html_racha_vis = generar_html_racha(df_vis_20)

# CÁLCULO DINÁMICO DE GOLES ESPERADOS (xG) BASADO EN PROMEDIOS
gf_loc_avg = df_loc_20["GF"].mean() if not df_loc_20.empty else 1.40
gc_loc_avg = df_loc_20["GC"].mean() if not df_loc_20.empty else 1.10
gf_vis_avg = df_vis_20["GF"].mean() if not df_vis_20.empty else 1.10
gc_vis_avg = df_vis_20["GC"].mean() if not df_vis_20.empty else 1.40

exp_local = max(0.2, (gf_loc_avg + gc_vis_avg) / 2.0)
exp_vis = max(0.2, (gf_vis_avg + gc_loc_avg) / 2.0)

prob_1, prob_x, prob_2, df_top_m, df_ou, df_btts = calcular_matrices_completas(exp_local, exp_vis)

# TABLERO DE MARCADOR
st.markdown(f"""
<div class="scoreboard">
    <div style="display:flex; justify-content:space-around; align-items:center;">
        <div style="flex:1;">
            {"<img src='" + eq_loc['crest'] + "' height='60'><br>" if eq_loc.get('crest') else ""}
            <h2 style="margin:4px 0; color:white;">{local_nom}</h2>
            <span class="power-badge">Power Rating: {pr_loc}</span><br><br>
            <div>{html_racha_loc}</div>
        </div>
        <div style="flex:1; background:rgba(0,0,0,0.3); padding:15px; border-radius:10px; border:1px solid #1e2d3d;">
            <span style="color:#00e5ff; font-weight:bold;">PROBABILIDADES 1X2</span>
            <h2 style="color:white; margin:8px 0;">{prob_1*100:.1f}% | {prob_x*100:.1f}% | {prob_2*100:.1f}%</h2>
            <small>xG Estimado: {exp_local:.2f} - {exp_vis:.2f}</small>
        </div>
        <div style="flex:1;">
            {"<img src='" + eq_vis['crest'] + "' height='60'><br>" if eq_vis.get('crest') else ""}
            <h2 style="margin:4px 0; color:white;">{visitante_nom}</h2>
            <span class="power-badge">Power Rating: {pr_vis}</span><br><br>
            <div>{html_racha_vis}</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 6. PESTAÑAS DE ANÁLISIS
# -----------------------------------------------------------------------------
tab_marcad, tab_btts_ou, tab_value, tab_montecarlo, tab_form = st.tabs([
    "🎯 Marcador & 1X2", 
    "⚽ Goles & BTTS",
    "🧮 Calculadora +EV & Kelly",
    "🎲 Monte Carlo (10k Sims)",
    "📈 Evolución & Historial"
])

with tab_marcad:
    st.subheader("🎯 Marcadores Exactos Más Probables")
    col1, col2 = st.columns(2)
    with col1:
        st.dataframe(df_top_m, use_container_width=True, hide_index=True)
    with col2:
        st.markdown("##### Cuotas Justas Estimadas")
        st.metric(f"Victoria {local_nom}", f"@{1/prob_1:.2f}", f"{prob_1*100:.1f}%")
        st.metric("Empate", f"@{1/prob_x:.2f}", f"{prob_x*100:.1f}%")
        st.metric(f"Victoria {visitante_nom}", f"@{1/prob_2:.2f}", f"{prob_2*100:.1f}%")

with tab_btts_ou:
    col_b, col_o = st.columns(2)
    with col_b:
        st.subheader("🤝 Ambos Equipos Anotan (BTTS)")
        st.dataframe(df_btts, use_container_width=True, hide_index=True)
    with col_o:
        st.subheader("⚽ Líneas Over / Under")
        st.dataframe(df_ou, use_container_width=True, hide_index=True)

with tab_value:
    st.subheader("🧮 Calculadora de Value Bets y Criterio de Kelly")
    st.write("Escribe la cuota ofrecida por tu casa de apuestas para evaluar si tiene Valor Positivo (+EV).")
    
    col_v1, col_v2, col_v3 = st.columns(3)
    
    with col_v1:
        sint_opcion = st.selectbox("Selecciona Selección", [f"Victoria {local_nom}", "Empate", f"Victoria {visitante_nom}"])
        cuota_bookie = st.number_input("Cuota de la Casa de Apuestas", min_value=1.01, value=2.10, step=0.05)
        bankroll = st.number_input("Tu Bankroll Total (€)", min_value=10.0, value=1000.0, step=50.0)
    
    prob_estimada = prob_1 if sint_opcion.startswith("Victoria " + local_nom) else (prob_x if sint_opcion == "Empate" else prob_2)
    
    ev = (prob_estimada * cuota_bookie) - 1.0
    b = cuota_bookie - 1.0
    f_kelly = max(0.0, (b * prob_estimada - (1.0 - prob_estimada)) / b)
    kelly_fraccional = f_kelly * 0.25 # Criterio Kelly Fraccional (1/4) por prudencia
    stake_sugerido = bankroll * kelly_fraccional

    with col_v2:
        st.metric("Probabilidad Estimada del Modelo", f"{prob_estimada*100:.1f}%")
        st.metric("Cuota Justa Calculada", f"@{1/prob_estimada:.2f}")
    
    with col_v3:
        if ev > 0:
            st.success(f"✅ ¡APUESTA CON VALOR POSITIVO! (+EV: {ev*100:.1f}%)")
            st.metric("Stake Recomendado (1/4 Kelly)", f"{stake_sugerido:.2f} €", f"{kelly_fraccional*100:.2f}% del bank")
        else:
            st.error(f"❌ SIN VALOR (+EV: {ev*100:.1f}%)")
            st.warning("La cuota de la casa de apuestas es menor a la cuota justa real. Se aconseja No Apostar.")

with tab_montecarlo:
    st.subheader("🎲 Simulación Estocástica de Monte Carlo (10,000 Partidos)")
    if st.button("🚀 Ejecutar 10,000 Simulaciones en Vivo"):
        gol_l, gol_v, ht1, htx, ht2 = ejecucion_monte_carlo(exp_local, exp_vis)
        
        mc1, mc2 = st.columns(2)
        with mc1:
            st.markdown("##### Probabilidades al Descanso (HT)")
            st.write(f"**Local lidera al descanso:** `{ht1*100:.1f}%`")
            st.write(f"**Empate al descanso:** `{htx*100:.1f}%`")
            st.write(f"**Visitante lidera al descanso:** `{ht2*100:.1f}%`")
        
        with mc2:
            st.markdown("##### Probabilidad de Goleada (Diferencia ≥ 3 Goles)")
            st.metric(f"Goleada de {local_nom}", f"{gol_l*100:.1f}%")
            st.metric(f"Goleada de {visitante_nom}", f"{gol_v*100:.1f}%")

with tab_form:
    st.subheader("📈 Evolución de Puntos y Registro")
    
    # GRÁFICO DE EVOLUCIÓN (Manejo de series de diferente longitud)
    if not df_loc_20.empty and not df_vis_20.empty:
        pts_loc_cum = pd.Series(df_loc_20.iloc[::-1]["Puntos"].cumsum().values)
        pts_vis_cum = pd.Series(df_vis_20.iloc[::-1]["Puntos"].cumsum().values)
        
        df_chart = pd.DataFrame({
            f"{local_nom} (Puntos Acum.)": pts_loc_cum,
            f"{visitante_nom} (Puntos Acum.)": pts_vis_cum
        }).ffill()

        st.markdown("##### Evolución de Puntos Acumulados en la Muestra")
        st.line_chart(df_chart)

    f_col1, f_col2 = st.columns(2)
    with f_col1:
        st.markdown(f"### 🏠 {local_nom}")
        st.markdown(f"**Power Rating:** `{pr_loc}/100` | **Racha:** {html_racha_loc}", unsafe_allow_html=True)
        st.dataframe(df_loc_20[["Fecha", "Condición", "Rival", "Resultado", "Estado_Raw"]].rename(columns={"Estado_Raw": "Res"}), use_container_width=True, hide_index=True, height=350)
    with f_col2:
        st.markdown(f"### ✈️ {visitante_nom}")
        st.markdown(f"**Power Rating:** `{pr_vis}/100` | **Racha:** {html_racha_vis}", unsafe_allow_html=True)
        st.dataframe(df_vis_20[["Fecha", "Condición", "Rival", "Resultado", "Estado_Raw"]].rename(columns={"Estado_Raw": "Res"}), use_container_width=True, hide_index=True, height=350)
