"""
Capa gold: une las tablas silver en un dataset "un jugador = una fila"
listo para los modelos de scouting (ranking + potencial de valor de mercado).


silver_transfermarkt no tiene columna `season`: es un snapshot del valor de
mercado ACTUAL. silver_fbref, en cambio, cubre 10 temporadas (2016-17 en
adelante). Cruzar ambas sin filtrar significaría explicar el valor de 2026
con estadísticas de 2016, y además repetiría al mismo jugador hasta 10 veces
con un target idéntico (fuga de información entre folds de validación).

Por eso `build_gold_scouting` filtra por UNA temporada, por defecto la más
reciente, que es la única que se alinea con el snapshot de valor.
Para aprovechar el histórico haría falta poblar
silver_transfermarkt_mv_history (hoy: 25 filas de un solo jugador) y montar
filas jugador-temporada con el valor de cada momento.
"""
import re
import unicodedata

import pandas as pd

from utils.database import get_connection
from utils.logger import get_logger

logger = get_logger(__name__)

# fbref usa códigos en inglés (a veces combinados, p.ej. "MF,FW"),
# transfermarkt/otras fuentes ya vienen en español -> normalizamos a un
# único vocabulario reducido para poder agrupar por posición.
_POSITION_MAP = {
    "GK": "Portero", "DF": "Defensa", "MF": "Centrocampista", "FW": "Delantero",
    "PORTERO": "Portero", "DEFENSA": "Defensa",
    "CENTROCAMPISTA": "Centrocampista", "DELANTERO": "Delantero",
}

# Estadísticas de conteo que se pasan a per-90 para ser comparables entre
# jugadores con distinta carga de minutos.
COUNTING_STATS = [
    "goals", "assists", "goals_np", "crosses", "tackles", "interceptions",
    "yellow_cards", "fouls_committed", "fouls_drawn", "offsides",
]


def normalize_position(raw: str) -> str:
    """Se queda con la primera posición cuando vienen varias separadas
    por coma (p.ej. "MF,DF" -> "Centrocampista"). Desconocido -> 'Otro'."""
    if not isinstance(raw, str) or not raw.strip():
        return "Otro"
    first = raw.split(",")[0].strip().upper()
    return _POSITION_MAP.get(first, "Otro")


def _per90(df: pd.DataFrame, cols: list[str], minutes_col: str = "minutes_played") -> pd.DataFrame:
    df = df.copy()
    minutes = df[minutes_col].replace(0, pd.NA)
    for c in cols:
        if c in df.columns:
            df[f"{c}_p90"] = (df[c] / minutes * 90).astype(float)
    return df


def _contract_years_left(contract_until: pd.Series, season: str) -> pd.Series:
    """Años que restan de contrato al final de la temporada analizada.
    Es uno de los factores que más pesa en el valor de mercado real: a menos
    contrato, menos poder de negociación del club vendedor."""
    ref = pd.Timestamp(f"{season.split('-')[1]}-06-30")
    until = pd.to_datetime(contract_until, errors="coerce")
    return ((until - ref).dt.days / 365.25).clip(lower=0)


# fbref usa nombres cortos ('Barcelona') y football-data los oficiales
# ('FC Barcelona'), así que el join directo por nombre solo casaba 121 filas
# de 2.839. Se resuelve por solapamiento de tokens, ignorando las partes
# genéricas del nombre; los casos que el solapamiento no cubre (abreviaturas
# y apodos) van en el diccionario de alias.
_TEAM_STOPWORDS = {
    "fc", "cf", "ca", "rc", "rcd", "ud", "sd", "cd", "club", "de", "ac", "as",
    "ss", "ssc", "afc", "sc", "bc", "us", "ogc", "losc", "sco", "fk", "vfl",
    "vfb", "tsg", "sv", "bsc", "borussia", "deportivo", "real",
}
_TEAM_ALIASES = {
    "wolves": "wolverhampton",
    "brest": "brestois",
    "lyon": "lyonnais",
    "psg": "paris saint germain",
    "rennes": "rennais",
    "gladbach": "monchengladbach",
    "inter": "internazionale",
}


def _team_tokens(name: str) -> set[str]:
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    text = _TEAM_ALIASES.get(text.strip(), text)
    return {t for t in re.split(r"[^a-z0-9]+", text) if t and t not in _TEAM_STOPWORDS}


