"""CSV-only data contract. No pipeline or database imports."""
from pathlib import Path
import unicodedata

import numpy as np
import pandas as pd
import streamlit as st

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "salida_modelos"
MODELS = {"General": "pred_general_eur", "Scouting": "pred_scouting_eur"}
KEY = ["player_name", "team", "league", "season"]
LABELS = {
    "player_name": "Jugador", "team": "Equipo", "league": "Liga", "season": "Temporada",
    "position_group": "Posición", "age": "Edad", "minutes_played": "Minutos",
    "matches_played": "Partidos", "contract_years_left": "Contrato restante (años)",
    "age_squared": "Edad al cuadrado", "assists_p90": "Asistencias / 90",
    "crosses_p90": "Centros / 90", "foot": "Pie", "fouls_committed_p90": "Faltas cometidas / 90",
    "fouls_drawn_p90": "Faltas recibidas / 90", "goals_p90": "Goles / 90", "height_cm": "Altura (cm)",
    "interceptions_p90": "Intercepciones / 90", "penalties_scored": "Penaltis marcados",
    "starts_ratio": "Proporción de titularidades", "tackles_p90": "Entradas ganadas / 90",
    "team_points": "Puntos del equipo", "team_position": "Posición del equipo",
    "xa_p90": "xA / 90", "xg_p90": "xG / 90", "yellow_cards_p90": "Amarillas / 90",
    "market_value_eur": "Valor de mercado (€)", "pred_general_eur": "Estimación general (€)",
    "pred_scouting_eur": "Estimación scouting (€)", "residuo_general": "Mercado / estimación general",
    "residuo_scouting": "Mercado / estimación scouting", "estimate": "Estimación (€)",
    "difference": "Diferencia (€)", "difference_pct": "Diferencia (%)",
}
TEXT_COLUMNS = KEY + ["position_group", "foot"]
REQUIRED = KEY + ["position_group", "age", "minutes_played", "matches_played",
                  "market_value_eur", "pred_general_eur", "pred_scouting_eur"]
IDENTITY_CORRECTIONS = {
    ("Vitinha", "Genoa", "ITA", "2025-2026"): {
        "market_value_eur": 8_000_000.0,
        "data_note": (
            "Valor de mercado corregido a 8,0 M. El CSV asignaba 140,0 M a los dos "
            "jugadores llamados Vitinha; ese valor corresponde al jugador del PSG."
        ),
    },
}


def search_key(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value)).casefold()
                   if not unicodedata.combining(c))


def file_signature(path):
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


@st.cache_data(show_spinner=False)
def _read_players(path: str, signature: tuple) -> tuple[pd.DataFrame, list[str]]:
    df = pd.read_csv(path)
    missing = sorted(set(REQUIRED) - set(df.columns))
    if missing:
        raise ValueError("Faltan columnas imprescindibles: " + ", ".join(missing))
    if df.empty:
        raise ValueError("El CSV de jugadores no contiene observaciones.")
    for col in KEY + ["position_group"]:
        if df[col].isna().any() or df[col].astype(str).str.strip().eq("").any():
            raise ValueError(f"Hay identificadores vacíos en {col}.")
        df[col] = df[col].astype(str)
    if df.duplicated(KEY).any():
        raise ValueError("Hay observaciones duplicadas de jugador, equipo, liga y temporada.")
    warnings = []
    for col in LABELS:
        if col in df and col not in TEXT_COLUMNS:
            original = df[col]
            numeric = pd.to_numeric(original, errors="coerce")
            invalid = original.notna() & (numeric.isna() | ~np.isfinite(numeric))
            if invalid.any():
                warnings.append(f"{LABELS[col]}: {invalid.sum()} valores inválidos tratados como no disponibles.")
            df[col] = numeric.replace([np.inf, -np.inf], np.nan)
    for col in ["market_value_eur", *MODELS.values()]:
        invalid = df[col].notna() & df[col].le(0)
        if invalid.any():
            warnings.append(f"{LABELS[col]}: {invalid.sum()} valores no positivos tratados como no disponibles.")
            df.loc[invalid, col] = np.nan
    for col in LABELS:
        if col not in df and col not in ["estimate", "difference", "difference_pct"]:
            df[col] = np.nan
    df["data_note"] = ""
    for identity, correction in IDENTITY_CORRECTIONS.items():
        mask = pd.Series(True, index=df.index)
        for col, value in zip(KEY, identity):
            mask &= df[col].eq(value)
        if mask.sum() != 1:
            warnings.append("No se encontró la observación prevista para una corrección de identidad: " + " | ".join(identity))
            continue
        for col, value in correction.items():
            df.loc[mask, col] = value
        for suffix in ["general", "scouting"]:
            prediction = df.loc[mask, f"pred_{suffix}_eur"].iloc[0]
            df.loc[mask, f"residuo_{suffix}"] = (
                correction["market_value_eur"] / prediction if pd.notna(prediction) and prediction > 0 else np.nan
            )
    df["record_id"] = df[KEY].apply(lambda row: " | ".join(row), axis=1)
    df["search_name"] = df.player_name.map(search_key)
    return df, warnings


def load_players():
    path = OUTPUT_DIR / "resultados_jugadores.csv"
    return _read_players(str(path), file_signature(path))


@st.cache_data(show_spinner=False)
def _read_metrics(path, signature):
    df = pd.read_csv(path)
    required = ["modelo", "n", "r2", "mae", "rmse", "ape_mediano"]
    if not set(required).issubset(df.columns):
        raise ValueError("El archivo de métricas no tiene las columnas esperadas.")
    for col in required[1:]:
        df[col] = pd.to_numeric(df[col], errors="raise")
    return df[required]


def load_metrics():
    path = OUTPUT_DIR / "metricas_modelos.csv"
    return _read_metrics(str(path), file_signature(path))


def with_model(df, model):
    result = df.copy()
    result["estimate"] = result[MODELS[model]]
    result["difference"] = result.estimate - result.market_value_eur
    result["difference_pct"] = result.difference.div(result.market_value_eur.where(result.market_value_eur > 0)) * 100
    return result


def rank_players(df, metric, ascending, top_n):
    valid = df.dropna(subset=[metric])
    return valid.sort_values([metric, *KEY], ascending=[ascending, True, True, True, True]).head(top_n).copy()


def fmt_market_value(value):
    if pd.isna(value):
        return "-"
    millions = round(value / 1_000_000, 1)
    if millions == 0:
        millions = 0.0
    return f"{millions:,.1f} M".replace(",", " ").replace(".", ",")
