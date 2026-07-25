import time
import datetime as dt
import pandas as pd
import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz
from utils.database import init_db, read_table, upsert_dataframe
from utils.logger import get_logger

logger = get_logger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (research project; contact: your_email@example.com)"
}
MIN_DELAY_SECONDS = 3  # NO TOCAR!!!
SEARCH_URL = "https://www.transfermarkt.com/schnellsuche/ergebnis/schnellsuche"
MATCH_THRESHOLD = 80  #Scoring minimo que puse para el matcheo de equipos obtenidos en la extracción de footballdata


def search_player_url(player_name: str, team_hint: str | None = None) -> str | None:
    params = {"query": player_name}
    try:
        resp = requests.get(SEARCH_URL, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error buscando '{player_name}' en Transfermarkt: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    rows = soup.select("table.items tbody tr")

    candidates = []
    for row in rows:
        link = row.select_one("a[href*='/profil/spieler/']")
        if not link:
            continue
        name = link.get_text(strip=True)
        if not name:
            continue
        club_tag = row.select_one("td.zentriert a[href*='/verein/']")
        club = club_tag.get_text(strip=True) if club_tag else ""
        url = "https://www.transfermarkt.com" + link["href"]
        candidates.append({"name": name, "club": club, "url": url})

    if not candidates:
        logger.warning(f"Sin resultados de búsqueda para '{player_name}'")
        time.sleep(MIN_DELAY_SECONDS)
        return None

    # Scoring
    best, best_score = None, -1
    for c in candidates:
        score = fuzz.token_sort_ratio(player_name.lower(), c["name"].lower())
        if team_hint and team_hint.lower() in c["club"].lower():
            score += 10  # desempata homónimos usando el equipo conocido
        if score > best_score:
            best, best_score = c, score

    time.sleep(MIN_DELAY_SECONDS)

    if best_score < MATCH_THRESHOLD:
        logger.warning(
            f"Mejor match para '{player_name}' fue '{best['name']}' "
            f"con score {best_score} (< umbral {MATCH_THRESHOLD}), se descarta"
        )
        return None

    logger.info(f"'{player_name}' -> '{best['name']}' ({best['club']}), score={best_score}")
    return best["url"]


def get_player_market_value(transfermarkt_player_url: str) -> dict:

    try:
        resp = requests.get(transfermarkt_player_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # El wrapper del valor de mercado incluye un <p> con "Last update: ..." como hijo; hay que quitarlo antes de leer el texto o queda
        # concatenado con la cifra (p.ej. "€120.00mLast update: 22/07/2026").
        value_tag = soup.select_one(".data-header__market-value-wrapper")
        market_value = None
        if value_tag:
            last_update = value_tag.select_one(".data-header__last-update")
            if last_update:
                last_update.extract()
            market_value = value_tag.get_text(strip=True)

        # El nombre real vive en un <strong> dentro del headline-wrapper; el wrapper entero también incluye el dorsal (p.ej. "#19Julián Álvarez"
        # si se lee de golpe).
        name_tag = soup.select_one(".data-header__headline-wrapper strong")
        player_name_canonical = name_tag.get_text(strip=True) if name_tag else None

        contract_until = _extract_contract_until(soup)
        info = _parse_info_table(soup)

        time.sleep(MIN_DELAY_SECONDS)
        return {
            "player_name_canonical": player_name_canonical,
            "market_value_raw": market_value,
            "contract_until_raw": contract_until,
            "transfermarkt_url": transfermarkt_player_url,
            "height_raw": info.get("height"),
            "foot": info.get("foot"),
            "nationality": info.get("citizenship"),
            "agent": info.get("player agent"),
            "full_name": info.get("full name"),
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Error extrayendo Transfermarkt {transfermarkt_player_url}: {e}")
        return {}

def _parse_info_table(soup: BeautifulSoup) -> dict[str, str]:
    items = soup.select(".info-table__content--regular, .info-table__content--bold")
    info: dict[str, str] = {}
    label = None
    for item in items:
        text = item.get_text(strip=True)
        is_label = "info-table__content--regular" in (item.get("class") or [])
        if is_label:
            label = text.rstrip(":").lower()
        elif label:
            info[label] = text
            label = None
    return info


def _extract_contract_until(soup: BeautifulSoup) -> str | None:

    for item in soup.select(".data-header__label"):
        if "contract expires" in item.get_text(strip=True).lower():
            value = item.select_one(".data-header__content")
            if value:
                return value.get_text(strip=True)

    # Fallback
    for row in soup.select("table.info-table tr"):
        label = row.select_one("th")
        if label and "contract expires" in label.get_text(strip=True).lower():
            value = row.select_one("td")
            if value:
                return value.get_text(strip=True)

    return None


def get_market_values_by_name(player_names: list[str], team_hints: dict[str, str] | None = None) -> pd.DataFrame:

    team_hints = team_hints or {}
    rows = []
    for name in player_names:
        url = search_player_url(name, team_hint=team_hints.get(name))
        if not url:
            rows.append({"player_name": name, "market_value_raw": None, "transfermarkt_url": None})
            continue
        data = get_player_market_value(url)
        if not data:
            data = {"market_value_raw": None, "contract_until_raw": None, "transfermarkt_url": url}
        #player_name es siempre el nombre BUSCADO (el que usa el resto del pipeline para fusionar/cachear), no el nombre canónico que muestra
        #la página de Transfermarkt — si no, la caché nunca vuelve a encontrarse a sí misma en la siguiente ejecución.
        data["player_name"] = name
        rows.append(data)

    df = pd.DataFrame(rows)
    df["source"] = "transfermarkt"
    n_found = df["market_value_raw"].notna().sum()
    logger.info(f"Transfermarkt: {n_found}/{len(df)} valores de mercado resueltos por nombre")
    return df

def get_market_values_with_cache(
    player_names: list[str],
    team_hints: dict[str, str] | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    init_db()

    cached = read_table("bronze_transfermarkt") if not force_refresh else pd.DataFrame(columns=["player_name"])
    already_cached = set(cached["player_name"]) if not cached.empty else set()
    pending = [n for n in player_names if n not in already_cached]

    logger.info(f"Transfermarkt: {len(pending)} jugadores nuevos por buscar, {len(already_cached)} ya en bronze")

    if pending:
        fresh = get_market_values_by_name(pending, team_hints=team_hints)
        fresh["extracted_at"] = dt.datetime.now().isoformat()
        db_cols = [
            "player_name", "market_value_raw", "contract_until_raw", "transfermarkt_url",
            "height_raw", "foot", "nationality", "agent", "full_name", "extracted_at",
        ]
        db_cols = [c for c in db_cols if c in fresh.columns]
        upsert_dataframe(fresh[db_cols], "bronze_transfermarkt")

    result = read_table("bronze_transfermarkt")
    return result[result["player_name"].isin(player_names)].reset_index(drop=True)


MV_HISTORY_URL_TEMPLATE = "https://www.transfermarkt.com/ceapi/marketValueDevelopment/graph/{player_id}"


def get_market_value_history(transfermarkt_url: str) -> list[dict]:
    player_id = transfermarkt_url.rstrip("/").split("/")[-1]
    url = MV_HISTORY_URL_TEMPLATE.format(player_id=player_id)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        time.sleep(MIN_DELAY_SECONDS)
        return data.get("list", [])
    except (requests.exceptions.RequestException, ValueError) as e:
        logger.error(f"Error extrayendo histórico de valor de mercado {url}: {e}")
        return []


def get_market_value_history_with_cache(
    players: list[tuple[str, str]], force_refresh: bool = False
) -> pd.DataFrame:
    init_db()
    cached = read_table("bronze_transfermarkt_mv_history") if not force_refresh else pd.DataFrame(columns=["player_name"])
    already_cached = set(cached.get("player_name", []))

    rows = []
    for player_name, url in players:
        if not url or player_name in already_cached:
            continue
        history = get_market_value_history(url)
        for point in history:
            rows.append({
                "player_name": player_name,
                "date_raw": point.get("datum_mw"),
                "market_value_eur": point.get("y"),
                "market_value_raw": point.get("mw"),
                "club_at_time": point.get("verein"),
                "age_at_time": point.get("age"),
            })

    if rows:
        df = pd.DataFrame(rows)
        df["extracted_at"] = dt.datetime.now().isoformat()
        upsert_dataframe(df, "bronze_transfermarkt_mv_history")

    return read_table("bronze_transfermarkt_mv_history")


if __name__ == "__main__":

    sample_names = ["Julián Álvarez", "Antoine Griezmann"]
    sample_team_hints = {"Julián Álvarez": "Atlético Madrid", "Antoine Griezmann": "Atlético Madrid"}

    #Búsqueda de equipos sacados de otras extracciones con fuzzy matching
    df = get_market_values_by_name(sample_names, team_hints=sample_team_hints)
    print(df)