def _match_team(team: str, candidates: pd.Series, threshold: float = 0.5) -> str | None:
    tokens = _team_tokens(team)
    best, best_score = None, 0.0
    for candidate in candidates:
        other = _team_tokens(candidate)
        if not tokens or not other:
            continue
        score = len(tokens & other) / min(len(tokens), len(other))
        if score > best_score:
            best, best_score = candidate, score
    return best if best_score >= threshold else None


def build_gold_scouting(season: str = "2025-2026", conn=None) -> pd.DataFrame:
    """Devuelve el dataset gold: una fila por jugador con stats + valor de
    mercado, listo para entrenar/rankear. `market_value_eur` puede venir
    NaN para jugadores sin match en Transfermarkt (se filtran para el
    entrenamiento, pero se conservan aquí para poder rankearlos igualmente).
    """
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        fbref = pd.read_sql(
            "SELECT * FROM silver_fbref WHERE season = ?", conn, params=(season,)
        )
        understat = pd.read_sql(
            "SELECT * FROM silver_understat WHERE season = ?", conn, params=(season,)
        )
        transfermarkt = pd.read_sql("SELECT * FROM silver_transfermarkt", conn)
        standings = pd.read_sql(
            "SELECT * FROM silver_standings WHERE season = ?", conn, params=(season,)
        )
    finally:
        if own_conn:
            conn.close()

    if fbref.empty:
        logger.warning("build_gold_scouting: silver_fbref vacío para season=%s", season)
        return pd.DataFrame()

    df = _per90(fbref, COUNTING_STATS)

    # xg/xa/npxg no traen minutos propios: se pasan a per-90 con los
    # minutos de fbref, que es la fuente de referencia del dataset.
    understat_cols = ["xg", "xa", "npxg"]
    if not understat.empty:
        keep = ["player_name_normalized"] + understat_cols
        df = df.merge(
            understat[[c for c in keep if c in understat.columns]].drop_duplicates(
                "player_name_normalized"
            ),
            on="player_name_normalized", how="left",
        )
        df = _per90(df, understat_cols)

    tm_cols = ["player_name_normalized", "market_value_eur", "height_cm", "foot",
               "nationality", "contract_until"]
    df = df.merge(
        transfermarkt[[c for c in tm_cols if c in transfermarkt.columns]].drop_duplicates(
            "player_name_normalized"
        ),
        on="player_name_normalized", how="left",
    )

    # Fuerza del equipo: un jugador del campeón vale más que uno con
    # estadísticas idénticas en un equipo de descenso.
    if not standings.empty:
        st = standings[["team_name", "league", "position", "points"]].rename(
            columns={"position": "team_position", "points": "team_points"}
        )
        pairs = df[["team", "league"]].drop_duplicates()
        pairs["team_name"] = [
            _match_team(t, st.loc[st["league"] == lg, "team_name"])
            for t, lg in zip(pairs["team"], pairs["league"])
        ]
        unmatched = pairs["team_name"].isna().sum()
        if unmatched:
            logger.warning(
                "Sin equivalencia en silver_standings: %d equipos de %d (%s)",
                unmatched, len(pairs),
                ", ".join(pairs.loc[pairs["team_name"].isna(), "team"].head(8)),
            )
        df = df.merge(pairs, on=["team", "league"], how="left").merge(
            st, on=["team_name", "league"], how="left"
        ).drop(columns=["team_name"])

    df["position_group"] = df["position"].apply(normalize_position)
    df["contract_years_left"] = _contract_years_left(df.get("contract_until"), season)
    df["starts_ratio"] = (df["starts"] / df["matches_played"].replace(0, pd.NA)).astype(float)
    df["has_market_value"] = df["market_value_eur"].notna()

    keep = [
        "player_id", "player_name", "player_name_normalized", "team", "league", "season",
        "position_group", "age", "minutes_played", "matches_played", "starts", "starts_ratio",
        *[f"{c}_p90" for c in COUNTING_STATS],
        "xg", "xa", "npxg", "xg_p90", "xa_p90", "npxg_p90",
        "penalties_scored", "penalties_attempted",
        "team_position", "team_points",
        "height_cm", "foot", "nationality", "contract_until", "contract_years_left",
        "market_value_eur", "has_market_value",
    ]
    df = df[[c for c in keep if c in df.columns]]
    logger.info(
        "build_gold_scouting %s: %d jugadores (%d con valor de mercado)",
        season, len(df), int(df["has_market_value"].sum()),
    )
    return df


if __name__ == "__main__":
    gold = build_gold_scouting()
    print(gold.shape)
    print(gold.head())
