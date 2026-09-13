"""
Capa silver: una función build_silver_X por fuente bronze, limpia y tipa
pero SIN fusionar entre fuentes (la fusión "un jugador = una fila" queda
para la futura capa gold, ver estado_actual.md).
"""
import hashlib
import json
import pandas as pd

from transform.cleaning import (
    clean_players_dataframe, normalize_name, normalize_league, parse_market_value,
    parse_contract_date, coerce_numeric_columns, parse_height_cm,
)
from utils.database import make_player_id
from utils.logger import get_logger

logger = get_logger(__name__)

#FBref
# El payload de bronze trae 43 campos; aquí se conservan los que tienen valor
# para el modelo (goles, asistencias, titularidades, tarjetas, faltas...).
# Los nombres largos de fbref se renombran a snake_case del proyecto.
FBREF_RENAME = {
    "Playing Time_MP": "matches_played",
    "Playing Time_Starts": "starts",
    "Performance_Gls": "goals",
    "Performance_Ast": "assists",
    "Performance_G-PK": "goals_np",
    "Performance_PK": "penalties_scored",
    "Performance_PKatt": "penalties_attempted",
    "Performance_CrdY": "yellow_cards",
    "Performance_CrdR": "red_cards",
    "Performance_misc_Fls": "fouls_committed",
    "Performance_misc_Fld": "fouls_drawn",
    "Performance_misc_Off": "offsides",
}
FBREF_NUMERIC_COLS = [
    "minutes_played", "crosses", "tackles", "interceptions",
    "matches_played", "starts", "goals", "assists", "goals_np",
    "penalties_scored", "penalties_attempted", "yellow_cards", "red_cards",
    "fouls_committed", "fouls_drawn", "offsides",
]
FBREF_REQUIRED_COLS = ["player_name", "team", "league", "season", "position"]
FBREF_KEY_COLS = ["player_name_normalized", "team", "season"]


def build_silver_fbref(fbref_raw: pd.DataFrame) -> pd.DataFrame:
    if fbref_raw.empty:
        return pd.DataFrame()
    fbref_raw = fbref_raw.rename(columns=FBREF_RENAME)
    df = clean_players_dataframe(fbref_raw, FBREF_NUMERIC_COLS)
    df["league"] = df["league"].apply(normalize_league)
    df["player_id"] = df.apply(
        lambda r: make_player_id(r["player_name_normalized"], r["team"], r["season"]), axis=1
    )
    df["is_outlier"] = df["is_outlier"].astype(int)
    df["processed_at"] = pd.Timestamp.now().isoformat()
    cols = [
        "player_id", "player_name", "player_name_normalized", "team", "league", "season",
        "position", "age", "minutes_played", "crosses", "tackles", "interceptions",
        *[c for c in FBREF_RENAME.values()],
        "is_outlier", "processed_at",
    ]
    return df[[c for c in cols if c in df.columns]]


#Understat
UNDERSTAT_NUMERIC_COLS = ["xg", "xa", "npxg", "goals", "assists", "shots", "key_passes", "yellow_cards", "red_cards", "xg_chain", "xg_buildup"]
UNDERSTAT_REQUIRED_COLS = ["player_name", "team", "league", "season"]
UNDERSTAT_KEY_COLS = ["player_name_normalized", "team", "season"]


def build_silver_understat(understat_raw: pd.DataFrame) -> pd.DataFrame:
    if understat_raw.empty:
        return pd.DataFrame()
    df = clean_players_dataframe(understat_raw, UNDERSTAT_NUMERIC_COLS)
    df["league"] = df["league"].apply(normalize_league)
    df["player_id"] = df.apply(
        lambda r: make_player_id(r["player_name_normalized"], r["team"], r["season"]), axis=1
    )
    df["is_outlier"] = df["is_outlier"].astype(int)
    df["processed_at"] = pd.Timestamp.now().isoformat()
    cols = [
        "player_id", "player_name", "player_name_normalized", "team", "league", "season",
        "position", "xg", "xa", "npxg", "goals", "assists", "shots", "key_passes",
        "yellow_cards", "red_cards", "xg_chain", "xg_buildup", "is_outlier", "processed_at",
    ]
    return df[[c for c in cols if c in df.columns]]


