import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")

#Añadiria para el modelo ligas menores, investigar cuales hay
LEAGUES = {
    "ESP": "La Liga",
    "ENG": "Premier League",
    "ITA": "Serie A",
    "GER": "Bundesliga",
    "FRA": "Ligue 1",
    "POR": "Primeira Liga",
    "NED": "Eredivisie",
}

DEFAULT_SEASON = "2025-2026"
REQUEST_TIMEOUT = 15


def historical_seasons(end_season: str = DEFAULT_SEASON, n_back: int = 5) -> list[str]:
    start_year = int(end_season.split("-")[0])
    return [f"{y}-{y + 1}" for y in range(start_year - n_back + 1, start_year + 1)]


#Estimado de fuerza de ligas MODIFICAR A LA HORA DE HACER EL MODELO
LEAGUE_STRENGTH = {
    "ESP": 1.00,
    "ENG": 1.00,
    "ITA": 0.95,
    "GER": 0.95,
    "FRA": 0.85,
    "POR": 0.70,
    "NED": 0.70,
}