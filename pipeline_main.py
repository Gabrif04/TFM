#Orquestrador
import argparse
import pandas as pd

from config import LEAGUES, DEFAULT_SEASON, historical_seasons
from extractors.soccerdata_extractor import extract_all
from extractors.football_data_api import get_all_leagues_teams, get_all_leagues_standings
from extractors.transfermarkt_extractor import get_market_values_with_cache, get_market_value_history_with_cache
from extractors.whoscored_extractor import extract_whoscored
from extractors.api_football import extract_transfers_for_players, extract_injuries_for_teams
from transform.silver import (
    build_silver_fbref, build_silver_understat, build_silver_transfermarkt,
    build_silver_teams, build_silver_whoscored, build_silver_transfers, build_silver_injuries,
    build_silver_standings, build_silver_transfermarkt_mv_history,
    FBREF_REQUIRED_COLS, FBREF_KEY_COLS, UNDERSTAT_REQUIRED_COLS, UNDERSTAT_KEY_COLS,
)
from utils.validators import run_quality_checks
from utils.logger import get_logger
from utils.database import init_db, upsert_dataframe, read_table, DB_PATH

logger = get_logger("pipeline_main")


def run_pipeline(
    league_codes: list[str], season: str | list[str], top_n_by_minutes: int | None = None,
    whoscored_max_matches: int | None = None,
) -> dict[str, pd.DataFrame]:
    seasons_list = [season] if isinstance(season, str) else list(season)
    logger.info(f"Iniciando pipeline para ligas={league_codes}, temporadas={seasons_list}")
    init_db()
    results: dict[str, pd.DataFrame] = {}

    # 1. FBref + Understat -> bronze_fbref/bronze_understat -> silver
    # extract_all acepta una o varias temporadas
    raw = extract_all(league_codes, seasons_list)
    fbref_raw, understat_raw = raw["fbref"], raw["understat"]

    if fbref_raw.empty:
        logger.error("Extracción de FBref vacía, abortando pipeline")
        return results

    silver_fbref = build_silver_fbref(fbref_raw)
    if not run_quality_checks(silver_fbref, FBREF_REQUIRED_COLS, FBREF_KEY_COLS):
        logger.warning("silver_fbref presenta problemas de calidad, revisar logs")
    upsert_dataframe(silver_fbref, "silver_fbref")
    results["silver_fbref"] = silver_fbref

    silver_understat = build_silver_understat(understat_raw)
    if not silver_understat.empty:
        if not run_quality_checks(silver_understat, UNDERSTAT_REQUIRED_COLS, UNDERSTAT_KEY_COLS):
            logger.warning("silver_understat presenta problemas de calidad, revisar logs")
        upsert_dataframe(silver_understat, "silver_understat")
    results["silver_understat"] = silver_understat

    # 2. Equipos -> bronze_football_data_teams -> silver
    teams_raw = get_all_leagues_teams(league_codes)
    silver_teams = build_silver_teams(teams_raw)
    upsert_dataframe(silver_teams, "silver_teams")
    results["silver_teams"] = silver_teams

    # 2b. Clasificación -> bronze_football_data_standings -> silver
    standings_frames = [get_all_leagues_standings(league_codes, season=s) for s in seasons_list]
    standings_frames = [f for f in standings_frames if not f.empty]
    standings_raw = pd.concat(standings_frames, ignore_index=True) if standings_frames else pd.DataFrame()
    silver_standings = build_silver_standings(standings_raw)
    if not silver_standings.empty:
        upsert_dataframe(silver_standings, "silver_standings")
    results["silver_standings"] = silver_standings

    # 3. Transfermarkt -> bronze_transfermarkt (con caché) -> silver
    tm_source = fbref_raw
    if "minutes_played" in fbref_raw.columns:
        tm_source = fbref_raw.sort_values("minutes_played", ascending=False).drop_duplicates(
            subset=["player_name"], keep="first"
        )
    # top_n_by_minutes es solo para pruebas: evita golpear Transfermarkt con la liga completa
    if top_n_by_minutes:
        before = len(tm_source)
        tm_source = tm_source.head(top_n_by_minutes)
        logger.info(
            f"Modo prueba: Transfermarkt limitado a los {top_n_by_minutes} jugadores "
            f"con más minutos ({before} -> {len(tm_source)})"
        )

    team_hints = dict(zip(tm_source["player_name"], tm_source["team"]))
    transfermarkt_raw = get_market_values_with_cache(
        player_names=tm_source["player_name"].dropna().unique().tolist(),
        team_hints=team_hints,
    )
    silver_transfermarkt = build_silver_transfermarkt(transfermarkt_raw)
    upsert_dataframe(silver_transfermarkt, "silver_transfermarkt")
    results["silver_transfermarkt"] = silver_transfermarkt

    # 4. WhoScored -> bronze_whoscored -> silver
    whoscored_raw = extract_whoscored(league_codes, seasons_list[-1], max_matches=whoscored_max_matches)
    silver_whoscored = build_silver_whoscored(whoscored_raw)
    if not silver_whoscored.empty:
        upsert_dataframe(silver_whoscored, "silver_whoscored")
    results["silver_whoscored"] = silver_whoscored

    logger.info(
        "Pipeline completo (silver, sin fusión): "
        f"fbref={len(silver_fbref)}, understat={len(silver_understat)}, "
        f"teams={len(silver_teams)}, standings={len(silver_standings)}, "
        f"transfermarkt={len(silver_transfermarkt)}, whoscored={len(silver_whoscored)} en {DB_PATH}"
    )
    return results


