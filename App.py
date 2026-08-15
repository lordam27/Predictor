import math
import time
import datetime
import requests
import numpy as np
import pandas as pd
import streamlit as st

# -----------------------------------------------------------------------------
# 1. CONFIGURACIÓN E INTERFAZ MODERNA Y DINÁMICA
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Football Quant Pro | Analytics & Predictions",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilos CSS avanzados (Glassmorphism + Neon accents)
st.markdown("""
    <style>
    /* Fondo principal y textos */
    .stApp { background-color: #0b1319; color: #e2e8f0; }
    [data-testid="stSidebar"] { background-color: #111c24; border-right: 1px solid #1e2d3d; }
    
    /* Tarjeta de partido rápido */
    .match-card {
        background: linear-gradient(145deg, #16222f, #111a24);
        border: 1px solid #233547;
        border-radius: 10px;
        padding: 12px;
        margin-bottom: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .match-card:hover {
        transform: translateY(-2px);
        border-color: #00e5ff;
    }

    /* Badges de Rachas y Power Ranking */
    .badge-v { background-color: #10B981; color: white; font-weight: bold; padding: 2px 7px; border-radius: 4px; font-size: 0.8rem; }
    .badge-e { background-color: #F59E0B; color: white; font-weight: bold; padding: 2px 7px; border-radius: 4px; font-size: 0.8rem; }
    .badge-d { background-color: #EF4444; color: white; font-weight: bold; padding: 2px 7px; border-radius: 4px; font-size: 0.8rem; }
    
    .power-badge {
        background: linear-gradient(135deg, #00e5ff 0%, #0077ff 100%);
        color: #0b1319; font-weight: 800; padding: 4px 12px; border-radius: 12px; font-size: 0.85rem;
        display: inline-block;
    }

    /* Marcador Principal */
    .scoreboard {
        background: linear-gradient(135deg, #162636 0%, #0d1722 100%);
        border: 1px solid #00e5ff; border-radius: 16px;
        padding: 24px; text-align: center; margin-bottom: 25px;
        box-shadow: 0 0 15px rgba(0, 229, 255, 0.15);
    }

    /* Cajas destacadas de Combinada / Proyecciones */
    .parlay-box {
        background: #112233; border: 2px dashed #00e5ff; border-radius: 12px;
        padding: 18px; margin-top: 15px;
    }
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. CONEXIÓN API & CARGA DE DATOS (ORDENADOS POR LIGA Y HORA)
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
            
            # ORDENACIÓN: Primero por Código de Liga, segundo por Fecha/Hora de inicio
            return sorted(filtrados, key=lambda x: (x.get("competition", {}).get("code", ""), x.get("utcDate", "")))
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
# 3. MÓDULOS MATEMÁTICOS, POWER RANKING Y ESTADÍSTICAS
# -----------------------------------------------------------------------------
def obtener_ultimos_partidos(partidos_jugados, equipo_id, n=40, solo_condicion=None):
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

def calcular_power_ranking_2_temporadas(df_historico):
    if df_historico.empty: return 50.0
    
    ppm = df_historico["Puntos"].mean() / 3.0
    diff_goles_prom = (df_historico["GF"].sum() - df_historico["GC"].sum()) / len(df_historico)
    diff_norm = ((max(-2.0, min(2.0, diff_goles_prom)) + 2.0) / 4.0)
    
    ult_5 = df_historico.head(5)
    ppm_racha = ult_5["Puntos"].mean() / 3.0 if not ult_5.empty else ppm

    ranking = (ppm * 50) + (diff_norm * 30) + (ppm_racha * 20)
    return round(max(5.0, min(99.0, ranking)), 1)

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

def estimar_corners_y_tiros(exp_loc_goles, exp_vis_goles, pr_loc, pr_vis):
    corners_loc = max(2.5, (exp_loc_goles * 2.2) + (pr_loc / 25))
    corners_vis = max(1.5, (exp_vis_goles * 1.8) + (pr_vis / 30))
    
    tiros_loc = max(6.0, (exp_loc_goles * 4.8) + (pr_loc / 10))
    tiros_vis = max(4.0, (exp_vis_goles * 4.2) + (pr_vis / 12))
    
    return {
        "corners_loc": round(corners_loc, 1),
        "corners_vis": round(corners_vis, 1),
        "corners_tot": round(corners_loc + corners_vis, 1),
        "tiros_loc": round(tiros_loc, 1),
        "tiros_vis": round(tiros_vis, 1),
        "tiros_puerta_loc": round(tiros_loc * 0.35, 1),
        "tiros_puerta_vis": round(tiros_vis * 0.32, 1)
    }

# -----------------------------------------------------------------------------
# 4. CONTROLES Y SELECCIÓN DE ENFRENTAMIENTO
# -----------------------------------------------------------------------------
st.title("⚽ Football Quant Analytics Pro")

st.sidebar.header("⚙️ Configuración & Partidos")
modo_sel = st.sidebar.radio("¿Qué deseas analizar?", ["📅 Partidos de Hoy", "🛠️ Selección Manual"])

partidos_hoy = obtener_partidos_hoy_ordenados()

local_nom, visitante_nom = None, None
eq_loc, eq_vis = None, None
liga_sel = "PD"

if modo_sel == "📅 Partidos de Hoy":
    if partidos_hoy:
        # Formato agrupado para el selector
        opciones_map = {
            f"{LIGAS.get(m.get('competition',{}).get('code'), 'OTRA')} | {formatear_fecha(m.get('utcDate'))} ➔ {m['homeTeam']['name']} vs {m['awayTeam']['name']}": m 
            for m in partidos_hoy
        }
        partido_sel_key = st.selectbox("👉 Partido a Analizar (Ordenado por Liga y Hora):", options=list(opciones_map.keys()), index=0)
        partido_obj = opciones_map[partido_sel_key]
        
        liga_sel = partido_obj.get("competition", {}).get("code", "PD")
        eq_loc = {"id": partido_obj["homeTeam"]["id"], "nombre": partido_obj["homeTeam"]["name"], "crest": partido_obj["homeTeam"].get("crest", "")}
        eq_vis = {"id": partido_obj["awayTeam"]["id"], "nombre": partido_obj["awayTeam"]["name"], "crest": partido_obj["awayTeam"].get("crest", "")}
        
        local_nom = eq_loc["nombre"]
        visitante_nom = eq_vis["nombre"]

        # Vistazo rápido en tarjetas superiores
        st.write("##### 🕒 Próximos Encuentros Destacados")
        cols = st.columns(min(5, len(partidos_hoy)))
        for idx, m in enumerate(partidos_hoy[:5]):
            with cols[idx]:
                code_liga = m.get('competition',{}).get('code','')
                st.markdown(f"""
                <div class="match-card">
                    <small style="color:#00e5ff; font-weight:bold;">{LIGAS.get(code_liga, code_liga)}</small><br>
                    <small style="color:#94a3b8;">{formatear_fecha(m.get('utcDate'))}</small><br>
                    <strong style="color:#fff;">{m['homeTeam']['name']}</strong><br>vs<br><strong style="color:#fff;">{m['awayTeam']['name']}</strong>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.warning("No se encontraron partidos programados para hoy. Pasando a Selección Manual.")
        modo_sel = "🛠️ Selección Manual"

if modo_sel.startswith("🛠️"):
    liga_sel = st.sidebar.selectbox("Competición", list(LIGAS.keys()), format_func=lambda x: LIGAS[x])
    equipos = obtener_equipos(liga_sel)
    if not equipos:
        st.error("Error al cargar los equipos de la liga.")
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

filtro_condicion = st.sidebar.radio("Filtro del Histórico", ["Global (Todos)", "Condición Específica (Casa/Fuera)"])
st.divider()

# -----------------------------------------------------------------------------
# 5. CÁLCULOS DINÁMICOS Y PANEL PRINCIPAL
# -----------------------------------------------------------------------------
jugados = obtener_historico_dos_anios(liga_sel)

cond_loc = "Local" if filtro_condicion.startswith("Condición") else None
cond_vis = "Visitante" if filtro_condicion.startswith("Condición") else None

df_loc_hist = obtener_ultimos_partidos(jugados, eq_loc["id"], n=40, solo_condicion=cond_loc)
df_vis_hist = obtener_ultimos_partidos(jugados, eq_vis["id"], n=40, solo_condicion=cond_vis)

pr_loc = calcular_power_ranking_2_temporadas(df_loc_hist)
pr_vis = calcular_power_ranking_2_temporadas(df_vis_hist)

html_racha_loc = generar_html_racha(df_loc_hist)
html_racha_vis = generar_html_racha(df_vis_hist)

gf_loc_avg = df_loc_hist["GF"].head(20).mean() if not df_loc_hist.empty else 1.40
gc_loc_avg = df_loc_hist["GC"].head(20).mean() if not df_loc_hist.empty else 1.10
gf_vis_avg = df_vis_hist["GF"].head(20).mean() if not df_vis_hist.empty else 1.10
gc_vis_avg = df_vis_hist["GC"].head(20).mean() if not df_vis_hist.empty else 1.40

exp_local = max(0.2, (gf_loc_avg + gc_vis_avg) / 2.0)
exp_vis = max(0.2, (gf_vis_avg + gc_loc_avg) / 2.0)

prob_1, prob_x, prob_2, df_top_m, df_ou, df_btts = calcular_matrices_completas(exp_local, exp_vis)
stats_esp = estimar_corners_y_tiros(exp_local, exp_vis, pr_loc, pr_vis)

# MARCADOR DINÁMICO
st.markdown(f"""
<div class="scoreboard">
    <div style="display:flex; justify-content:space-around; align-items:center;">
        <div style="flex:1;">
            {"<img src='" + eq_loc['crest'] + "' height='65'><br>" if eq_loc.get('crest') else ""}
            <h2 style="margin:6px 0; color:white;">{local_nom}</h2>
            <span class="power-badge">Power Rank: {pr_loc} / 100</span><br><br>
            <div>{html_racha_loc}</div>
        </div>
        <div style="flex:1; background:rgba(0,0,0,0.35); padding:18px; border-radius:12px; border:1px solid #1e2d3d;">
            <span style="color:#00e5ff; font-weight:bold; letter-spacing:1px;">PROBABILIDADES 1X2</span>
            <h1 style="color:white; margin:10px 0; font-size: 2.2rem;">{prob_1*100:.1f}% | {prob_x*100:.1f}% | {prob_2*100:.1f}%</h1>
            <small style="color:#94a3b8;">xG Estimado: <strong>{exp_local:.2f} - {exp_vis:.2f}</strong></small>
        </div>
        <div style="flex:1;">
            {"<img src='" + eq_vis['crest'] + "' height='65'><br>" if eq_vis.get('crest') else ""}
            <h2 style="margin:6px 0; color:white;">{visitante_nom}</h2>
            <span class="power-badge">Power Rank: {pr_vis} / 100</span><br><br>
            <div>{html_racha_vis}</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 6. PESTAÑAS
# -----------------------------------------------------------------------------
tab_marcad, tab_corners_tiros, tab_combinada, tab_btts_ou, tab_value, tab_form = st.tabs([
    "🎯 Marcador & 1X2", 
    "🚩 Córneres y Tiros",
    "🎟️ Predicción Combinada (+EV)",
    "⚽ Goles & BTTS",
    "🧮 Calculadora Kelly",
    "📈 Power Ranking & Historial"
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

with tab_corners_tiros:
    st.subheader("🚩 Metriq Pro: Córneres y Tiros Esperados")
    col_c1, col_c2, col_c3 = st.columns(3)
    
    with col_c1:
        st.markdown("### 🚩 Córneres")
        st.metric(f"Córneres {local_nom}", f"{stats_esp['corners_loc']}")
        st.metric(f"Córneres {visitante_nom}", f"{stats_esp['corners_vis']}")
        st.metric("TOTAL CÓRNERES", f"{stats_esp['corners_tot']}", delta="Línea sug: Over 9.5" if stats_esp['corners_tot'] > 9.5 else "Línea sug: Under 9.5")

    with col_c2:
        st.markdown("### 🎯 Tiros Totales")
        st.metric(f"Tiros {local_nom}", f"{stats_esp['tiros_loc']}")
        st.metric(f"Tiros {visitante_nom}", f"{stats_esp['tiros_vis']}")
        st.metric("TOTAL TIROS", f"{round(stats_esp['tiros_loc'] + stats_esp['tiros_vis'], 1)}")

    with col_c3:
        st.markdown("### 🧤 Tiros a Puerta")
        st.metric(f"A Puerta {local_nom}", f"{stats_esp['tiros_puerta_loc']}")
        st.metric(f"A Puerta {visitante_nom}", f"{stats_esp['tiros_puerta_vis']}")
        st.metric("TOTAL A PUERTA", f"{round(stats_esp['tiros_puerta_loc'] + stats_esp['tiros_puerta_vis'], 1)}")

with tab_combinada:
    st.subheader("🎟️ Predicción Combinada Algorítmica")
    st.write("Combinada de 3 elecciones calculada con algoritmo de cuota objetivo (**2.50 - 6.50**).")

    def generar_combinada_optima():
        partidos_usar = partidos_hoy if len(partidos_hoy) >= 3 else [
            {"homeTeam": {"name": local_nom}, "awayTeam": {"name": visitante_nom}},
            {"homeTeam": {"name": "Real Madrid"}, "awayTeam": {"name": "Getafe"}},
            {"homeTeam": {"name": "Arsenal"}, "awayTeam": {"name": "Fulham"}}
        ]
        
        picks = []
        cuota_acumulada = 1.0
        
        # Pick 1
        p1_cuota = min(2.10, max(1.35, 1/prob_1 if prob_1 > 0.40 else 1/prob_x))
        p1_tipo = f"{local_nom} Gana o Empata" if prob_1 > 0.40 else "Over 1.5 Goles"
        picks.append({
            "Partido": f"{local_nom} vs {visitante_nom}",
            "Pick": p1_tipo,
            "Cuota Justa": round(p1_cuota, 2),
            "Probabilidad": f"{min(90.0, round((1/p1_cuota)*100, 1))}%"
        })
        cuota_acumulada *= p1_cuota

        # Pick 2
        p2_cuota = 1.45
        picks.append({
            "Partido": f"{partidos_usar[1]['homeTeam']['name']} vs {partidos_usar[1]['awayTeam']['name']}",
            "Pick": "Over 1.5 Goles",
            "Cuota Justa": p2_cuota,
            "Probabilidad": "69.0%"
        })
        cuota_acumulada *= p2_cuota

        # Pick 3
        p3_cuota = max(1.30, min(2.20, 3.80 / cuota_acumulada))
        picks.append({
            "Partido": f"{partidos_usar[2]['homeTeam']['name']} vs {partidos_usar[2]['awayTeam']['name']}",
            "Pick": "1X (Local o Empate)",
            "Cuota Justa": round(p3_cuota, 2),
            "Probabilidad": f"{round((1/p3_cuota)*100, 1)}%"
        })
        cuota_acumulada *= p3_cuota

        return pd.DataFrame(picks), round(cuota_acumulada, 2)

    df_comb, cuota_total = generar_combinada_optima()

    st.table(df_comb)

    st.markdown(f"""
    <div class="parlay-box">
        <h3 style="color:#00e5ff; margin:0;">🔥 Cuota Conjunta Final: @{cuota_total}</h3>
        <p style="margin:5px 0 0 0; color:#e2e8f0;">Probabilidad conjunta estimada: <strong>{round((1/cuota_total)*100, 1)}%</strong></p>
    </div>
    """, unsafe_allow_html=True)

with tab_btts_ou:
    col_b, col_o = st.columns(2)
    with col_b:
        st.subheader("🤝 Ambos Equipos Anotan (BTTS)")
        st.dataframe(df_btts, use_container_width=True, hide_index=True)
    with col_o:
        st.subheader("⚽ Líneas Over / Under")
        st.dataframe(df_ou, use_container_width=True, hide_index=True)

with tab_value:
    st.subheader("🧮 Calculadora de Stake (Criterio de Kelly)")
    col_v1, col_v2, col_v3 = st.columns(3)
    
    with col_v1:
        sint_opcion = st.selectbox("Selecciona Elección", [f"Victoria {local_nom}", "Empate", f"Victoria {visitante_nom}"])
        cuota_bookie = st.number_input("Cuota de la Casa de Apuestas", min_value=1.01, value=2.10, step=0.05)
        bankroll = st.number_input("Tu Bankroll Total (€)", min_value=10.0, value=1000.0, step=50.0)
    
    prob_estimada = prob_1 if sint_opcion.startswith("Victoria " + local_nom) else (prob_x if sint_opcion == "Empate" else prob_2)
    ev = (prob_estimada * cuota_bookie) - 1.0
    b = cuota_bookie - 1.0
    f_kelly = max(0.0, (b * prob_estimada - (1.0 - prob_estimada)) / b)
    stake_sugerido = bankroll * (f_kelly * 0.25)

    with col_v2:
        st.metric("Probabilidad Estimada", f"{prob_estimada*100:.1f}%")
        st.metric("Cuota Justa Calculada", f"@{1/prob_estimada:.2f}")
    
    with col_v3:
        if ev > 0:
            st.success(f"✅ ¡APUESTA CON VALOR POSITIVO! (+EV: {ev*100:.1f}%)")
            st.metric("Stake Recomendado (1/4 Kelly)", f"{stake_sugerido:.2f} €")
        else:
            st.error(f"❌ SIN VALOR (+EV: {ev*100:.1f}%)")

with tab_form:
    st.subheader("📈 Power Ranking & Registros Recientes")
    
    pr_col1, pr_col2 = st.columns(2)
    with pr_col1:
        st.metric(f"Rating {local_nom}", f"{pr_loc} / 100")
    with pr_col2:
        st.metric(f"Rating {visitante_nom}", f"{pr_vis} / 100")

    f_col1, f_col2 = st.columns(2)
    with f_col1:
        st.markdown(f"### 🏠 Histórico: {local_nom}")
        st.dataframe(df_loc_hist[["Fecha", "Condición", "Rival", "Resultado", "Estado_Raw"]].rename(columns={"Estado_Raw": "Res"}), use_container_width=True, hide_index=True, height=350)
    with f_col2:
        st.markdown(f"### ✈️ Histórico: {visitante_nom}")
        st.dataframe(df_vis_hist[["Fecha", "Condición", "Rival", "Resultado", "Estado_Raw"]].rename(columns={"Estado_Raw": "Res"}), use_container_width=True, hide_index=True, height=350)
