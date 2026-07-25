import pandas as pd
from utils.logger import get_logger

logger = get_logger(__name__)


def check_no_empty(df: pd.DataFrame) -> tuple[bool, str]:
    if df.empty:
        return False, "DataFrame vacío"
    return True, f"OK: {len(df)} filas"


def check_required_columns(df: pd.DataFrame, required: list[str]) -> tuple[bool, str]:
    missing = [c for c in required if c not in df.columns]
    if missing:
        return False, f"Faltan columnas: {missing}"
    return True, "OK: columnas requeridas presentes"


def check_no_duplicate_players(df: pd.DataFrame, key_cols: list[str]) -> tuple[bool, str]:
    dups = df.duplicated(subset=key_cols).sum()
    if dups:
        return False, f"{dups} filas duplicadas según {key_cols}"
    return True, "OK: sin duplicados"


def check_value_ranges(df: pd.DataFrame, column: str, min_val=0, max_val=None) -> tuple[bool, str]:
    if column not in df.columns:
        return False, f"Columna '{column}' no existe"
    series = df[column].dropna()
    below = (series < min_val).sum()
    above = (series > max_val).sum() if max_val is not None else 0
    if below or above:
        return False, f"'{column}': {below} valores < {min_val}, {above} valores > {max_val}"
    return True, f"OK: '{column}' dentro de rango"


def run_quality_checks(df: pd.DataFrame, required_cols: list[str], key_cols: list[str]) -> bool:
    checks = [
        check_no_empty(df),
        check_required_columns(df, required_cols),
        check_no_duplicate_players(df, key_cols),
    ]
    if "pass_completion_pct" in df.columns:
        checks.append(check_value_ranges(df, "pass_completion_pct", 0, 100))

    all_ok = True
    for ok, msg in checks:
        level = logger.info if ok else logger.error
        level(msg)
        all_ok = all_ok and ok
    return all_ok