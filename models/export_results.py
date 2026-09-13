"""
Ejecuta los dos modelos y exporta los resultados a CSV.

Genera dos ficheros en la carpeta `results/`:

  resultados_jugadores.csv
      Una fila por jugador con TODA la información: identificación,
      features usadas, valor real, y las predicciones y residuos de LOS DOS
      modelos en paralelo. Así se puede comparar directamente qué dice el
      modelo general (con contexto de equipo y liga) frente al de scouting
      (solo rendimiento individual) sobre el mismo futbolista.

  metricas_modelos.csv
      Una fila por modelo con R2, MAE, RMSE y error mediano.

Los dos scripts de entrenamiento siguen funcionando igual e imprimiendo por
pantalla; este es un tercer punto de entrada que no los modifica.

Todas las predicciones salen de cross_val_predict: cada jugador se predice
con un modelo que no lo ha visto durante el entrenamiento, que es lo
correcto para que los residuos señalen oportunidades reales.

Uso:
    python -m models.export_results
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import KFold, cross_val_predict

import models.train_market_value_model as base
from models.train_market_value_model import (
    CATEGORICAL_FEATURES, NUMERIC_FEATURES, TARGET,
    build_pipeline, compute_metrics, format_metrics, load_dataset,
)
from models.train_scouting_model import (
    MODEL_PARAMS, SCOUTING_CATEGORICAL, SCOUTING_NUMERIC,
)
from utils.logger import get_logger

logger = get_logger(__name__)

OUTPUT_DIR = "results"

# Nombres autoexplicativos: lo que separa a ambos modelos es si usan las
# variables de entorno del jugador (puntos y posición del equipo, y liga)
# o solo su rendimiento individual.
NOMBRE_GENERAL = "Modelo general (incluye equipo y liga)"
NOMBRE_SCOUTING = "Detección de oportunidades (solo rendimiento individual)"

IDENTIFICACION = [
    "player_name", "team", "league", "season", "position_group", "age",
    "minutes_played", "matches_played", "contract_years_left",
]


def _predict_cv(df: pd.DataFrame, numeric: list[str], categorical: list[str]) -> np.ndarray:
    """Predicciones fuera de muestra. build_pipeline lee las listas de
    features a nivel de módulo, así que se sobrescriben temporalmente y se
    restauran después: sin restaurarlas, una llamada con las features de
    scouting dejaba contaminadas las del modelo general para las llamadas
    siguientes."""
    original = base.NUMERIC_FEATURES, base.CATEGORICAL_FEATURES
    try:
        base.NUMERIC_FEATURES, base.CATEGORICAL_FEATURES = numeric, categorical
        pipe = build_pipeline(GradientBoostingRegressor(**MODEL_PARAMS))
        cv = KFold(n_splits=5, shuffle=True, random_state=42)
        return cross_val_predict(pipe, df[numeric + categorical], df["log_value"], cv=cv)
    finally:
        base.NUMERIC_FEATURES, base.CATEGORICAL_FEATURES = original


def main() -> None:
    df = load_dataset()
    metricas = []

    # --- Modelo general: incluye las variables de equipo y liga ---
    preds_general = _predict_cv(df, NUMERIC_FEATURES, CATEGORICAL_FEATURES)
    m = compute_metrics(df["log_value"], preds_general)
    print(format_metrics("Modelo general", m, n=len(df)))
    metricas.append({"modelo": NOMBRE_GENERAL, "n": len(df), **m})

    df = df.copy()
    df["pred_general_eur"] = np.expm1(preds_general)
    df["residuo_general"] = df[TARGET] / df["pred_general_eur"]

    # --- Detección de oportunidades: sin equipo ni liga, solo jugadores de campo ---
    # Los porteros quedan fuera: sin estadísticas de portería en las fuentes,
    # su predicción no tendría contenido deportivo (ver train_scouting_model).
    es_portero = df["position_group"] == "Portero"
    campo = df[~es_portero]
    preds = _predict_cv(campo, SCOUTING_NUMERIC, SCOUTING_CATEGORICAL)
    m = compute_metrics(campo["log_value"], preds)
    print(format_metrics("Detección de oportunidades", m, n=len(campo)))
    metricas.append({"modelo": NOMBRE_SCOUTING, "n": len(campo), **m})

    df["pred_scouting_eur"] = np.nan
    df.loc[~es_portero, "pred_scouting_eur"] = np.expm1(preds)
    df["residuo_scouting"] = df[TARGET] / df["pred_scouting_eur"]

    # --- Exportación ---
    features = sorted(set(NUMERIC_FEATURES + CATEGORICAL_FEATURES + SCOUTING_NUMERIC))
    columnas = (
        IDENTIFICACION
        + [c for c in features if c not in IDENTIFICACION]
        + [TARGET, "pred_general_eur", "residuo_general",
           "pred_scouting_eur", "residuo_scouting"]
    )
    salida = df[[c for c in dict.fromkeys(columnas) if c in df.columns]]
    # Los porteros quedan con residuo_scouting nulo y van al final.
    salida = salida.sort_values("residuo_scouting", na_position="last")

    import os
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ruta_jugadores = os.path.join(OUTPUT_DIR, "resultados_jugadores.csv")
    ruta_metricas = os.path.join(OUTPUT_DIR, "metricas_modelos.csv")

    # utf-8-sig para que Excel en Windows respete acentos y eñes.
    salida.to_csv(ruta_jugadores, index=False, encoding="utf-8-sig")
    pd.DataFrame(metricas).to_csv(ruta_metricas, index=False, encoding="utf-8-sig")

    print(f"\n{len(salida)} jugadores y {len(salida.columns)} columnas -> {ruta_jugadores}")
    print(f"{len(metricas)} filas de métricas -> {ruta_metricas}")
    print("\nOrdenado por residuo_scouting ascendente: los primeros son los "
          "candidatos a infravalorados. Los porteros aparecen al final, sin "
          "predicción de scouting.")
    print("residuo = valor real / valor predicho (< 1 infravalorado, > 1 sobrevalorado)")


if __name__ == "__main__":
    main()
