"""Gráfico de evolución del valor de mercado (Transfermarkt)."""
import plotly.graph_objects as go
import pandas as pd


def build_market_value_chart(mv_history: pd.DataFrame, player_name: str) -> go.Figure | None:
    """
    Construye un gráfico de línea con el histórico de valor de mercado.

    Args:
        mv_history: DataFrame con columnas [date, market_value_eur, club_at_time].
        player_name: Nombre del jugador para el tooltip.

    Returns:
        Figura Plotly o None si no hay datos.
    """
    if mv_history.empty:
        return None

    df = mv_history.copy()
    df["market_value_m"] = df["market_value_eur"] / 1_000_000

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["market_value_m"],
            mode="lines+markers",
            line=dict(color="#00d4aa", width=2),
            marker=dict(size=6, color="#00d4aa"),
            fill="tozeroy",
            fillcolor="rgba(0, 212, 170, 0.08)",
            customdata=df[["club_at_time", "age_at_time"]].values,
            hovertemplate=(
                "<b>%{x|%b %Y}</b><br>"
                "Valor: €%{y:.1f}M<br>"
                "Club: %{customdata[0]}<br>"
                "Edad: %{customdata[1]}<extra></extra>"
            ),
            name="Valor de mercado",
        )
    )

    fig.update_layout(
        xaxis=dict(
            title="",
            gridcolor="rgba(255,255,255,0.05)",
            linecolor="rgba(255,255,255,0.1)",
            tickfont=dict(color="rgba(255,255,255,0.6)", size=11),
        ),
        yaxis=dict(
            title="Millones €",
            gridcolor="rgba(255,255,255,0.05)",
            linecolor="rgba(255,255,255,0.1)",
            tickfont=dict(color="rgba(255,255,255,0.6)", size=11),
            titlefont=dict(color="rgba(255,255,255,0.5)", size=11),
            tickprefix="€",
            ticksuffix="M",
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=10, b=10),
        height=220,
        showlegend=False,
        hoverlabel=dict(bgcolor="#1e1e2e", font_color="white"),
    )
    return fig
