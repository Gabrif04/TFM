import sqlite3
import hashlib
import datetime as dt
import pandas as pd

from config import BASE_DIR
from utils.logger import get_logger

logger = get_logger(__name__)

DB_PATH = BASE_DIR / "data" / "atm_scouting.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def make_player_id(name_normalized: str, team: str, season: str) -> str:
    raw = f"{name_normalized}|{team}|{season}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


SCHEMA = """
-- BRONZE
CREATE TABLE IF NOT EXISTS bronze_fbref (
    ingestion_id     TEXT PRIMARY KEY,
    player_name        TEXT,
    team                 TEXT,
    league                 TEXT,
    season                   TEXT,
    payload_json               TEXT,  
    extracted_at                 TEXT
);

CREATE TABLE IF NOT EXISTS bronze_understat (
    ingestion_id     TEXT PRIMARY KEY,
    player_name        TEXT,
    team                 TEXT,
    league                 TEXT,
    season                   TEXT,
    payload_json               TEXT,
    extracted_at                 TEXT
);

CREATE TABLE IF NOT EXISTS bronze_transfermarkt (
    player_name             TEXT PRIMARY KEY,   
    market_value_raw          TEXT,
    contract_until_raw          TEXT,
    transfermarkt_url             TEXT,
    height_raw                       TEXT,
    foot                               TEXT,
    nationality                         TEXT,
    agent                                TEXT,
    full_name                             TEXT,
    extracted_at                            TEXT
);

CREATE TABLE IF NOT EXISTS bronze_transfermarkt_mv_history (
    player_name       TEXT,
    date_raw             TEXT,
    market_value_eur        REAL,
    market_value_raw           TEXT,
    club_at_time                  TEXT,
    age_at_time                      TEXT,
    extracted_at                        TEXT,
    PRIMARY KEY (player_name, date_raw)
);

CREATE TABLE IF NOT EXISTS bronze_football_data_standings (
    ingestion_id     TEXT PRIMARY KEY,
    team_api_id          INTEGER,
    league                  TEXT,
    season                     TEXT,
    payload_json                  TEXT,
    extracted_at                     TEXT
);

CREATE TABLE IF NOT EXISTS bronze_football_data_teams (
    ingestion_id     TEXT PRIMARY KEY,
    team_api_id          INTEGER,
    league                 TEXT,
    payload_json              TEXT,
    extracted_at                TEXT
);

CREATE TABLE IF NOT EXISTS bronze_whoscored (
    ingestion_id     TEXT PRIMARY KEY,
    player_name         TEXT,
    team                    TEXT,
    league                     TEXT,
    season                       TEXT,
    game_id                         TEXT,
    passes_attempted                   REAL,
    passes_completed                      REAL,
    pass_completion_pct                      REAL,
    crosses                                     REAL,
    crosses_completed                              REAL,
    tackles                                           REAL,
    interceptions                                        REAL,
    payload_json                                            TEXT,
    extracted_at                                               TEXT
);

--SILVER:

CREATE TABLE IF NOT EXISTS silver_fbref (
    player_id               TEXT PRIMARY KEY,
    player_name              TEXT NOT NULL,
    player_name_normalized   TEXT NOT NULL,
    team                      TEXT,
    league                    TEXT,
    season                    TEXT,
    position                  TEXT,
    age                        INTEGER,
    minutes_played              INTEGER,
    crosses                       REAL,
    tackles                         REAL,   -- OJO: tackles GANADOS, no el total intentado
    interceptions                     REAL,
    is_outlier                          INTEGER,
    processed_at                          TEXT,
    UNIQUE(player_name_normalized, team, season)
);

CREATE TABLE IF NOT EXISTS silver_understat (
    player_id               TEXT PRIMARY KEY,
    player_name              TEXT NOT NULL,
    player_name_normalized   TEXT NOT NULL,
    team                      TEXT,
    league                    TEXT,
    season                    TEXT,
    position                  TEXT,
    xg                          REAL,
    xa                             REAL,
    npxg                             REAL,
    is_outlier                         INTEGER,
    processed_at                         TEXT,
    UNIQUE(player_name_normalized, team, season)
);

CREATE TABLE IF NOT EXISTS silver_transfermarkt (
    player_name_normalized  TEXT PRIMARY KEY,
    player_name               TEXT NOT NULL,
    market_value_eur            REAL,
    contract_until                 TEXT,
    transfermarkt_url                TEXT,
    height_cm                          REAL,
    foot                                 TEXT,
    nationality                            TEXT,
    agent                                    TEXT,
    full_name                                  TEXT,
    processed_at                                 TEXT
);

CREATE TABLE IF NOT EXISTS silver_transfermarkt_mv_history (
    player_name_normalized  TEXT,
    date                       TEXT,
    market_value_eur             REAL,
    club_at_time                    TEXT,
    age_at_time                        INTEGER,
    processed_at                          TEXT,
    PRIMARY KEY (player_name_normalized, date)
);

CREATE TABLE IF NOT EXISTS silver_standings (
    team_api_id       INTEGER,
    league               TEXT,
    season                  TEXT,
    team_name                  TEXT,
    position                     INTEGER,
    points                          INTEGER,
    won                                INTEGER,
    draw                                  INTEGER,
    lost                                     INTEGER,
    goal_difference                            INTEGER,
    processed_at                                  TEXT,
    PRIMARY KEY (team_api_id, league, season)
);

CREATE TABLE IF NOT EXISTS silver_teams (
    team_api_id       INTEGER,
    league               TEXT,
    team_name              TEXT NOT NULL,
    short_name                TEXT,
    tla                         TEXT,
    founded                       INTEGER,
    venue                           TEXT,
    processed_at                       TEXT,
    PRIMARY KEY (team_api_id, league)
);

CREATE TABLE IF NOT EXISTS silver_transfers (
    transfer_id       TEXT PRIMARY KEY,
    player_name          TEXT,
    player_api_id           INTEGER,
    transfer_date               TEXT,
    team_out                       TEXT,
    team_in                           TEXT,
    transfer_type                        TEXT,
    processed_at                            TEXT
);

CREATE TABLE IF NOT EXISTS silver_injuries (
    injury_id       TEXT PRIMARY KEY,
    team_name          TEXT,
    team_api_id           INTEGER,
    season                   TEXT,
    player_name                 TEXT,
    injury_type                    TEXT,
    injury_date                       TEXT,
    processed_at                         TEXT
);

CREATE TABLE IF NOT EXISTS silver_whoscored (
    event_id                 TEXT PRIMARY KEY,
    player_name               TEXT NOT NULL,
    player_name_normalized     TEXT NOT NULL,
    team                          TEXT,
    league                          TEXT,
    season                            TEXT,
    game_id                             TEXT,
    passes_attempted                       REAL,
    passes_completed                          REAL,
    pass_completion_pct                          REAL,
    crosses                                         REAL,
    crosses_completed                                  REAL,
    tackles                                               REAL,
    interceptions                                            REAL,
    processed_at                                                TEXT,
    UNIQUE(player_name_normalized, team, game_id)
);

CREATE TABLE IF NOT EXISTS bronze_api_football_transfers (
    ingestion_id     TEXT PRIMARY KEY,
    player_name         TEXT,
    player_api_id          INTEGER,
    payload_json               TEXT,   
    extracted_at                 TEXT
);

CREATE TABLE IF NOT EXISTS bronze_api_football_injuries (
    ingestion_id     TEXT PRIMARY KEY,
    team_name           TEXT,
    team_api_id             INTEGER,
    season                     TEXT,
    payload_json                  TEXT,
    extracted_at                    TEXT
);

CREATE INDEX IF NOT EXISTS idx_silver_fbref_league_season ON silver_fbref(league, season);
CREATE INDEX IF NOT EXISTS idx_silver_understat_league_season ON silver_understat(league, season);
CREATE INDEX IF NOT EXISTS idx_silver_standings_league_season ON silver_standings(league, season);
"""


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for col, col_type in columns.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        _ensure_columns(conn, "bronze_transfermarkt", {
            "height_raw": "TEXT", "foot": "TEXT", "nationality": "TEXT",
            "agent": "TEXT", "full_name": "TEXT",
        })
        _ensure_columns(conn, "silver_transfermarkt", {
            "height_cm": "REAL", "foot": "TEXT", "nationality": "TEXT",
            "agent": "TEXT", "full_name": "TEXT",
        })
        _ensure_columns(conn, "silver_understat", {
            "goals": "REAL", "assists": "REAL", "shots": "REAL", "key_passes": "REAL",
            "yellow_cards": "REAL", "red_cards": "REAL", "xg_chain": "REAL", "xg_buildup": "REAL"
        })
        conn.commit()
        logger.info(f"Base de datos (bronze/silver) lista en {DB_PATH}")
    finally:
        conn.close()

