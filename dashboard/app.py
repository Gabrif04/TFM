"""Run from the repository root: streamlit run dashboard/app.py."""
import sys
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from views import overview, explorer, ranking

st.set_page_config(page_title="Scouting Lab · Valoración de jugadores", page_icon="⚽", layout="wide", initial_sidebar_state="auto")
st.markdown("""
<style>
.stApp {background: #10151e; color: #edf2f7;}
[data-testid="stHeader"] {background: #10151e;}
.block-container {max-width: 1440px; padding-top: 5rem; padding-bottom: 3rem;}
[data-testid="stMetric"] {background: #192230; border: 1px solid #2a3748;
border-radius: 12px; padding: 18px; min-height: 115px;}
[data-testid="stMetricLabel"] {color: #b7c5d8;}
[data-testid="stMetricValue"] {font-size: 1.65rem;}
h1 {letter-spacing: -0.035em;} h2, h3 {letter-spacing: -0.02em;}
.brand {color: #55d6b0; font-size: .8rem; letter-spacing: .18em; font-weight: 700;}
@media (max-width: 600px) {
    .block-container {padding: 2.25rem 1rem 2rem;}
    [data-testid="stMetric"] {min-height: 96px; padding: 12px;}
    [data-testid="stMetricValue"] {font-size: 1.35rem;}
    h1 {font-size: 2rem;}
}
</style>
""", unsafe_allow_html=True)
st.markdown('<div class="brand">SCOUTING LAB / TFM</div>', unsafe_allow_html=True)
# Explicit navigation disables discovery of the previous pages/ directory.
pages = [st.Page(overview, title="Datos", icon="📊", default=True),
         st.Page(explorer, title="Buscador y perfil", icon="🔎"),
         st.Page(ranking, title="Ranking", icon="🏅")]
st.navigation(pages, position="top").run()