#Transfermarkt
def build_silver_transfermarkt(transfermarkt_raw: pd.DataFrame) -> pd.DataFrame:
    if transfermarkt_raw.empty:
        return pd.DataFrame()
    df = transfermarkt_raw.copy()
    df["player_name_normalized"] = df["player_name"].apply(normalize_name)
    df["market_value_eur"] = df["market_value_raw"].apply(parse_market_value)
    df["contract_until"] = df["contract_until_raw"].apply(parse_contract_date).astype(str)
    if "height_raw" in df.columns:
        df["height_cm"] = df["height_raw"].apply(parse_height_cm)
    df["processed_at"] = pd.Timestamp.now().isoformat()
    df = df.drop_duplicates(subset=["player_name_normalized"], keep="last")
    cols = [
        "player_name_normalized", "player_name", "market_value_eur", "contract_until",
        "transfermarkt_url", "height_cm", "foot", "nationality", "agent", "full_name", "processed_at",
    ]
    return df[[c for c in cols if c in df.columns]]


def build_silver_transfermarkt_mv_history(bronze_mv_history_df: pd.DataFrame) -> pd.DataFrame:
    """bronze_mv_history_df = salida de
    extractors.transfermarkt_extractor.get_market_value_history_with_cache
    (una fila por punto del histórico). ⚠️ Sin verificar contra un pipeline
    completo todavía (endpoint confirmado en vivo el 25/07/2026, pero solo
    con 1-2 jugadores de prueba)."""
    if bronze_mv_history_df.empty:
        return pd.DataFrame()
    df = bronze_mv_history_df.copy()
    df["player_name_normalized"] = df["player_name"].apply(normalize_name)
    # date_raw viene como 'DD/MM/YYYY', mismo formato que ya soporta parse_contract_date.
    df["date"] = df["date_raw"].apply(parse_contract_date).astype(str)
    df["market_value_eur"] = pd.to_numeric(df["market_value_eur"], errors="coerce")
    df["age_at_time"] = pd.to_numeric(df["age_at_time"], errors="coerce")
    df["processed_at"] = pd.Timestamp.now().isoformat()
    df = df.drop_duplicates(subset=["player_name_normalized", "date"], keep="last")
    cols = ["player_name_normalized", "date", "market_value_eur", "club_at_time", "age_at_time", "processed_at"]
    return df[[c for c in cols if c in df.columns]]


#football-data.org (equipos)
def build_silver_teams(teams_raw: pd.DataFrame) -> pd.DataFrame:
    if teams_raw.empty:
        return pd.DataFrame()
    df = teams_raw.rename(columns={"id": "team_api_id", "name": "team_name", "shortName": "short_name"})
    df["league"] = df["league"].apply(normalize_league)
    if "founded" in df.columns:
        df["founded"] = pd.to_numeric(df["founded"], errors="coerce")
    df["processed_at"] = pd.Timestamp.now().isoformat()
    cols = ["team_api_id", "league", "team_name", "short_name", "tla", "founded", "venue", "processed_at"]
    df = df[[c for c in cols if c in df.columns]]
    return df.drop_duplicates(subset=["team_api_id", "league"], keep="last")