#Función auxiliar para llamar si hace falta modificar alguna tabla
def upsert_dataframe(df: pd.DataFrame, table: str) -> None:
    if df.empty:
        logger.warning(f"DataFrame vacío, no se escribe nada en '{table}'")
        return

    conn = get_connection()
    try:
        cols = list(df.columns)
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        sql = f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})"
        df_obj = df.astype(object)
        records = df_obj.where(pd.notnull(df_obj), None).values.tolist()
        conn.executemany(sql, records)
        conn.commit()
        logger.info(f"{len(df)} filas insertadas/actualizadas en '{table}'")
    except sqlite3.Error as e:
        logger.error(f"Error escribiendo en '{table}': {e}")
        conn.rollback()
    finally:
        conn.close()


def read_table(table: str, where: str | None = None) -> pd.DataFrame:
    conn = get_connection()
    try:
        query = f"SELECT * FROM {table}"
        if where:
            query += f" WHERE {where}"
        return pd.read_sql_query(query, conn)
    finally:
        conn.close()


def write_bronze(df: pd.DataFrame, table: str, id_cols: list[str]) -> None:
    df = df.copy()
    df["ingestion_id"] = df[id_cols].astype(str).agg("|".join, axis=1).apply(
        lambda s: hashlib.md5(s.encode()).hexdigest()[:16]
    )
    df["extracted_at"] = dt.datetime.now().isoformat()
    df["payload_json"] = df.drop(columns=["ingestion_id", "extracted_at"]).to_json(orient="records", lines=True).splitlines()
    conn = get_connection()
    try:
        table_cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()
    extra_cols = [
        c for c in table_cols
        if c in df.columns and c not in id_cols and c not in ("ingestion_id", "payload_json", "extracted_at")
    ]
    keep_cols = ["ingestion_id"] + id_cols + extra_cols + ["payload_json", "extracted_at"]
    upsert_dataframe(df[keep_cols], table)

    