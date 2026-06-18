import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from warren import HistoryManager, MATERIALS, WarrenTruss


# ----
# Page config
# ----
st.set_page_config(
    page_title="Calculadora — Puente Warren",
    page_icon="🧱",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ----
# Theme / CSS
# ----
CSS = """
<style>
:root {
  --bg: #0B1E33;
  --panel: #0F2744;
  --card: #102A4A;
  --muted: #89A9C7;
  --text: #EAF2FA;
  --accent: #2563EB;
  --accent2: #F59E0B;
  --danger: #DC2626;
  --safe: #16A34A;
  --warn: #D97706;
}

/* Main background */
.stApp {
  background: radial-gradient(1200px 600px at 10% 10%, #163A5F 0%, var(--bg) 55%, #061425 100%);
  color: var(--text);
}

/* Sidebar */
section[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #0C2340 0%, #071A2E 100%);
  border-right: 1px solid rgba(255,255,255,0.06);
}

/* Hide Streamlit default footer/menu spacing a bit */
footer { visibility: hidden; }

/* Buttons */
.stButton>button {
  width: 100%;
  border-radius: 10px;
  padding: 0.85rem 1rem;
  border: 0;
  font-weight: 700;
}

/* Primary button style (Streamlit uses classes inconsistently; keep it simple) */

/* Cards */
.block-container {
  padding-top: 1.2rem;
}

/* Metric cards */
[data-testid="stMetric"] {
  background: rgba(16,42,74,0.75);
  border: 1px solid rgba(255,255,255,0.08);
  padding: 14px 14px;
  border-radius: 14px;
}

/* Tabs */
div[data-baseweb="tab-list"] {
  gap: 6px;
}
button[data-baseweb="tab"] {
  background: rgba(255,255,255,0.06);
  border-radius: 999px;
  padding: 10px 14px;
}
button[data-baseweb="tab"][aria-selected="true"] {
  background: rgba(37,99,235,0.75);
}

/* Dataframe container */
[data-testid="stDataFrame"] {
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,0.08);
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ----
# Small helpers
# ----
Page = Literal["home", "calc"]


def _init_state() -> None:
    if "page" not in st.session_state:
        st.session_state.page = "home"
    if "last_run" not in st.session_state:
        st.session_state.last_run = None


def _goto(page: Page) -> None:
    st.session_state.page = page


@dataclass(frozen=True)
class Inputs:
    L: float
    H: float
    panels: int
    P_total: float
    area_cm2: float
    material: str


def validate_inputs(inp: Inputs) -> List[str]:
    errors: List[str] = []
    if inp.L <= 0:
        errors.append("La longitud total L debe ser positiva.")
    if inp.H <= 0:
        errors.append("La altura H debe ser positiva.")
    if inp.P_total <= 0:
        errors.append("La carga total debe ser positiva.")
    if inp.area_cm2 <= 0:
        errors.append("El área de sección debe ser positiva.")
    if not (2 <= inp.panels <= 20):
        errors.append("El número de paneles debe estar entre 2 y 20.")
    if inp.material not in MATERIALS:
        errors.append("Material inválido.")
    return errors


def verdict_message(v_level: str, verdict: str, subtitle: str) -> None:
    if v_level == "safe":
        st.success(f"{verdict} — {subtitle}")
    elif v_level == "warn":
        st.warning(f"{verdict} — {subtitle}")
    else:
        st.error(f"{verdict} — {subtitle}")


def build_members_dataframe(member_evals: List[Dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(member_evals)
    # Required columns:
    # ID, Nombre, Tipo, Fuerza, Longitud, Esfuerzo, Esfuerzo admisible, Ratio, Estado
    out = pd.DataFrame(
        {
            "ID": df["id"],
            "Nombre": df["name"],
            "Tipo": df["type"],
            "Fuerza (kN)": df["force"],
            "Longitud (m)": df["length"],
            "Esfuerzo (MPa)": df["sigma_MPa"],
            "Esfuerzo admisible (MPa)": df["allowable_MPa"],
            "Ratio": df["ratio"],
            "Estado": df["status"],
        }
    )
    return out


# ----
# Plotly diagram
# ----

def warren_geometry(L: float, H: float, panels: int) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    d = L / panels
    top_nodes = [(i * d, H) for i in range(panels + 1)]
    bot_nodes = [(i * d, 0.0) for i in range(panels + 1)]
    return top_nodes, bot_nodes


def member_segments(L: float, H: float, panels: int) -> Dict[str, Tuple[Tuple[float, float], Tuple[float, float]]]:
    top, bot = warren_geometry(L, H, panels)
    seg: Dict[str, Tuple[Tuple[float, float], Tuple[float, float]]] = {}

    # Bottom chord CIi: bot i -> bot i+1
    for i in range(panels):
        seg[f"CI{i+1}"] = (bot[i], bot[i + 1])

    # Top chord CSi: top i -> top i+1
    for i in range(panels):
        seg[f"CS{i+1}"] = (top[i], top[i + 1])

    # Diagonals Di alternate like original Tkinter draw
    for i in range(panels):
        if i % 2 == 0:
            # bot i -> top i+1
            seg[f"D{i+1}"] = (bot[i], top[i + 1])
        else:
            # top i -> bot i+1
            seg[f"D{i+1}"] = (top[i], bot[i + 1])

    return seg


def plot_truss(res: Dict[str, Any], member_evals: List[Dict[str, Any]]) -> go.Figure:
    L = float(res["L"])
    H = float(res["H"])
    n = int(res["panels"])
    d = L / n

    eval_by_id = {m["id"]: m for m in member_evals}
    max_f = max(abs(m["force"]) for m in member_evals) if member_evals else 1.0
    max_f = max(max_f, 1e-9)

    segs = member_segments(L, H, n)
    top_nodes, bot_nodes = warren_geometry(L, H, n)

    fig = go.Figure()

    # Members
    for mid, (p1, p2) in segs.items():
        ev = eval_by_id.get(mid)
        if not ev:
            continue
        force = float(ev["force"])
        stress_type = ev.get("stress_type", "")

        # Color by tension/compression (requirements)
        # Tension: green, Compression: red
        color = "#16A34A" if (stress_type.lower().startswith("t") or force > 0) else "#DC2626"

        # Thickness by magnitude
        width = 2.0 + 8.0 * (abs(force) / max_f)

        fig.add_trace(
            go.Scatter(
                x=[p1[0], p2[0]],
                y=[p1[1], p2[1]],
                mode="lines",
                line=dict(color=color, width=width),
                hovertemplate=(
                    f"<b>{mid}</b><br>"
                    f"Fuerza: {force:.3f} kN<br>"
                    f"Tipo: {stress_type}<extra></extra>"
                ),
                showlegend=False,
            )
        )

    # Nodes
    fig.add_trace(
        go.Scatter(
            x=[p[0] for p in bot_nodes],
            y=[p[1] for p in bot_nodes],
            mode="markers+text",
            marker=dict(size=10, color="#60A5FA", line=dict(width=1, color="#0B1E33")),
            text=[str(i) for i in range(len(bot_nodes))],
            textposition="bottom center",
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[p[0] for p in top_nodes],
            y=[p[1] for p in top_nodes],
            mode="markers",
            marker=dict(size=10, color="#F97316", line=dict(width=1, color="#0B1E33")),
            hoverinfo="skip",
            showlegend=False,
        )
    )

    # Supports
    # Left pin support at bot node 0
    x0, y0 = bot_nodes[0]
    fig.add_trace(
        go.Scatter(
            x=[x0],
            y=[y0 - 0.15 * H],
            mode="markers",
            marker=dict(symbol="triangle-up", size=18, color="#94A3B8"),
            hovertemplate="Apoyo fijo<extra></extra>",
            showlegend=False,
        )
    )

    # Right roller support at bot node n
    xr, yr = bot_nodes[-1]
    fig.add_trace(
        go.Scatter(
            x=[xr],
            y=[yr - 0.15 * H],
            mode="markers",
            marker=dict(symbol="triangle-up", size=18, color="#94A3B8"),
            hovertemplate="Apoyo móvil (rodillo)<extra></extra>",
            showlegend=False,
        )
    )

    # Roller base line
    fig.add_trace(
        go.Scatter(
            x=[xr - 0.3 * d, xr + 0.3 * d],
            y=[yr - 0.22 * H, yr - 0.22 * H],
            mode="lines",
            line=dict(color="#94A3B8", width=4),
            hoverinfo="skip",
            showlegend=False,
        )
    )

    # Loads: distributed at top nodes 1..n-1 (as original assumption)
    for i in range(1, n):
        xt, yt = top_nodes[i]
        # Downward arrow
        fig.add_annotation(
            x=xt,
            y=yt,
            ax=xt,
            ay=yt + 0.25 * H,
            xref="x",
            yref="y",
            axref="x",
            ayref="y",
            showarrow=True,
            arrowhead=2,
            arrowsize=1.2,
            arrowwidth=2,
            arrowcolor="#F59E0B",
        )

    fig.update_layout(
        title="Diagrama — Armadura Warren (Tensión=Verde, Compresión=Rojo)",
        margin=dict(l=20, r=20, t=60, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.02)",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False, scaleanchor="x", scaleratio=1),
    )

    # Fit view
    fig.update_xaxes(range=[-0.06 * L, 1.06 * L])
    fig.update_yaxes(range=[-0.35 * H, 1.25 * H])

    return fig


# ----
# UI Pages
# ----

def page_home() -> None:
    # Home / portada inspired by your screenshots
    c1, c2, c3 = st.columns([1, 1.2, 1])

    # Top-left corner: logo1.png (universidad) — se muestra solo si existe
    with c1:
        if os.path.exists("logo1.png"):
            st.image("logo1.png", width=80)
        else:
            # Mantener espacio visual si no existe (no rompe el layout)
            st.write("")

    with c2:
        st.markdown(
            """
            <div style="text-align:center; padding: 18px 12px;">
              <div style="font-size: 14px; letter-spacing: 0.12em; color: #94A3B8; font-weight: 800;">
                CALCULADORA
              </div>
              <div style="font-size: 44px; font-weight: 900; color: #FFFF; line-height: 1.05; margin-top: 6px;">
                PUENTE WARREN
              </div>
              <div style="font-size: 18px; color: #89A9C7; margin-top: 8px;">
                Proyecto Integrador — Ingeniería
              </div>
              <div style="height: 10px;"></div>
              <div style="height: 3px; width: 140px; margin: 0 auto; background: #F59E0B; border-radius: 999px;"></div>
              <div style="height: 22px;"></div>
              <div style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 14px;">
                <div style="color:#EAF2FA; font-weight:700;">Análisis estructural de armaduras</div>
                <div style="color:#89A9C7; margin-top:6px;">Método de secciones · FS = 1.67 · A36 / A572 / Al 6061</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Gemini logo (logo2.png) justo encima del botón INGRESAR — se muestra solo si existe
        if os.path.exists("logo2.png"):
            st.image("logo2.png", width=120)

        st.button("▶ INGRESAR", on_click=_goto, args=("calc",))

        st.caption("v2.0 · Armadura Warren simétrica")


def page_calc() -> None:
    st.title("🧱 Puente de Armadura Tipo Warren")
    st.caption("Cálculo de fuerzas internas · reacciones · verificación de esfuerzos admisibles · sugerencias · historial")

    # Sidebar
    st.sidebar.header("Parámetros de entrada")

    L = st.sidebar.number_input("Longitud total L (m)", min_value=0.01, value=20.0, step=0.5, format="%.3f")
    H = st.sidebar.number_input("Altura H (m)", min_value=0.01, value=3.0, step=0.1, format="%.3f")
    panels = st.sidebar.slider("Número de paneles", min_value=2, max_value=20, value=6, step=1)
    P_total = st.sidebar.number_input("Carga total (kN)", min_value=0.01, value=500.0, step=10.0, format="%.3f")
    area_cm2 = st.sidebar.number_input("Área de sección (cm²)", min_value=0.01, value=50.0, step=1.0, format="%.3f")
    material = st.sidebar.selectbox("Material", options=list(MATERIALS.keys()), index=0)

    col_sb1, col_sb2 = st.sidebar.columns(2)
    with col_sb1:
        run = st.button("CALCULAR")
    with col_sb2:
        st.button("HOME", on_click=_goto, args=("home",))

    inp = Inputs(L=L, H=H, panels=panels, P_total=P_total, area_cm2=area_cm2, material=material)

    if run:
        errs = validate_inputs(inp)
        if errs:
            for e in errs:
                st.error(e)
        else:
            truss = WarrenTruss(inp.L, inp.H, inp.panels, inp.P_total)
            safety = truss.evaluate_safety(material=inp.material, section_area_cm2=inp.area_cm2)

            # Persist in session
            st.session_state.last_run = {
                "results": truss.results,
                "safety": safety,
                "inputs": {
                    "L": inp.L,
                    "H": inp.H,
                    "panels": inp.panels,
                    "P_total": inp.P_total,
                    "area_cm2": inp.area_cm2,
                    "material": inp.material,
                },
            }

            # Save to history.json
            sigma_max = max(e["sigma_MPa"] for e in safety["member_evals"]) if safety["member_evals"] else 0.0
            HistoryManager("history.json").save(
                {
                    "timestamp": truss.results["timestamp"],
                    "params": {
                    "L": inp.L,
                    "H": inp.H,
                    "panels": inp.panels,
                    "P": inp.P_total,
                    "area_cm2": inp.area_cm2,
                    "material": inp.material,
                    },
                    "verdict": safety["verdict"],
                    "v_level": safety["v_level"],
                    "max_force": truss.results["max_force"],
                    "sigma_max_MPa": round(float(sigma_max), 2),
                    "critical": safety["critical_members"],
                    "suggestions": safety["suggestions"],
                }
            )

    # If no run yet
    if not st.session_state.last_run:
        st.info("Ingresa los parámetros en la barra lateral y presiona CALCULAR.")
        return

    res = st.session_state.last_run["results"]
    safety = st.session_state.last_run["safety"]

    subtitle = f"Material: {safety['material']} | σ_adm = {safety['allowable_MPa']} MPa | Área = {safety['section_area_cm2']} cm²"
    verdict_message(safety["v_level"], f"ESTADO: {safety['verdict']}", subtitle)

    tabs = st.tabs(["Resumen", "Miembros", "Historial", "Diagrama"])

    # --- Resumen ---
    with tabs[0]:
        sigma_max = max(e["sigma_MPa"] for e in safety["member_evals"]) if safety["member_evals"] else 0.0

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Ra = Rb", f"{res['Ra']} kN")
        m2.metric("Fuerza Máx.", f"{res['max_force']} kN")
        m3.metric("Tensión Máx.", f"{sigma_max:.1f} MPa")
        m4.metric("N° Miembros", f"{res['n_members']}")
        m5.metric("Ángulo Diagonal", f"{res['angle_deg']}°")

        st.subheader("Sugerencias de diseño")
        if safety["suggestions"]:
            for s in safety["suggestions"]:
                # Mirror original color tone by overall verdict
                if safety["v_level"] == "danger":
                    st.error(s)
                elif safety["v_level"] == "warn":
                    st.warning(s)
                else:
                    st.success(s)
        else:
            st.success("Sin sugerencias adicionales.")

    # --- Miembros ---
    with tabs[1]:
        st.subheader("Tabla de miembros")
        df = build_members_dataframe(safety["member_evals"])

        # Add a helper column for sorting / conditional formatting
        color_map = {"SEGURO": "✅", "LIMITE": "⚠️", "FALLA": "❌"}
        df_show = df.copy()
        df_show.insert(0, " ", df_show["Estado"].map(color_map).fillna(""))

        st.dataframe(df_show, use_container_width=True, hide_index=True)

    # --- Historial ---
    with tabs[2]:
        st.subheader("Historial")
        hm = HistoryManager("history.json")
        records = hm.get_all()

        c1, c2 = st.columns([1, 1])
        with c1:
            st.caption("Se guarda en `history.json`. En Streamlit Cloud puede reiniciarse si la app se reinicia.")
        with c2:
            if st.button("🗑️ Borrar historial"):
                hm.clear()
                st.success("Historial borrado.")
                st.rerun()

        if not records:
            st.info("No hay registros todavía.")
        else:
            # Flatten for display
            rows: List[Dict[str, Any]] = []
            for r in records:
                p = r.get("params", {})
                rows.append(
                    {
                    "Fecha": r.get("timestamp", ""),
                    "L (m)": p.get("L", ""),
                    "H (m)": p.get("H", ""),
                    "Paneles": p.get("panels", ""),
                    "P (kN)": p.get("P", ""),
                    "A (cm²)": p.get("area_cm2", ""),
                    "Material": p.get("material", ""),
                    "Estado": r.get("verdict", ""),
                    "Fmax (kN)": r.get("max_force", ""),
                    "σmax (MPa)": r.get("sigma_max_MPa", ""),
                    }
                )
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # --- Diagrama ---
    with tabs[3]:
        st.subheader("Diagrama")
        st.caption("Se dibuja con Plotly (sin Tkinter Canvas). Incluye nodos, apoyos y cargas.")
        fig = plot_truss(res, safety["member_evals"])
        st.plotly_chart(fig, use_container_width=True)


# ----
# App entry
# ----

def main() -> None:
    _init_state()

    if st.session_state.page == "home":
        page_home()
    else:
        page_calc()


if __name__ == "__main__":
    main()
