"""
Football Quant Pro | Analytics & Predictions
---------------------------------------------
Correcciones aplicadas respecto a la versión original:
  1. Manejo de errores explícito en las llamadas a la API (nada de `except: pass`).
  2. Cálculo de la matriz de marcadores vectorizado con numpy en vez de doble bucle for.
  3. Dataclass `Equipo` en vez de diccionarios sueltos, con tipado.
  4. Fracción de Kelly ajustable por el usuario en vez de fija (0.25 hardcodeado).
  5. Config (ligas, endpoints, colores) separada en constantes al principio del archivo.
  6. Estética renovada: paleta más viva, animaciones sutiles, tarjetas con más jerarquía visual.
"""

import math
import time
import datetime
import logging
from dataclasses import dataclass, field
from typing import Optional

import requests
import numpy as np
import pandas as pd
import streamlit as st

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("football_quant_pro")

# -----------------------------------------------------------------------------
# 0. CONFIG / CONSTANTES
# -----------------------------------------------------------------------------
BASE_URL = "https://api.football-data.org/v4/"
REQUEST_TIMEOUT = 10
KELLY_FRACTION_DEFAULT = 0.25

LIGAS = {
    "PD": "🇪🇸 LaLiga", "PL": "🏴 Premier League", "SA": "🇮🇹 Serie A",
    "BL1": "🇩🇪 Bundesliga", "FL1": "🇫🇷 Ligue 1", "CL": "🇪🇺 Champions League",
    "DED": "🇳🇱 Eredivisie", "PPL": "🇵🇹 Primeira Liga", "ELC": "🏴 Championship",
    "BSA": "🇧🇷 Brasileirão Série A"
}

OU_LINES = (0.5, 1.5, 2.5, 3.5)


@dataclass
class Equipo:
    id: int
    nombre: str
    crest: str = ""


