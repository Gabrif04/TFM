"""Local-only profile imagery. CSV observations remain the identity source."""
import base64
from html import escape
import json
from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).resolve().parents[1] / "assets"
MEDIA = ASSETS / "media"
LEAGUES = {"ESP": "España", "ENG": "Inglaterra", "ITA": "Italia", "GER": "Alemania",
           "FRA": "Francia", "POR": "Portugal", "NED": "Países Bajos"}
POSITIONS = {"Portero": "goalkeeper", "Defensa": "defender",
             "Centrocampista": "midfielder", "Delantero": "forward"}


@st.cache_data(show_spinner=False)
def _read_manifest(signature):
    try:
        return json.loads((MEDIA / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"club": {}, "player": {}}


def media_manifest():
    path = MEDIA / "manifest.json"
    return _read_manifest(path.stat().st_mtime_ns if path.exists() else None)


def media_entry(kind, key):
    item = media_manifest().get(kind, {}).get(key, {})
    if item.get("status") != "ready" or not item.get("path"):
        return None
    path = (MEDIA / item["path"]).resolve()
    if not path.is_relative_to(MEDIA.resolve()) or not path.is_file():
        return None
    return item


@st.cache_data(show_spinner=False)
def _data_uri(path, signature):
    path = Path(path)
    mime = "image/svg+xml" if path.suffix == ".svg" else "image/webp"
    return "data:" + mime + ";base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def image_tag(path, alt, css=""):
    path = Path(path)
    return f'<img class="{escape(css)}" src="{_data_uri(str(path), path.stat().st_mtime_ns)}" alt="{escape(alt)}">'


def render_profile_identity(row):
    player_key = "|".join(str(row[col]) for col in ["player_name", "team", "league", "season"])
    club_key = f"{row.league}|{row.team}"
    photo = media_entry("player", player_key)
    crest = media_entry("club", club_key)
    photo_path = MEDIA / photo["path"] if photo else ASSETS / "icons" / "person.svg"
    crest_path = MEDIA / crest["path"] if crest else ASSETS / "icons" / "club.svg"
    flag_path = ASSETS / "icons" / f"flag-{row.league}.svg"
    if not flag_path.exists():
        flag_path = ASSETS / "icons" / "globe.svg"
    position_path = ASSETS / "icons" / (POSITIONS.get(row.position_group, "pitch") + ".svg")
    badges = [
        (crest_path, str(row.team), "Escudo de " + str(row.team) if crest else "Club"),
        (flag_path, LEAGUES.get(row.league, row.league), "País de la liga; no es la nacionalidad del jugador"),
        (ASSETS / "icons" / "calendar.svg", str(row.season), "Temporada"),
        (position_path, str(row.position_group), "Posición"),
    ]
    badge_html = "".join(f'<span class="identity-badge" title="{escape(title)}">'
                         f'{image_tag(path, title)}<span>{escape(text)}</span></span>'
                         for path, text, title in badges)
    st.html(f"""
    <style>
    .player-identity {{display:flex;gap:24px;align-items:center;margin:8px 0 24px;}}
    .player-portrait {{width:112px;height:132px;object-fit:contain;background:#192230;
        border:1px solid #344456;border-radius:16px;flex-shrink:0;}}
    .identity-name {{font-size:clamp(1.6rem,3vw,2.2rem);font-weight:700;color:#edf2f7;
        line-height:1.2;margin:0 0 16px;}}
    .identity-badges {{display:flex;gap:10px;flex-wrap:wrap;}}
    .identity-badge {{display:inline-flex;align-items:center;gap:8px;padding:7px 11px;
        background:#192230;border:1px solid #2a3748;border-radius:9px;color:#cbd5e1;font-size:.9rem;}}
    .identity-badge img {{width:25px;height:27px;object-fit:contain;}}
    @media(max-width:600px) {{
        .player-identity {{gap:12px;align-items:flex-start;}}
        .player-portrait {{width:76px;height:94px;}}
        .identity-badge {{padding:5px 7px;font-size:.8rem;}}
        .identity-badge img {{width:21px;height:23px;}}
    }}
    </style>
    <div class="player-identity">
      {image_tag(photo_path, "Foto de " + str(row.player_name) if photo else "Foto no disponible", "player-portrait")}
      <div><h2 class="identity-name">{escape(str(row.player_name))}</h2>
      <div class="identity-badges">{badge_html}</div></div>
    </div>
    """)
    return [(label, item) for label, item in [("Foto", photo), ("Escudo", crest)] if item]


def render_credits(entries):
    if not entries:
        return
    with st.expander("Créditos de imágenes"):
        for label, item in entries:
            source = item.get("source", "")
            author = item.get("author") or "Autor indicado en la fuente"
            license_name = item.get("license") or "Ver fuente"
            license_url = item.get("license_url") or source
            st.html(f'<p><strong>{escape(label)}</strong> · {escape(author)} · '
                    f'<a href="{escape(license_url, quote=True)}" target="_blank" rel="noopener noreferrer">{escape(license_name)}</a>'
                    f' · <a href="{escape(source, quote=True)}" target="_blank" rel="noopener noreferrer">Fuente original</a></p>')
        st.caption("Imágenes de Wikimedia Commons, redimensionadas y convertidas a WebP. "
                   "Se conserva el encuadre original. Las imágenes pueden corresponder a otra fecha o equipación. "
                   "Banderas e iconos de posición: gráficos propios del proyecto.")
