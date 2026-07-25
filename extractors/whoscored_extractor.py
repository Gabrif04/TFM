import numpy as np
import pandas as pd
import soccerdata as sd
from bs4 import BeautifulSoup
from selenium.common.exceptions import WebDriverException

from config import DEFAULT_SEASON
from utils.database import init_db, write_bronze
from utils.logger import get_logger

logger = get_logger(__name__)

SOCCERDATA_LEAGUE_NAMES = {
    "ESP": "ESP-La Liga", "ENG": "ENG-Premier League", "ITA": "ITA-Serie A",
    "GER": "GER-Bundesliga", "FRA": "FRA-Ligue 1",
}

# WhoScored (vía soccerdata) solo cubre las 5 grandes ligas, igual que FBref/Understat.
WHOSCORED_SUPPORTED_LEAGUES = {"ESP", "ENG", "ITA", "GER", "FRA"}


def _patched_validate_page(self, url: str) -> str:
    page_html = self._driver.page_source
    if "Incapsula incident ID" in page_html:
        raise WebDriverException("Your IP is blocked. Use tor or a proxy to continue scraping.")
    if not page_html:
        raise Exception("Empty response.")
    body = BeautifulSoup(page_html, "html.parser").find("body")
    return body.get_text() if body else page_html


def _patch_whoscored() -> None:
    if getattr(sd.WhoScored, "_atm_scouting_patched", False):
        return
    sd.WhoScored._validate_page = _patched_validate_page
    sd.WhoScored._atm_scouting_patched = True


def get_whoscored_events(
    league_code: str, season: str = DEFAULT_SEASON, max_matches: int | None = None
) -> pd.DataFrame:
    if league_code not in WHOSCORED_SUPPORTED_LEAGUES:
        logger.info(f"WhoScored no cubre {league_code} (fuera de las 5 grandes ligas), se omite")
        return pd.DataFrame()

    _patch_whoscored()
    league_name = SOCCERDATA_LEAGUE_NAMES.get(league_code)
    try:
        ws = sd.WhoScored(leagues=league_name, seasons=season)
        if max_matches:
            schedule = ws.read_schedule().reset_index()
            match_ids = schedule["game_id"].head(max_matches).tolist()
            logger.info(f"WhoScored: limitado a {len(match_ids)} partidos de {league_code} {season}")
            events = ws.read_events(match_id=match_ids).reset_index()
        else:
            events = ws.read_events().reset_index()
        logger.info(f"WhoScored: {len(events)} eventos extraídos de {league_code} {season}")
        return events
    except Exception as e:
        logger.error(f"Error extrayendo WhoScored para {league_code} {season}: {e}")
        return pd.DataFrame()


def aggregate_player_match_stats(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()

    required = {"league", "season", "game", "team", "player", "type", "outcome_type"}
    missing = required - set(events.columns)
    if missing:
        logger.error(f"aggregate_player_match_stats: faltan columnas esperadas {missing}, no se agrega")
        return pd.DataFrame()

    is_pass = events["type"] == "Pass"
    is_success = events["outcome_type"] == "Successful"
    is_cross = is_pass & events["qualifiers"].apply(
        lambda qs: isinstance(qs, list) and any(q.get("type", {}).get("displayName") == "Cross" for q in qs)
    )

    group_cols = ["league", "season", "game", "team", "player"]
    grouped = events.groupby(group_cols)

    agg = grouped.apply(lambda g: pd.Series({
        "passes_attempted": is_pass.loc[g.index].sum(),
        "passes_completed": (is_pass & is_success).loc[g.index].sum(),
        "crosses": is_cross.loc[g.index].sum(),
        "crosses_completed": (is_cross & is_success).loc[g.index].sum(),
        "tackles": (g["type"] == "Tackle").sum(),
        "interceptions": (g["type"] == "Interception").sum(),
    }), include_groups=False).reset_index()

    agg["pass_completion_pct"] = np.where(
        agg["passes_attempted"] > 0,
        agg["passes_completed"] / agg["passes_attempted"] * 100,
        np.nan,
    )
    agg = agg.rename(columns={"player": "player_name", "game": "game_id"})
    return agg


def extract_whoscored(
    league_codes: list[str], season: str = DEFAULT_SEASON, max_matches: int | None = None
) -> pd.DataFrame:
    init_db()
    frames = []
    for code in league_codes:
        events = get_whoscored_events(code, season, max_matches=max_matches)
        if events.empty:
            continue
        agg = aggregate_player_match_stats(events)
        if not agg.empty:
            frames.append(agg)

    if not frames:
        logger.warning("extract_whoscored: sin datos (bloqueado o sin cobertura), no se escribe en bronze_whoscored")
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    write_bronze(result, "bronze_whoscored", id_cols=["player_name", "team", "game_id"])
    return result


if __name__ == "__main__":
    df = extract_whoscored(["ESP"], max_matches=3)
    print(df.head() if not df.empty else "sin datos (ver logs: probablemente bloqueado por bot-detection)")
