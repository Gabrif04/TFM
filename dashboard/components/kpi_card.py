"""Tarjeta KPI reutilizable."""
import streamlit as st


def kpi_card(label: str, value: str, delta: str | None = None, help: str | None = None):
    """
    Renderiza una tarjeta KPI usando st.metric.

    Args:
        label: Etiqueta de la métrica.
        value: Valor principal a mostrar.
        delta: Variación opcional (string, e.g. "+3").
        help: Texto de ayuda opcional (tooltip).
    """
    st.metric(label=label, value=value, delta=delta, help=help)
