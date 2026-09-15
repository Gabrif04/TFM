"""
Modelo predictivo de valor de mercado a partir de estadísticas de rendimiento.

Enfoque:  Dadas las stats de la temporada más
reciente, predice el valor de mercado actual. Los jugadores cuyo valor REAL
queda por debajo del PREDICHO son candidatos a infravalorados (oportunidad de
fichaje), y al revés. El residuo es la señal de scouting.


Decisiones de modelado relevantes:
  - Target en log: los valores de mercado son muy asimétricos (de 25 k€ a
    200 M€). Sin log, unos pocos jugadores muy valiosos dominan el error.
  - Edad al cuadrado: el valor no baja linealmente con la edad, hace pico
    en torno a los 24-27 y cae después. Un término lineal no lo capta.
  - npxg queda fuera: es casi idéntico a xg (xg sin penaltis) y su
    colinealidad provocaba coeficientes con signos opuestos sin sentido
    futbolístico. Se conserva xg y, aparte, los penaltis como feature.
  - Se comparan RandomForest y GradientBoosting, ambos basados en árboles:
    captan relaciones no lineales e interacciones (edad x posición) sin
    necesidad de especificarlas a mano.
"""
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from transform.gold import build_gold_scouting
from utils.logger import get_logger

logger = get_logger(__name__)

NUMERIC_FEATURES = [
    "age", "age_squared", "minutes_played", "matches_played", "starts_ratio",
    "goals_p90", "assists_p90", "crosses_p90", "tackles_p90", "interceptions_p90",
    "yellow_cards_p90", "fouls_committed_p90", "fouls_drawn_p90",
    "xg_p90", "xa_p90",
    "penalties_scored", "team_position", "team_points",
    "height_cm", "contract_years_left",
]
CATEGORICAL_FEATURES = ["position_group", "league", "foot"]
TARGET = "market_value_eur"
MIN_MINUTES = 450  # ~5 partidos completos: por debajo, las per-90 son ruido

# Filtro de calidad sobre la variable objetivo. El scraper de Transfermarkt
# busca por nombre y toma el primer resultado sin verificar que sea el
# jugador correcto, lo que produce emparejamientos con homónimos de
# categorías inferiores. Estos registros son los puntos más alejados
# posibles y contaminan tanto el entrenamiento como el ranking, donde
# encabezan la lista de infravalorados precisamente por estar mal.
#
# El criterio combina las tres condiciones: es futbolísticamente imposible
# que un jugador JOVEN y TITULAR HABITUAL en una liga top-5 valga menos de
# medio millón. La edad es imprescindible en la regla: sin ella se excluyen
# también veteranos de 32-38 años cuyo valor bajo es perfectamente legítimo
# (se midió: 13 de los 17 detectados sin el criterio de edad eran veteranos
# correctos, no errores).
MAX_VALOR_SOSPECHOSO = 500_000
MIN_MINUTOS_SOSPECHOSO = 900
MAX_EDAD_SOSPECHOSA = 26


def build_pipeline(model) -> Pipeline:
    preprocess = ColumnTransformer([
        ("num", Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]), NUMERIC_FEATURES),
        ("cat", Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("encode", OneHotEncoder(handle_unknown="ignore")),
        ]), CATEGORICAL_FEATURES),
    ])
    return Pipeline([("preprocess", preprocess), ("model", model)])


def suspicious_mask(df: pd.DataFrame) -> pd.Series:
    """Registros cuyo valor de mercado es incompatible con el perfil del
    jugador y que apuntan a un emparejamiento erróneo por homónimo."""
    return (
        (df[TARGET] <= MAX_VALOR_SOSPECHOSO)
        & (df["minutes_played"] >= MIN_MINUTOS_SOSPECHOSO)
        & (df["age"] <= MAX_EDAD_SOSPECHOSA)
    )


