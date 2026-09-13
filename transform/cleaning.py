import re
import unicodedata
import numpy as np
import pandas as pd
from datetime import datetime

from utils.logger import get_logger

logger = get_logger(__name__)

POSITION_MAP = {
    "GK": "Portero", "DF": "Defensa", "MF": "Centrocampista", "FW": "Delantero",
    "DFMF": "Defensa/Centrocampista", "MFFW": "Centrocampista/Delantero",
    "MF,FW": "Centrocampista/Delantero", "FW,MF": "Delantero/Centrocampista",
    "DF,MF": "Defensa/Centrocampista", "MF,DF": "Centrocampista/Defensa",
    "DF,FW": "Defensa/Delantero", "FW,DF": "Delantero/Defensa"
}


def normalize_league(raw: str) -> str:
    """Unifica el código de liga a las claves cortas de config.LEAGUES.

    soccerdata devuelve nombres largos ('ESP-La Liga') y los extractores de
    fbref/understat ya los sobreescriben con el código corto ('ESP'), pero
    whoscored agrupa por la columna nativa y conserva el largo. Sin esto,
    un join o un filtro por `league` entre fuentes no casa.
    """
    if not isinstance(raw, str) or not raw.strip():
        return ""
    code = raw.strip().split("-")[0].strip().upper()
    return code


def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"\s+", " ", name).strip().lower()
    return name


def parse_market_value(raw: str) -> float:
    if not isinstance(raw, str):
        return np.nan
    raw = raw.replace("€", "").strip()
    multiplier = 1
    if raw.lower().endswith("m"):
        multiplier = 1_000_000
        raw = raw[:-1]
    elif raw.lower().endswith("k"):
        multiplier = 1_000
        raw = raw[:-1]
    try:
        return float(raw) * multiplier
    except ValueError:
        return np.nan

#Nos quedamos con los años de edad, ignorando los días que da FBref
def parse_fbref_age(raw) -> float:
    if pd.isna(raw):
        return np.nan
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(str(raw).split("-")[0])
    except ValueError:
        return np.nan

#Convertimos a cm
def parse_height_cm(raw: str) -> float:
    if not isinstance(raw, str):
        return np.nan
    try:
        meters = float(raw.replace("m", "").replace(",", ".").strip())
        return round(meters * 100)
    except ValueError:
        return np.nan


def coerce_numeric_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    df = df.copy()
    for col in columns:
        if col not in df.columns:
            continue
        before_na = df[col].isna().sum()
        df[col] = pd.to_numeric(df[col], errors="coerce")
        after_na = df[col].isna().sum()
        if after_na > before_na:
            logger.warning(
                f"Columna '{col}': {after_na - before_na} valores no numéricos convertidos a NaN"
            )
    return df


def handle_missing_values(df: pd.DataFrame, numeric_cols: list[str]) -> pd.DataFrame:

    df = df.copy()
    volume_cols = [c for c in numeric_cols if not c.endswith("_pct")]
    played = df["minutes_played"].fillna(0) > 0 if "minutes_played" in df.columns else True
    for col in volume_cols:
        if col in df.columns:
            df.loc[played & df[col].isna(), col] = 0
    return df


def remove_outliers_iqr(df: pd.DataFrame, columns: list[str], factor: float = 3.0) -> pd.DataFrame:

    df = df.copy()
    df["is_outlier"] = False
    for col in columns:
        if col not in df.columns:
            continue
        q1, q3 = df[col].quantile([0.25, 0.75])
        iqr = q3 - q1
        lower, upper = q1 - factor * iqr, q3 + factor * iqr
        mask = (df[col] < lower) | (df[col] > upper)
        n_outliers = mask.sum()
        if n_outliers:
            logger.info(f"{n_outliers} outliers detectados en '{col}' (no eliminados, solo marcados)")
        df["is_outlier"] = df["is_outlier"] | mask
    return df


def clean_players_dataframe(df: pd.DataFrame, numeric_cols: list[str]) -> pd.DataFrame:

    df = df.copy()
    if "player_name" in df.columns:
        df["player_name_normalized"] = df["player_name"].apply(normalize_name)
    if "position" in df.columns:
        df["position"] = df["position"].map(POSITION_MAP).fillna(df["position"])
    if "age" in df.columns:
        df["age"] = df["age"].apply(parse_fbref_age)
    df = coerce_numeric_columns(df, numeric_cols)
    df = handle_missing_values(df, numeric_cols)
    df = remove_outliers_iqr(df, numeric_cols)
    df = df.drop_duplicates(subset=["player_name_normalized", "team", "season"], keep="last")
    return df

def parse_contract_date(raw: str) -> pd.Timestamp:

    if not isinstance(raw, str) or not raw.strip():
        return pd.NaT
    for fmt in ("%b %d, %Y", "%d.%m.%Y", "%d/%m/%Y"):  # Transfermarkt usa distintos formatos según el idioma/región
        try:
            return pd.Timestamp(datetime.strptime(raw.strip(), fmt))
        except ValueError:
            continue
    logger.warning(f"No se pudo parsear fecha de contrato: '{raw}'")
    return pd.NaT