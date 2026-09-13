"""Radar chart de habilidades de jugador usando Plotly."""
from __future__ import annotations

import math

import plotly.graph_objects as go
import pandas as pd


# Métricas por grupo de posición
# Cada métrica: (columna_df, etiqueta_display, max_valor_referencia)
_RADAR_CONFIG: dict[str, list[tuple[str, str, float]]] = {
    "Portero": [
        ("minutes_played", "Minutos", 3000),
        ("yellow_cards", "T. Amarillas", 10),
        ("interceptions", "Intercepciones", 12),
        ("tackles", "Entradas", 25),
        ("fouls_committed", "Faltas", 20),
    ],
    "Defensa": [
        ("tackles", "Entradas", 40),
        ("interceptions", "Intercepciones", 30),
        ("xg_buildup", "xG BuildUp", 10),
        ("xa", "xA", 4),
        ("fouls_drawn", "Faltas recibidas", 30),
        ("yellow_cards", "T. Amarillas", 8),
    ],
    "Centrocampista": [
        ("tackles", "Entradas", 35),
        ("interceptions", "Intercepciones", 25),
        ("xg_chain", "xG Chain", 12),
        ("xg", "xG", 10),
        ("xa", "xA", 8),
        ("goals", "Goles", 12),
        ("assists", "Asistencias", 12),
    ],
    "Delantero": [
        ("goals", "Goles", 20),
        ("xg", "xG", 18),
        ("npxg", "npxG", 18),
        ("shots", "Remates", 80),
        ("assists", "Asistencias", 12),
        ("xa", "xA", 10),
        ("gls_per90", "Goles/90'", 1.5),
    ],
    "Otro": [
        ("goals", "Goles", 15),
        ("xg", "xG", 12),
        ("xa", "xA", 8),
        ("tackles", "Entradas", 25),
        ("interceptions", "Intercepciones", 20),
        ("minutes_played", "Minutos", 2500),
    ],
}


def _get_config(position_group: str) -> list[tuple[str, str, float]]:
    return _RADAR_CONFIG.get(position_group, _RADAR_CONFIG["Otro"])


def _normalize(value, max_ref: float) -> float:
    """Normaliza un valor suavemente para que el radar se vea más estable y menos extremo."""
    if max_ref == 0:
        return 0.0
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if num <= 0:
        return 0.0
    return min(math.log1p(num) / math.log1p(max_ref), 1.0)


def build_radar(
    row: pd.Series,
    position_group: str,
    color: str = "#00d4aa",
    title: str | None = None,
) -> go.Figure:
    """
    Construye un radar chart para un jugador.

    Args:
        row: Fila del DataFrame de jugadores enriquecido.
        position_group: Grupo de posición simplificado.
        color: Color de la línea y relleno.
        title: Título opcional del gráfico.

    Returns:
        Figura Plotly lista para st.plotly_chart().
    """
    config = _get_config(position_group)
    categories = [label for _, label, _ in config]
    values_norm = [_normalize(row.get(col, 0), max_ref) for col, _, max_ref in config]

    # Cerrar el polígono
    categories_closed = categories + [categories[0]]
    values_closed = values_norm + [values_norm[0]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=values_closed,
            theta=categories_closed,
            fill="toself",
            fillcolor=f"rgba({int(color[1:3], 16)}, {int(color[3:5], 16)}, {int(color[5:7], 16)}, 0.2)",
            line=dict(color=color, width=2),
            name=row.get("player_name", "Jugador"),
        )
    )

    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 1],
                showticklabels=False,
                gridcolor="rgba(255,255,255,0.1)",
            ),
            angularaxis=dict(
                gridcolor="rgba(255,255,255,0.15)",
                linecolor="rgba(255,255,255,0.2)",
            ),
            bgcolor="rgba(0,0,0,0)",
        ),
        showlegend=False,
        title=dict(text=title or "", font=dict(size=14, color="white"), x=0.5),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=40, r=40, t=50, b=40),
        height=350,
    )
    return fig


def build_radar_comparison(
    row_a: pd.Series,
    row_b: pd.Series,
    position_group: str,
) -> go.Figure:
    """Radar con dos jugadores superpuestos para comparación."""
    config = _get_config(position_group)
    categories = [label for _, label, _ in config]
    categories_closed = categories + [categories[0]]

    colors = [("#00d4aa", "rgba(0,212,170,0.15)"), ("#ff6b6b", "rgba(255,107,107,0.15)")]
    fig = go.Figure()

    for (row, (line_color, fill_color)) in zip([row_a, row_b], colors):
        vals = [_normalize(row.get(col, 0), max_ref) for col, _, max_ref in config]
        vals_closed = vals + [vals[0]]
        fig.add_trace(
            go.Scatterpolar(
                r=vals_closed,
                theta=categories_closed,
                fill="toself",
                fillcolor=fill_color,
                line=dict(color=line_color, width=2),
                name=row.get("player_name", ""),
            )
        )

    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 1], showticklabels=False,
                            gridcolor="rgba(255,255,255,0.1)"),
            angularaxis=dict(gridcolor="rgba(255,255,255,0.15)",
                             linecolor="rgba(255,255,255,0.2)"),
            bgcolor="rgba(0,0,0,0)",
        ),
        showlegend=True,
        legend=dict(font=dict(color="white")),
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=40, r=40, t=50, b=40),
        height=380,
    )
    return fig