# -----------------------------------------------------------------------------
# 1. INTERFAZ — ESTÉTICA RENOVADA
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Football Quant Pro | Analytics & Predictions",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=Inter:wght@400;500;600&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    h1, h2, h3 { font-family: 'Space Grotesk', sans-serif; letter-spacing: -0.5px; }

    /* Fondo con degradado sutil animado en vez de plano */
    .stApp {
        background: radial-gradient(circle at 15% 0%, #0f2027 0%, #0b1319 45%, #090f14 100%);
        color: #e6edf3;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #111c24 0%, #0c151c 100%);
        border-right: 1px solid #1e2d3d;
    }

    /* Tarjeta de partido con acento de color por liga y animación de entrada */
    .match-card {
        background: linear-gradient(145deg, #172433, #101923);
        border: 1px solid #22384a;
        border-left: 3px solid #00e5ff;
        border-radius: 12px;
        padding: 14px;
        margin-bottom: 10px;
        box-shadow: 0 4px 10px rgba(0,0,0,0.35);
        transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
        animation: fadeInUp 0.4s ease both;
    }
    .match-card:hover {
        transform: translateY(-4px) scale(1.01);
        border-color: #7c3aed;
        box-shadow: 0 10px 20px rgba(0, 229, 255, 0.12);
    }
    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(8px); }
        to { opacity: 1; transform: translateY(0); }
    }

    /* Badges de racha con mas contraste y borde luminoso */
    .badge-v { background: linear-gradient(135deg,#10B981,#059669); color:white; font-weight:700; padding:2px 8px; border-radius:6px; font-size:0.78rem; box-shadow:0 0 8px rgba(16,185,129,0.35); }
    .badge-e { background: linear-gradient(135deg,#F59E0B,#D97706); color:white; font-weight:700; padding:2px 8px; border-radius:6px; font-size:0.78rem; box-shadow:0 0 8px rgba(245,158,11,0.35); }
    .badge-d { background: linear-gradient(135deg,#EF4444,#B91C1C); color:white; font-weight:700; padding:2px 8px; border-radius:6px; font-size:0.78rem; box-shadow:0 0 8px rgba(239,68,68,0.35); }

    .power-badge {
        background: linear-gradient(135deg, #00e5ff 0%, #7c3aed 100%);
        color: #0b1319; font-weight: 800; padding: 5px 14px; border-radius: 14px; font-size: 0.85rem;
        display: inline-block;
        box-shadow: 0 4px 12px rgba(124, 58, 237, 0.35);
    }

    /* Marcador principal con degradado dinámico + resplandor */
    .scoreboard {
        background: linear-gradient(135deg, #16263a 0%, #0d1722 60%, #14121f 100%);
        border: 1px solid #2a3f52;
        border-radius: 20px;
        padding: 28px; text-align: center; margin-bottom: 25px;
        box-shadow: 0 0 25px rgba(0, 229, 255, 0.1), inset 0 0 40px rgba(124,58,237,0.06);
    }

    .parlay-box {
        background: linear-gradient(145deg, #14202e, #0f1720);
        border: 2px dashed #00e5ff; border-radius: 14px;
        padding: 20px; margin-top: 15px;
    }

    /* Métricas nativas de Streamlit con un poco más de aire y contraste */
    [data-testid="stMetricValue"] { font-family: 'Space Grotesk', sans-serif; }
    </style>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# 2. CONEXIÓN API & CARGA DE DATOS (con manejo de errores real)
# -----------------------------------------------------------------------------
try:
    API_KEY = st.secrets["FOOTBALL_API_KEY"]
except (KeyError, FileNotFoundError):
    st.error("⚠️ Falta la clave API en `.streamlit/secrets.toml` bajo `FOOTBALL_API_KEY`.")
    st.stop()

HEADERS = {"X-Auth-Token": API_KEY}


def _get(url: str) -> Optional[dict]:
    """Wrapper único para llamadas GET con manejo de errores explícito y feedback al usuario."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.Timeout:
        st.warning(f"⏱️ Tiempo de espera agotado al consultar la API ({url}).")
        logger.warning("Timeout en %s", url)
        return None
    except requests.exceptions.RequestException as exc:
        st.warning(f"🔌 Error de conexión con la API: {exc}")
        logger.error("RequestException en %s: %s", url, exc)
        return None

    if res.status_code == 429:
        st.warning("🚦 Límite de peticiones a la API alcanzado (plan gratuito). Intenta de nuevo en unos minutos.")
        return None
    if res.status_code != 200:
        st.warning(f"⚠️ La API respondió con estado {res.status_code} para {url}.")
        logger.warning("Status %s en %s", res.status_code, url)
        return None

    try:
        return res.json()
    except ValueError:
        st.warning("⚠️ Respuesta de la API no es JSON válido.")
        return None


def formatear_fecha(iso_str: Optional[str]) -> str:
    if not iso_str:
        return "-"
    try:
        dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso_str[:10]


@st.cache_data(ttl=900)
def obtener_partidos_hoy_ordenados() -> list:
    hoy = datetime.date.today()
    desde = (hoy - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    hasta = (hoy + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    data = _get(f"{BASE_URL}matches?dateFrom={desde}&dateTo={hasta}")
    if not data:
        return []
    matches = data.get("matches", [])
    codigos = set(LIGAS.keys())
    filtrados = [m for m in matches if m.get("competition", {}).get("code") in codigos]
    return sorted(filtrados, key=lambda x: (x.get("competition", {}).get("code", ""), x.get("utcDate", "")))


@st.cache_data(ttl=86400)
def obtener_equipos(liga_code: str) -> list:
    data = _get(f"{BASE_URL}competitions/{liga_code}/teams")
    if not data:
        return []
    teams = data.get("teams", [])
    equipos = [Equipo(id=t["id"], nombre=t["name"], crest=t.get("crest", "")) for t in teams]
    return sorted(equipos, key=lambda e: e.nombre)


@st.cache_data(ttl=14400)
def obtener_historico_dos_anios(liga_code: str) -> list:
    anio = datetime.datetime.now().year
    jugados = []
    for s in (anio, anio - 1):
        data = _get(f"{BASE_URL}competitions/{liga_code}/matches?season={s}")
        if data:
            jugados.extend([m for m in data.get("matches", []) if m.get("status") == "FINISHED"])
        time.sleep(0.1)
    return sorted(jugados, key=lambda x: x.get("utcDate", ""), reverse=True)


# -----------------------------------------------------------------------------
# 3. MÓDULOS MATEMÁTICOS, POWER RANKING Y ESTADÍSTICAS
# -----------------------------------------------------------------------------
def obtener_ultimos_partidos(partidos_jugados, equipo_id, n=40, solo_condicion=None) -> pd.DataFrame:
    rows = []
    for m in partidos_jugados:
        is_home = m["homeTeam"]["id"] == equipo_id
        is_away = m["awayTeam"]["id"] == equipo_id
        if not (is_home or is_away):
            continue
        if solo_condicion == "Local" and not is_home:
            continue
        if solo_condicion == "Visitante" and not is_away:
            continue

        score = m["score"]["fullTime"]
        gf = score["home"] if is_home else score["away"]
        gc = score["away"] if is_home else score["home"]
        if gf is None or gc is None:
            continue

        if gf > gc:
            est_raw, pts = "V", 3
        elif gf == gc:
            est_raw, pts = "E", 1
        else:
            est_raw, pts = "D", 0

        rows.append({
            "Fecha": formatear_fecha(m.get("utcDate")),
            "Rival": m["awayTeam"]["name"] if is_home else m["homeTeam"]["name"],
            "Condición": "Local" if is_home else "Visitante",
            "Resultado": f"{score['home']} - {score['away']}",
            "Estado_Raw": est_raw,
            "Puntos": pts, "GF": gf, "GC": gc
        })
        if len(rows) == n:
            break
    return pd.DataFrame(rows)


def calcular_power_ranking_2_temporadas(df_historico: pd.DataFrame) -> float:
    if df_historico.empty:
        return 50.0
    ppm = df_historico["Puntos"].mean() / 3.0
    diff_goles_prom = (df_historico["GF"].sum() - df_historico["GC"].sum()) / len(df_historico)
    diff_norm = (max(-2.0, min(2.0, diff_goles_prom)) + 2.0) / 4.0
    ult_5 = df_historico.head(5)
    ppm_racha = ult_5["Puntos"].mean() / 3.0 if not ult_5.empty else ppm
    ranking = (ppm * 50) + (diff_norm * 30) + (ppm_racha * 20)
    return round(max(5.0, min(99.0, ranking)), 1)


def generar_html_racha(df_partidos: pd.DataFrame) -> str:
    if df_partidos.empty:
        return "Sin datos"
    badge_map = {"V": "badge-v", "E": "badge-e", "D": "badge-d"}
    return " ".join(
        f'<span class="{badge_map[row["Estado_Raw"]]}">{row["Estado_Raw"]}</span>'
        for _, row in df_partidos.head(5).iterrows()
    )


def calcular_matrices_completas(exp_loc: float, exp_vis: float, max_goles: int = 7):
    """Versión vectorizada: construye la matriz de probabilidades Poisson(local) x Poisson(vis)
    de una sola vez con numpy en vez de un doble bucle con math.factorial en cada paso."""
    goles = np.arange(max_goles)
    # Vector de probabilidades Poisson para cada equipo
    p_loc = np.exp(-exp_loc) * (exp_loc ** goles) / np.array([math.factorial(int(k)) for k in goles])
    p_vis = np.exp(-exp_vis) * (exp_vis ** goles) / np.array([math.factorial(int(k)) for k in goles])

    matriz = np.outer(p_loc, p_vis)  # matriz[g_loc, g_vis]

    prob_1 = np.tril(matriz, k=-1).sum()   # g_loc > g_vis
    prob_x = np.trace(matriz)              # g_loc == g_vis
    prob_2 = np.triu(matriz, k=1).sum()    # g_loc < g_vis

    idx_loc, idx_vis = np.meshgrid(goles, goles, indexing="ij")
    btts_yes = matriz[(idx_loc > 0) & (idx_vis > 0)].sum()

    marcadores = pd.DataFrame({
        "Marcador Exacto": [f"{g_loc} - {g_vis}" for g_loc in goles for g_vis in goles],
        "Probabilidad": matriz.flatten(),
    })
    marcadores["Cuota Justa"] = marcadores["Probabilidad"].apply(lambda p: 1 / p if p > 0 else 99.0)
    marcadores = marcadores.sort_values("Probabilidad", ascending=False).reset_index(drop=True)
    df_top = marcadores.head(8).copy()
    df_top["Probabilidad"] = df_top["Probabilidad"].map("{:.1%}".format)
    df_top["Cuota Justa"] = df_top["Cuota Justa"].map("@{:.2f}".format)

    total_goles = idx_loc + idx_vis
    ou_rows = []
    for line in OU_LINES:
        prob_over = matriz[total_goles > line].sum()
        prob_under = 1.0 - prob_over
        ou_rows.append({
            "Línea de Goles": f"{line} Goles",
            "Over Prob.": f"{prob_over:.1%}",
            "Cuota Over": f"@{1/prob_over:.2f}" if prob_over > 0 else "-",
            "Under Prob.": f"{prob_under:.1%}",
            "Cuota Under": f"@{1/prob_under:.2f}" if prob_under > 0 else "-"
        })

    btts_no = 1.0 - btts_yes
    df_btts = pd.DataFrame([
        {"Mercado": "Ambos Anotan (Sí)", "Probabilidad": f"{btts_yes:.1%}", "Cuota Justa": f"@{1/btts_yes:.2f}"},
        {"Mercado": "Ambos Anotan (No)", "Probabilidad": f"{btts_no:.1%}", "Cuota Justa": f"@{1/btts_no:.2f}"}
    ])

    return float(prob_1), float(prob_x), float(prob_2), df_top, pd.DataFrame(ou_rows), df_btts


def estimar_corners_y_tiros(exp_loc_goles, exp_vis_goles, pr_loc, pr_vis) -> dict:
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
eq_loc: Optional[Equipo] = None
eq_vis: Optional[Equipo] = None
liga_sel = "PD"

if modo_sel == "📅 Partidos de Hoy":
    if partidos_hoy:
        opciones_map = {
            f"{LIGAS.get(m.get('competition',{}).get('code'), 'OTRA')} | {formatear_fecha(m.get('utcDate'))} ➔ {m['homeTeam']['name']} vs {m['awayTeam']['name']}": m
            for m in partidos_hoy
        }
        partido_sel_key = st.selectbox("👉 Partido a Analizar (Ordenado por Liga y Hora):", options=list(opciones_map.keys()), index=0)
        partido_obj = opciones_map[partido_sel_key]

        liga_sel = partido_obj.get("competition", {}).get("code", "PD")
        eq_loc = Equipo(id=partido_obj["homeTeam"]["id"], nombre=partido_obj["homeTeam"]["name"], crest=partido_obj["homeTeam"].get("crest", ""))
        eq_vis = Equipo(id=partido_obj["awayTeam"]["id"], nombre=partido_obj["awayTeam"]["name"], crest=partido_obj["awayTeam"].get("crest", ""))

        local_nom = eq_loc.nombre
        visitante_nom = eq_vis.nombre

        st.write("##### 🕒 Próximos Encuentros Destacados")
        cols = st.columns(min(5, len(partidos_hoy)))
        for idx, m in enumerate(partidos_hoy[:5]):
            with cols[idx]:
                code_liga = m.get('competition', {}).get('code', '')
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

    equipos_dict = {e.nombre: e for e in equipos}
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

df_loc_hist = obtener_ultimos_partidos(jugados, eq_loc.id, n=40, solo_condicion=cond_loc)
df_vis_hist = obtener_ultimos_partidos(jugados, eq_vis.id, n=40, solo_condicion=cond_vis)

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

try:
    prob_1, prob_x, prob_2, df_top_m, df_ou, df_btts = calcular_matrices_completas(exp_local, exp_vis)
except Exception as e:
    st.error("❌ Error calculando marcadores/mercados (Over-Under, BTTS, marcador exacto). Detalle del fallo:")
    st.exception(e)
    st.stop()

stats_esp = estimar_corners_y_tiros(exp_local, exp_vis, pr_loc, pr_vis)

st.markdown(f"""
<div class="scoreboard">
    <div style="display:flex; justify-content:space-around; align-items:center;">
        <div style="flex:1;">
            {"<img src='" + eq_loc.crest + "' height='65'><br>" if eq_loc.crest else ""}
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
            {"<img src='" + eq_vis.crest + "' height='65'><br>" if eq_vis.crest else ""}
            <h2 style="margin:6px 0; color:white;">{visitante_nom}</h2>
            <span class="power-badge">Power Rank: {pr_vis} / 1