def load_dataset(season: str = "2025-2026", filtrar_sospechosos: bool = True) -> pd.DataFrame:
    gold = build_gold_scouting(season)
    df = gold[gold["has_market_value"] & (gold["minutes_played"] >= MIN_MINUTES)].copy()

    sospechosos = suspicious_mask(df)
    if filtrar_sospechosos and sospechosos.any():
        logger.info(
            "Excluidos %d registros por valor de mercado implausible: %s",
            int(sospechosos.sum()), ", ".join(df.loc[sospechosos, "player_name"]),
        )
        df = df[~sospechosos]

    df["age_squared"] = df["age"] ** 2
    df["log_value"] = np.log1p(df[TARGET])

    n_leagues = df["league"].nunique()
    logger.info(
        "Dataset: %d jugadores, %d ligas, mínimo %d minutos", len(df), n_leagues, MIN_MINUTES
    )
    if n_leagues < 2:
        logger.warning("Solo hay %d liga(s): `league` no aportará nada al modelo", n_leagues)
    return df


def compute_metrics(y_log: pd.Series, preds_log: np.ndarray) -> dict:
    """R2, MAE y RMSE sobre la escala logarítmica (la que se modela), más el
    error porcentual mediano en euros, que es el único interpretable sin
    deshacer mentalmente el logaritmo.

    MAE y RMSE se reportan juntas a propósito: MAE es el error típico y RMSE
    penaliza más los errores grandes, así que la distancia entre ambas informa
    de la cola de jugadores mal predichos. Si fueran parecidas, el error
    estaría repartido de forma homogénea.

    Función compartida por los dos modelos (general y scouting) para que sus
    resultados sean directamente comparables.
    """
    real = np.expm1(y_log)
    pred = np.expm1(preds_log)
    return {
        "r2": r2_score(y_log, preds_log),
        "mae": mean_absolute_error(y_log, preds_log),
        "rmse": mean_squared_error(y_log, preds_log) ** 0.5,
        "ape_mediano": np.median(np.abs(real - pred) / real),
    }


def format_metrics(name: str, metrics: dict, n: int | None = None) -> str:
    prefijo = f"[{name:26s}]" + (f" n={n:5d} " if n is not None else "")
    return (f"{prefijo} R2(log)={metrics['r2']:.3f}  MAE(log)={metrics['mae']:.3f}  "
            f"RMSE(log)={metrics['rmse']:.3f}  error mediano={metrics['ape_mediano']:.1%}")


def print_target_distribution(df: pd.DataFrame) -> None:
    """Resumen de la variable objetivo. Justifica numéricamente la
    transformación logarítmica: si la media supera con holgura a la mediana,
    la distribución tiene una cola derecha larga y unos pocos jugadores de
    élite dominarían la función de pérdida sin transformar."""
    v = df[TARGET]
    millones = lambda x: f"{x / 1e6:,.1f} M€"
    print(f"\n{'=' * 70}\nDISTRIBUCIÓN DEL VALOR DE MERCADO ({len(df)} jugadores)\n{'=' * 70}")
    for etiqueta, valor in [
        ("Mínimo", v.min()), ("Percentil 25", v.quantile(.25)), ("Mediana", v.median()),
        ("Media", v.mean()), ("Percentil 75", v.quantile(.75)),
        ("Percentil 95", v.quantile(.95)), ("Máximo", v.max()),
    ]:
        print(f"  {etiqueta:14s} {millones(valor):>12s}")
    print(f"\n  Asimetría (skew): {v.skew():.2f}   Media / mediana: {v.mean() / v.median():.2f}x")
    print(f"  Tras aplicar log1p, la asimetría baja a {np.log1p(v).skew():.2f}.")
    print("  Una media muy por encima de la mediana indica cola derecha larga: sin\n"
          "  transformar, el error de unos pocos jugadores de mucho valor dominaría la función de pérdida.")


def evaluate_cv(df: pd.DataFrame, model, name: str, n_splits: int = 5) -> dict:
    X, y = df[NUMERIC_FEATURES + CATEGORICAL_FEATURES], df["log_value"]
    pipe = build_pipeline(model)
    cv = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    preds_log = cross_val_predict(pipe, X, y, cv=cv)
    metrics = compute_metrics(y, preds_log)
    print(format_metrics(name, metrics))
    return metrics