#API-Football: transfers / injuries
def build_silver_transfers(bronze_transfers_df: pd.DataFrame) -> pd.DataFrame:
    if bronze_transfers_df.empty:
        return pd.DataFrame()
    rows = []
    for _, row in bronze_transfers_df.iterrows():
        try:
            parsed = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            logger.warning("silver_transfers: payload_json ilegible, fila descartada")
            continue
        for player_record in parsed.get("payload", []):
            for t in player_record.get("transfers", []):
                teams = t.get("teams", {})
                transfer_date = t.get("date")
                raw_key = f"{parsed.get('player_api_id')}|{transfer_date}|{(teams.get('in') or {}).get('id')}"
                rows.append({
                    "transfer_id": hashlib.md5(raw_key.encode()).hexdigest()[:16],
                    "player_name": parsed.get("player_name"),
                    "player_api_id": parsed.get("player_api_id"),
                    "transfer_date": transfer_date,
                    "team_out": (teams.get("out") or {}).get("name"),
                    "team_in": (teams.get("in") or {}).get("name"),
                    "transfer_type": t.get("type"),
                })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["processed_at"] = pd.Timestamp.now().isoformat()
    return df


def build_silver_injuries(bronze_injuries_df: pd.DataFrame) -> pd.DataFrame:
    if bronze_injuries_df.empty:
        return pd.DataFrame()
    rows = []
    for _, row in bronze_injuries_df.iterrows():
        try:
            parsed = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            logger.warning("silver_injuries: payload_json ilegible, fila descartada")
            continue
        for record in parsed.get("payload", []):
            player = record.get("player", {}) or {}
            fixture = record.get("fixture", {}) or {}
            raw_key = f"{parsed.get('team_api_id')}|{player.get('id')}|{fixture.get('id')}"
            rows.append({
                "injury_id": hashlib.md5(raw_key.encode()).hexdigest()[:16],
                "team_name": parsed.get("team_name"),
                "team_api_id": parsed.get("team_api_id"),
                "season": parsed.get("season"),
                "player_name": player.get("name"),
                "injury_type": player.get("type"),
                "injury_date": fixture.get("date"),
            })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["processed_at"] = pd.Timestamp.now().isoformat()
    return df


#WhoScored
WHOSCORED_NUMERIC_COLS = [
    "passes_attempted", "passes_completed", "pass_completion_pct",
    "crosses", "crosses_completed", "tackles", "interceptions",
]


def build_silver_whoscored(whoscored_raw: pd.DataFrame) -> pd.DataFrame:
    if whoscored_raw.empty:
        return pd.DataFrame()
    df = whoscored_raw.copy()
    df["player_name_normalized"] = df["player_name"].apply(normalize_name)
    df["league"] = df["league"].apply(normalize_league)
    df = coerce_numeric_columns(df, WHOSCORED_NUMERIC_COLS)
    df["event_id"] = df.apply(
        lambda r: hashlib.md5(
            f"{r['player_name_normalized']}|{r['team']}|{r['game_id']}".encode()
        ).hexdigest()[:16],
        axis=1,
    )
    df["processed_at"] = pd.Timestamp.now().isoformat()
    cols = [
        "event_id", "player_name", "player_name_normalized", "team", "league", "season", "game_id",
        "passes_attempted", "passes_completed", "pass_completion_pct", "crosses", "crosses_completed",
        "tackles", "interceptions", "processed_at",
    ]
    return df[[c for c in cols if c in df.columns]]


#football-data.org (clasificación)
STANDINGS_REQUIRED_COLS = ["team_name", "league", "season"]
STANDINGS_KEY_COLS = ["team_api_id", "league", "season"]


def build_silver_standings(standings_raw: pd.DataFrame) -> pd.DataFrame:
    if standings_raw.empty:
        return pd.DataFrame()
    df = standings_raw.copy()
    df["league"] = df["league"].apply(normalize_league)
    for col in ["position", "points", "won", "draw", "lost", "goal_difference"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["processed_at"] = pd.Timestamp.now().isoformat()
    cols = [
        "team_api_id", "league", "season", "team_name", "position", "points",
        "won", "draw", "lost", "goal_difference", "processed_at",
    ]
    df = df[[c for c in cols if c in df.columns]]
    return df.drop_duplicates(subset=["team_api_id", "league", "season"], keep="last")
