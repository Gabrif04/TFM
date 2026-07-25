import pandas as pd
import soccerdata as sd

from config import LEAGUES, DEFAULT_SEASON
from utils.database import init_db, write_bronze
from utils.logger import get_logger

logger = get_logger(__name__)

def _normalize_season(raw_season) -> str:
    s = str(raw_season)
    if len(s) == 4 and s.isdigit():
        start_year = int("20" + s[:2])
        return f"{start_year}-{start_year + 1}"
    return s


SOCCERDATA_LEAGUE_NAMES = {
    "ESP": "ESP-La Liga", "ENG": "ENG-Premier League", "ITA": "ITA-Serie A",
    "GER": "GER-Bundesliga", "FRA": "FRA-Ligue 1",
    "POR": "POR-Primeira Liga", "NED": "NED-Eredivisie",
}

# FBref (vía soccerdata) solo cubre las 5 grandes ligas + competiciones
# internacionales. POR y NED existen en football-data.org pero NO en FBref.
FBREF_SUPPORTED_LEAGUES = {"ESP", "ENG", "ITA", "GER", "FRA"}

FBREF_COLUMN_MAP = {
    "pos": "position",
    "Playing Time_Min": "minutes_played",
    "Performance_misc_Crs": "crosses",
    "Performance_misc_Int": "interceptions",
    # OJO: TklW = tackles GANADOS, no el total de entradas intentadas
    "Performance_misc_TklW": "tackles",
}

#Gestión de columnas MultiIndex de soccerdata
def _flatten_fbref_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [
        "_".join(str(level) for level in col if str(level)) if isinstance(col, tuple) else col
        for col in df.columns
    ]
    return df.rename(columns=FBREF_COLUMN_MAP)

#Estadisticas de jugador
def extract_fbref_stats(league_code: str, seasons: str | list[str] = DEFAULT_SEASON) -> pd.DataFrame:
    if league_code not in FBREF_SUPPORTED_LEAGUES:
        logger.info(f"FBref no cubre {league_code} (fuera de las 5 grandes ligas), se omite")
        return pd.DataFrame()

    league_name = SOCCERDATA_LEAGUE_NAMES.get(league_code)
    try:
        fbref = sd.FBref(leagues=league_name, seasons=seasons)
        standard = fbref.read_player_season_stats(stat_type="standard")
        misc = fbref.read_player_season_stats(stat_type="misc")

        df = standard.join(misc, rsuffix="_misc").reset_index()
        df = df.rename(columns={"player": "player_name"})
        df = _flatten_fbref_columns(df)
        df["season"] = df["season"].apply(_normalize_season)
        df["league"] = league_code
        df["source"] = "fbref"
        logger.info(f"FBref: {len(df)} jugadores extraídos de {league_code} {seasons}")
        logger.info(f"Columnas disponibles: {list(df.columns)}")  #temporal, borrar cuando se hagan las pruebas con todos los datos
        return df
    except Exception as e:
        logger.error(f"Error extrayendo FBref para {league_code}: {e}")
        return pd.DataFrame()


def extract_understat_stats(league_code: str, seasons: str | list[str] = DEFAULT_SEASON) -> pd.DataFrame:
    league_name = SOCCERDATA_LEAGUE_NAMES.get(league_code)
    if league_code not in {"ESP", "ENG", "ITA", "GER", "FRA"}:
        logger.info(f"Understat no cubre {league_code}, se omite")
        return pd.DataFrame()

    try:
        understat = sd.Understat(leagues=league_name, seasons=seasons)
        df = understat.read_player_season_stats().reset_index()
        #np_xg es el nombre real que devuelve soccerdata el resto del proyecto usa npxg
        df = df.rename(columns={"player": "player_name", "np_xg": "npxg"})
        df["season"] = df["season"].apply(_normalize_season)
        df["league"] = league_code
        df["source"] = "understat"
        logger.info(f"Understat: {len(df)} jugadores extraídos de {league_code} {seasons}")
        return df
    except Exception as e:
        logger.error(f"Error extrayendo Understat para {league_code}: {e}")
        return pd.DataFrame()


def extract_all(league_codes: list[str], seasons: str | list[str] = DEFAULT_SEASON) -> dict[str, pd.DataFrame]:
    init_db()
    fbref_frames, understat_frames = [], []
    for code in league_codes:
        fbref_frames.append(extract_fbref_stats(code, seasons))
        understat_frames.append(extract_understat_stats(code, seasons))

    fbref_frames = [f for f in fbref_frames if not f.empty]
    understat_frames = [f for f in understat_frames if not f.empty]

    fbref_df = pd.concat(fbref_frames, ignore_index=True) if fbref_frames else pd.DataFrame()
    understat_df = pd.concat(understat_frames, ignore_index=True) if understat_frames else pd.DataFrame()

    if not fbref_df.empty:
        write_bronze(fbref_df, "bronze_fbref", id_cols=["player_name", "team", "season"])
    else:
        logger.warning("extract_all: ninguna liga devolvió datos de FBref, no se escribe en bronze_fbref")

    if not understat_df.empty:
        write_bronze(understat_df, "bronze_understat", id_cols=["player_name", "team", "season"])
    else:
        logger.warning("extract_all: ninguna liga devolvió datos de Understat, no se escribe en bronze_understat")

    return {"fbref": fbref_df, "understat": understat_df}


if __name__ == "__main__":
    result = extract_all(list(LEAGUES.keys()))
    for name, df in result.items():
        print(name, df.shape)