def print_model_parameters(pipe: Pipeline, name: str, df: pd.DataFrame) -> None:
    """Hiperparámetros + peso de cada feature. Se usa permutation importance
    en vez del feature_importances_ propio de los árboles, porque esta última
    está sesgada hacia variables con muchos valores distintos."""
    model = pipe.named_steps["model"]

    print(f"\n{'=' * 70}\nPARÁMETROS DEL MODELO: {name}\n{'=' * 70}")
    print("\nHiperparámetros:")
    for k, v in sorted(model.get_params().items()):
        print(f"  {k:24s} = {v}")

    X, y = df[NUMERIC_FEATURES + CATEGORICAL_FEATURES], df["log_value"]
    perm = permutation_importance(pipe, X, y, n_repeats=5, random_state=42, scoring="r2")
    imp = pd.DataFrame({
        "feature": NUMERIC_FEATURES + CATEGORICAL_FEATURES,
        "caida_r2": perm.importances_mean,
    }).sort_values("caida_r2", ascending=False)
    print("\nImportancia por permutación (caída de R2 al barajar la feature):")
    print(imp.to_string(index=False, float_format=lambda x: f"{x:9.4f}"))


def report_suspicious_values(df: pd.DataFrame) -> None:
    """Informa de los registros que suspicious_mask marcaría. Con el filtro
    activado en load_dataset ya no quedan en el dataset, así que sirve como
    comprobación de que el criterio sigue vigente al cambiar los datos."""
    sospechosos = df[suspicious_mask(df)]
    if sospechosos.empty:
        print("\nControl de calidad: sin valores de mercado implausibles en el dataset.")
        return
    print(f"\n{'!' * 70}")
    print(f"AVISO DE CALIDAD: {len(sospechosos)} registros con valor implausible "
          f"(<= {MAX_VALOR_SOSPECHOSO:,} EUR, {MIN_MINUTOS_SOSPECHOSO}+ minutos, "
          f"edad <= {MAX_EDAD_SOSPECHOSA}).")
    print(f"{'!' * 70}")
    print(sospechosos.nsmallest(10, TARGET)[
        ["player_name", "team", "league", "age", "minutes_played", TARGET]
    ].to_string(index=False, float_format=lambda x: f"{x:,.0f}"))


def main():
    df = load_dataset()
    report_suspicious_values(df)
    print_target_distribution(df)

    candidates = {
        "RandomForest": RandomForestRegressor(
            n_estimators=400, max_depth=12, min_samples_leaf=3, random_state=42, n_jobs=-1
        ),
        "GradientBoosting": GradientBoostingRegressor(
            n_estimators=400, learning_rate=0.05, max_depth=3, subsample=0.8, random_state=42
        ),
    }
    print(f"Validación cruzada 5-fold sobre {len(df)} jugadores\n" + "-" * 70)
    results = {name: evaluate_cv(df, model, name) for name, model in candidates.items()}

    best_name = max(results, key=lambda n: results[n]["r2"])
    print(f"\nMejor modelo por R2: {best_name}")

    best_pipe = build_pipeline(candidates[best_name])
    X = df[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
    best_pipe.fit(X, df["log_value"])
    print_model_parameters(best_pipe, best_name, df)

    # Residuos fuera de muestra: usar las predicciones del propio fit
    # sobreestimaría al jugador (el modelo ya lo ha visto). Con
    # cross_val_predict cada jugador se predice con un modelo que no lo
    # incluía, que es lo correcto para detectar oportunidades reales.
    cv = KFold(n_splits=5, shuffle=True, random_state=42)
    df["pred_value_eur"] = np.expm1(
        cross_val_predict(build_pipeline(candidates[best_name]), X, df["log_value"], cv=cv)
    )
    df["residual_ratio"] = df[TARGET] / df["pred_value_eur"]

    cols = ["player_name", "team", "league", "position_group", "age", TARGET,
            "pred_value_eur", "residual_ratio"]
    fmt = lambda x: f"{x:,.2f}"

    infra = df.nsmallest(25, "residual_ratio")[cols]
    print(f"\n{'=' * 70}\nTOP 25 INFRAVALORADOS (valor real << predicho por sus stats)\n{'=' * 70}")
    print(infra.to_string(index=False, float_format=fmt))

    sobre = df.nlargest(25, "residual_ratio")[cols]
    print(f"\n{'=' * 70}\nTOP 25 SOBREVALORADOS (el mercado paga más de lo que explican sus stats)\n{'=' * 70}")
    print(sobre.to_string(index=False, float_format=fmt))


if __name__ == "__main__":
    main()