def run_market_value_history_pipeline(league_codes: list[str], top_n_by_minutes: int | None = None) -> pd.DataFrame:
    logger.info(f"Iniciando histórico de valor de mercado (Transfermarkt) para ligas={league_codes}")
    tm = read_table("silver_transfermarkt")
    if tm.empty:
        logger.error("silver_transfermarkt vacío — ejecuta run_pipeline() antes")
        return pd.DataFrame()

    tm = tm.dropna(subset=["transfermarkt_url"])
    if top_n_by_minutes:
        tm = tm.head(top_n_by_minutes)
    players = list(tm[["player_name", "transfermarkt_url"]].itertuples(index=False, name=None))
    logger.info(f"Histórico de valor de mercado: {len(players)} jugadores objetivo (1 petición extra c/u)")

    bronze_mv_history = get_market_value_history_with_cache(players)
    silver_mv_history = build_silver_transfermarkt_mv_history(bronze_mv_history)
    upsert_dataframe(silver_mv_history, "silver_transfermarkt_mv_history")
    logger.info(f"Histórico de valor de mercado completo: {len(silver_mv_history)} puntos en {DB_PATH}")
    return silver_mv_history


def run_api_football_pipeline(
    league_codes: list[str], season: str, top_n_players: int = 20, top_n_teams: int = 10
) -> dict[str, pd.DataFrame]:
    logger.info(f"Iniciando API-Football (transfers/injuries) para ligas={league_codes}, temporada={season}")
    results: dict[str, pd.DataFrame] = {}

    fbref = read_table("silver_fbref", where=f"league IN ({','.join(repr(c) for c in league_codes)})")
    if fbref.empty:
        logger.error("silver_fbref vacío para esas ligas — ejecuta run_pipeline() antes de API-Football")
        return results

    player_names = (
        fbref.sort_values("minutes_played", ascending=False)["player_name"]
        .dropna().unique().tolist()[:top_n_players]
    )
    logger.info(f"API-Football transfers: {len(player_names)} jugadores objetivo (hasta ~{len(player_names) * 2} peticiones)")
    bronze_transfers = extract_transfers_for_players(player_names)
    silver_transfers = build_silver_transfers(bronze_transfers)
    upsert_dataframe(silver_transfers, "silver_transfers")
    results["silver_transfers"] = silver_transfers

    teams = read_table("silver_teams", where=f"league IN ({','.join(repr(c) for c in league_codes)})")
    if teams.empty:
        logger.warning("silver_teams vacío para esas ligas, se omite API-Football injuries")
    else:

        team_pairs = list(
            teams[["team_name", "short_name"]].dropna(subset=["team_name"]).itertuples(index=False, name=None)
        )[:top_n_teams]
        logger.info(f"API-Football injuries: {len(team_pairs)} equipos objetivo (~{len(team_pairs) * 2} peticiones)")
        bronze_injuries = extract_injuries_for_teams(team_pairs, season)
        silver_injuries = build_silver_injuries(bronze_injuries)
        upsert_dataframe(silver_injuries, "silver_injuries")
        results["silver_injuries"] = silver_injuries

    logger.info(
        f"API-Football completo: transfers={len(results.get('silver_transfers', pd.DataFrame()))}, "
        f"injuries={len(results.get('silver_injuries', pd.DataFrame()))}"
    )
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--leagues", type=str, default=",".join(LEAGUES.keys()))
    parser.add_argument("--season", type=str, default=DEFAULT_SEASON,
                         help="Temporada final (más reciente) a extraer, formato YYYY-YYYY")
    parser.add_argument("--seasons-back", type=int, default=None,
                         help="Si se indica, pide esta cantidad de temporadas hacia atrás desde --season "
                              "(incluida) en vez de solo esa temporada — necesario para construir histórico "
                              "pre/post-fichaje. FBref/Understat solamente (Transfermarkt no es por temporada, "
                              "WhoScored solo pide la más reciente).")
    parser.add_argument("--top-n", type=int, default=None,
                         help="Limitar a los N jugadores con más minutos jugados (pruebas rápidas, evita golpear Transfermarkt con la liga completa)")
    parser.add_argument("--whoscored-max-matches", type=int, default=None,
                         help="Limitar WhoScored a los N primeros partidos del calendario (una temporada completa "
                              "son ~380 partidos/liga, uno por petición — sin límite tarda 30-50+ min)")
    parser.add_argument("--run-api-football", action="store_true",
                         help="Además del pipeline principal, ejecuta API-Football (transfers/injuries). Consume cuota diaria (~100 peticiones/día)")
    parser.add_argument("--api-football-top-n", type=int, default=20,
                         help="Límite de jugadores/equipos para API-Football (por defecto 20, para no agotar la cuota diaria)")
    parser.add_argument("--run-market-value-history", action="store_true",
                         help="Además del pipeline principal, extrae el histórico de valor de mercado de Transfermarkt "
                              "(1 petición extra por jugador)")
    parser.add_argument("--market-value-history-top-n", type=int, default=None,
                         help="Límite de jugadores para el histórico de valor de mercado (recomendado en pruebas)")
    args = parser.parse_args()

    league_codes = args.leagues.split(",")
    seasons = historical_seasons(args.season, args.seasons_back) if args.seasons_back else args.season
    run_pipeline(league_codes, seasons, top_n_by_minutes=args.top_n, whoscored_max_matches=args.whoscored_max_matches)

    if args.run_api_football:
        run_api_football_pipeline(
            league_codes,
            args.season,
            top_n_players=args.api_football_top_n,
            top_n_teams=min(args.api_football_top_n, 10),
        )

    if args.run_market_value_history:
        run_market_value_history_pipeline(league_codes, top_n_by_minutes=args.market_value_history_top_n)
