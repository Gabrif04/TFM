import time
import requests
import pandas as pd

from config import FOOTBALL_DATA_API_KEY, LEAGUES, REQUEST_TIMEOUT
from utils.database import init_db, write_bronze
from utils.logger import get_logger

logger = get_logger(__name__)
BASE_URL = "https://api.football-data.org/v4"

COMPETITION_CODES = {
    "ESP": "PD", "ENG": "PL", "ITA": "SA",
    "GER": "BL1", "FRA": "FL1", "POR": "PPL", "NED": "DED",
}

def _get(endpoint: str, params: dict | None = None) -> dict:
    headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
    url = f"{BASE_URL}/{endpoint}"
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error al llamar a {url}: {e}")
        return {}


def get_teams_by_league(league_code: str) -> pd.DataFrame:
    comp_code = COMPETITION_CODES.get(league_code)
    if not comp_code:
        logger.warning(f"Liga desconocida: {league_code}")
        return pd.DataFrame()

    data = _get(f"competitions/{comp_code}/teams")
    teams = data.get("teams", [])
    if not teams:
        logger.warning(f"Sin datos de equipos para {league_code}")
        return pd.DataFrame()

    df = pd.json_normalize(teams)
    df["league"] = league_code
    logger.info(f"Extraídos {len(df)} equipos de {league_code}")
    return df

#Equipos de todas las ligas definidas
def get_all_leagues_teams(league_codes: list[str] | None = None) -> pd.DataFrame:

    init_db()
    league_codes = league_codes or list(LEAGUES.keys())
    frames = []
    for code in league_codes:
        df = get_teams_by_league(code)
        if not df.empty:
            frames.append(df)
        time.sleep(6.5)  #NO TOCAR!!!!

    if not frames:
        logger.warning("get_all_leagues_teams: no se extrajo ningún equipo, no se escribe en bronze")
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)

    #id y name vienen directos de la API de football-data.org (id único de equipo)
    bronze_df = result.rename(columns={"id": "team_api_id", "name": "team_name"})
    write_bronze(
        bronze_df,
        table="bronze_football_data_teams",
        id_cols=["team_api_id", "league"],
    )

    return result

#Clasificaciones de liga
def get_standings(league_code: str, season: str | None = None) -> pd.DataFrame:
    comp_code = COMPETITION_CODES.get(league_code)
    if not comp_code:
        logger.warning(f"Liga desconocida: {league_code}")
        return pd.DataFrame()

    params = {"season": season.split("-")[0]} if season else None
    data = _get(f"competitions/{comp_code}/standings", params=params)
    tables = data.get("standings", [])
    # Puede haber varias tablas (TOTAL/HOME/AWAY); nos quedamos con TOTAL.
    total_table = next((t for t in tables if t.get("type") == "TOTAL"), tables[0] if tables else None)
    if not total_table:
        logger.warning(f"Sin standings para {league_code}")
        return pd.DataFrame()

    rows = []
    for row in total_table.get("table", []):
        team = row.get("team", {})
        rows.append({
            "team_api_id": team.get("id"),
            "team_name": team.get("name"),
            "league": league_code,
            "season": season or "",
            "position": row.get("position"),
            "points": row.get("points"),
            "won": row.get("won"),
            "draw": row.get("draw"),
            "lost": row.get("lost"),
            "goal_difference": row.get("goalDifference"),
        })
    df = pd.DataFrame(rows)
    logger.info(f"Standings: {len(df)} equipos extraídos de {league_code}")
    return df

def get_all_leagues_standings(league_codes: list[str] | None = None, season: str | None = None) -> pd.DataFrame:
    """Itera sobre varias ligas respetando el rate limit gratuito (10 req/min)
    y persiste el resultado crudo en bronze_football_data_standings."""
    init_db()
    league_codes = league_codes or list(LEAGUES.keys())
    frames = []
    for code in league_codes:
        df = get_standings(code, season=season)
        if not df.empty:
            frames.append(df)
        time.sleep(6.5)  # NO TOCAR!!!!

    if not frames:
        logger.warning("get_all_leagues_standings: no se extrajo ninguna clasificación, no se escribe en bronze")
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    write_bronze(result, table="bronze_football_data_standings", id_cols=["team_api_id", "league", "season"])
    return result


if __name__ == "__main__":
    df = get_all_leagues_teams()
    print(df.head())