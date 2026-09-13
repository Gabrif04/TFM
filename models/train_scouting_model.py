"""
Modelo de scouting puro: valor de mercado explicado SOLO por el jugador.

Diferencias con train_market_value_model.py:

  1. Sin features de contexto. Fuera `team_points`, `team_position` y
     `league`. En el modelo general esas tres dominaban (team_points era la
     más importante con diferencia) y hacían que predijera sobre todo "en qué
     equipo juegas". Quitándolas el R2 baja, pero lo que queda es señal
     individual: permite encontrar jugadores buenos en equipos malos, que es
     justo el caso de uso de captación.

  2. Solo jugadores de campo. Los porteros quedan FUERA del modelo, no en un
     submodelo aparte. El motivo es que no hay con qué evaluarlos: el
     extractor pide únicamente los stat_type "standard" y "misc" de FBref,
     que no incluyen nada de portería (ni paradas, ni porterías a cero, ni
     PSxG). Sobre esas features un portero es un jugador de campo con todo a
     cero (goles 0.000, centros 0.0004), así que cualquier predicción se
     apoyaría en edad, minutos y altura, sin contenido deportivo. Antes que
     publicar un ranking de porteros que no significa nada, se excluyen y se
     deja constancia de la limitación.

     Para incorporarlos en el futuro hay que extraer los stat_type "keeper" y
     "keeper_adv" en extractors/soccerdata_extractor.py.

Uso:
    python -m models.train_scouting_model
"""
import numpy as np
import pandas as pd

from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import KFold, cross_val_predict

from models.train_market_value_model import (
    build_pipeline, compute_metrics, format_metrics, load_dataset, TARGET,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# Sin team_points/team_position: el valor lo tiene que explicar el jugador.
SCOUTING_NUMERIC = [
    "age", "age_squared", "minutes_played", "matches_played", "starts_ratio",
    "goals_p90", "assists_p90", "crosses_p90", "tackles_p90", "interceptions_p90",
    "yellow_cards_p90", "fouls_committed_p90", "fouls_drawn_p90",
    "xg_p90", "xa_p90", "penalties_scored",
    "height_cm", "contract_years_left",
]
# Sin `league`: no queremos que el modelo premie jugar en la Premier.
SCOUTING_CATEGORICAL = ["position_group", "foot"]

MODEL_PARAMS = dict(
    n_estimators=600, learning_rate=0.05, max_depth=2,
    subsample=0.85, random_state=42,
)


def _pipeline(numeric: list[str], categorical: list[str]):
    """build_pipeline lee las listas de features a nivel de módulo, así que
    se sobrescriben temporalmente y se restauran después: sin restaurarlas,
    quedaban contaminadas para cualquier uso posterior del modelo general."""
    import models.train_market_value_model as base
    original = base.NUMERIC_FEATURES, base.CATEGORICAL_FEATURES
    try:
        base.NUMERIC_FEATURES, base.CATEGORICAL_FEATURES = numeric, categorical
        return build_pipeline(GradientBoostingRegressor(**MODEL_PARAMS))
    finally:
        base.NUMERIC_FEATURES, base.CATEGORICAL_FEATURES = original


def load_outfield_dataset(season: str = "2025-2026") -> pd.DataFrame:
    """Dataset de scouting: el general menos los porteros."""
    df = load_dataset(season)
    porteros = df["position_group"] == "Portero"
    logger.info(
        "Excluidos %d porteros: sin estadísticas de portería no son evaluables",
        int(porteros.sum()),
    )
    return df[~porteros]


def fit_and_rank(df: pd.DataFrame) -> pd.DataFrame:
    """Entrena, evalúa con validación cruzada y devuelve el df con predicción
    y residuo. Las predicciones salen de cross_val_predict: cada jugador se
    predice con un modelo que no lo ha visto, que es lo correcto para
    detectar oportunidades reales y no memorización."""
    features = SCOUTING_NUMERIC + SCOUTING_CATEGORICAL
    X, y = df[features], df["log_value"]
    cv = KFold(n_splits=5, shuffle=True, random_state=42)
    preds_log = cross_val_predict(_pipeline(SCOUTING_NUMERIC, SCOUTING_CATEGORICAL), X, y, cv=cv)

    print(format_metrics("Jugadores de campo", compute_metrics(y, preds_log), n=len(df)))

    out = df.copy()
    out["pred_value_eur"] = np.expm1(preds_log)
    out["residual_ratio"] = out[TARGET] / out["pred_value_eur"]
    return out


def print_ranking(df: pd.DataFrame, n: int = 20) -> None:
    cols = ["player_name", "team", "league", "position_group", "age",
            TARGET, "pred_value_eur", "residual_ratio"]
    fmt = lambda x: f"{x:,.2f}"
    print(f"\n{'=' * 78}\nTOP {n} INFRAVALORADOS "
          f"(valor real muy por debajo del que explican sus stats)\n{'=' * 78}")
    print(df.nsmallest(n, "residual_ratio")[cols].to_string(index=False, float_format=fmt))
    print(f"\n{'=' * 78}\nTOP {n} SOBREVALORADOS\n{'=' * 78}")
    print(df.nlargest(n, "residual_ratio")[cols].to_string(index=False, float_format=fmt))


def main():
    df = load_outfield_dataset()
    print(f"\nModelo de scouting (sin equipo ni liga, solo jugadores de campo)\n" + "-" * 78)
    resultado = fit_and_rank(df)
    print_ranking(resultado)


if __name__ == "__main__":
    main()
