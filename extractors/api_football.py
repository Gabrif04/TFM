#Sólo permite 100 peticiones por día, no repetir llamadas y usar con cuidado
import time
import requests
import pandas as pd
from rapidfuzz import fuzz

from config import API_FOOTBALL_KEY, REQUEST_TIMEOUT
from utils.database import init_db, write_bronze, read_table
from utils.logger import get_logger

logger = get_logger(__name__)

BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_FOOTBALL_KEY}
MIN_DELAY_SECONDS = 1.5  #NO TOCAR!!!!!!


def _get(endpoint: str, params: dict) -> dict:
    try:
        resp = requests.get(f"{BASE_URL}/{endpoint}", headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        remaining = resp.headers.get("x-ratelimit-requests-remaining")
        if remaining is not None:
            logger.info(f"Peticiones restantes = {remaining}") #Control para no pasarse de petis
            if int(remaining) < 5:
                logger.warning("PARAR PORQUE QUEDAN MENOS DE 5 PETICIONES A API-FOOTBALL")
        return data
    except requests.exceptions.RequestException as e:
        logger.error(f"Error, endpoint {endpoint}: {e}")
        return {}
    finally:
        time.sleep(MIN_DELAY_SECONDS)

#Busco el id de un jugador por nombre, luego será necesario para la la llamada a transfers
def search_player_id(player_name: str) -> int | None:
    data = _get("players/profiles", {"search": player_name})
    results = data.get("response", [])
    if not results:
        logger.warning(f"API-Football: sin resultados para '{player_name}'")
        return None
    return results[0]["player"]["id"]

#Histórico de traspasos de un jugador buscando por player id (lo que comentaba en la función de arriba)
def get_player_transfers(player_name: str, player_api_id: int | None = None) -> dict:
    player_api_id = player_api_id or search_player_id(player_name)
    if not player_api_id:
        return {}

    data = _get("transfers", {"player": player_api_id})
    transfers = data.get("response", [])
    if not transfers:
        logger.info(f"No hay fichajes pasados para '{player_name}'")
        return {}

    return {
        "player_name": player_name,
        "player_api_id": player_api_id,
        "payload": transfers,
    }

#Busqueda del id de un equipo por el nombre que luego se usarán para las lesiones.
def search_team_id(team_name: str, alt_names: list[str] | None = None) -> int | None:
    for query in [team_name] + [n for n in (alt_names or []) if n]:
        data = _get("teams", {"search": query})
        results = data.get("response", [])
        if not results:
            continue
        best = max(results, key=lambda r: fuzz.token_sort_ratio(query.lower(), r["team"]["name"].lower()))
        return best["team"]["id"]
    logger.warning(f"No hay resultados para '{team_name}'")
    return None

#Lesiones de un equipo en una temporada
def get_team_injuries(team_api_id: int, team_name: str, season: str) -> dict:
    season_year = season.split("-")[0]  # API-Football espera el año de inicio, p.ej. "2025"
    data = _get("injuries", {"team": team_api_id, "season": season_year})
    injuries = data.get("response", [])
    if not injuries:
        logger.info(f"No hay lesiones registradas para team_id={team_api_id}, {season}")
        return {}

    return {
        "team_name": team_name,
        "team_api_id": team_api_id,
        "season": season,
        "payload": injuries,
    }

#Fichajes
def extract_transfers_for_players(player_names: list[str], force_refresh: bool = False) -> pd.DataFrame:
    init_db()
    #Cacheo para mantener la info en memoria y no realizar llamadas repetidas
    cached = read_table("bronze_api_football_transfers") if not force_refresh else pd.DataFrame(columns=["player_name"])
    already_cached = set(cached["player_name"]) if not cached.empty else set()
    pending = [n for n in player_names if n not in already_cached]

    logger.info(f"Fichajes: {len(pending)} pendientes, {len(already_cached)} ya en bronze")

    rows = []
    for name in pending:
        result = get_player_transfers(name)
        if result:
            rows.append(result)

    if rows:
        df = pd.DataFrame(rows)
        write_bronze(df[["player_name", "player_api_id", "payload"]], "bronze_api_football_transfers",
                     id_cols=["player_name", "player_api_id"])

    return read_table("bronze_api_football_transfers")

#Ingesta de lesiones de un equipo en una temporada
def extract_injuries_for_teams(teams: list[tuple[str, str | None]], season: str, force_refresh: bool = False) -> pd.DataFrame:
    init_db()
    cached = read_table("bronze_api_football_injuries") if not force_refresh else pd.DataFrame(columns=["team_name", "season"])
    already_cached = set(zip(cached.get("team_name", []), cached.get("season", [])))

    rows = []
    for team_name, short_name in teams:
        if (team_name, season) in already_cached:
            continue
        team_api_id = search_team_id(team_name, alt_names=[short_name] if short_name else None)
        if not team_api_id:
            continue
        result = get_team_injuries(team_api_id, team_name, season)
        if result:
            rows.append(result)

    if rows:
        df = pd.DataFrame(rows)
        write_bronze(df[["team_name", "team_api_id", "season", "payload"]],
                     "bronze_api_football_injuries", id_cols=["team_name", "team_api_id", "season"])

    return read_table("bronze_api_football_injuries")


if __name__ == "__main__":
    df = extract_transfers_for_players(["Julián Álvarez", "Antoine Griezmann"])
    print(df[["player_name", "player_api_id"]] if not df.empty else "sin resultados")