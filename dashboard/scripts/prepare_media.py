"""Prepare a reviewed Wikimedia image catalog; never runs from the dashboard.

discover writes candidates for review. download accepts only catalog entries
explicitly marked approved and records original author and license metadata.
"""
import argparse
import hashlib
import html
import io
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "dashboard" / "assets" / "media"
CATALOG = MEDIA / "catalog.json"
MANIFEST = MEDIA / "manifest.json"
APPROVED = MEDIA / "approved.json"
WD = "https://www.wikidata.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "ScoutingLabTFM/1.0 (local educational project; Wikimedia image attribution retained)"
ALIASES = {
    "Alavés": "Deportivo Alaves", "Athletic Club": "Athletic Bilbao", "Atlético Madrid": "Atletico Madrid",
    "Barcelona": "FC Barcelona", "Celta Vigo": "RC Celta de Vigo", "Elche": "Elche CF",
    "Espanyol": "RCD Espanyol", "Getafe": "Getafe CF", "Girona": "Girona FC", "Levante": "Levante UD",
    "Mallorca": "RCD Mallorca", "Osasuna": "CA Osasuna", "Oviedo": "Real Oviedo",
    "Sevilla": "Sevilla FC", "Valencia": "Valencia CF", "Villarreal": "Villarreal CF",
    "Arsenal": "Arsenal FC", "Bournemouth": "AFC Bournemouth", "Brighton": "Brighton & Hove Albion",
    "Brentford": "Brentford FC", "Burnley": "Burnley FC", "Chelsea": "Chelsea FC",
    "Crystal Palace": "Crystal Palace FC", "Everton": "Everton FC", "Fulham": "Fulham FC",
    "Liverpool": "Liverpool FC", "Manchester Utd": "Manchester United", "Newcastle": "Newcastle United",
    "Nottingham": "Nottingham Forest", "Sunderland": "Sunderland AFC",
    "Tottenham": "Tottenham Hotspur", "West Ham": "West Ham United", "Wolves": "Wolverhampton Wanderers",
    "Angers": "Angers SCO", "Auxerre": "AJ Auxerre", "Brest": "Stade Brestois 29",
    "Le Havre": "Le Havre AC", "Lens": "RC Lens", "Lille": "Lille OSC", "Lorient": "FC Lorient",
    "Lyon": "Olympique Lyonnais", "Marseille": "Olympique Marseille", "Metz": "FC Metz",
    "Monaco": "AS Monaco FC", "Nantes": "FC Nantes", "Nice": "OGC Nice", "PSG": "Paris Saint-Germain FC",
    "Rennes": "Stade Rennais FC", "Strasbourg": "RC Strasbourg Alsace", "Toulouse": "Toulouse FC",
    "Augsburg": "FC Augsburg", "Bayern Munich": "FC Bayern Munich", "Dortmund": "Borussia Dortmund",
    "Frankfurt": "Eintracht Frankfurt", "Freiburg": "SC Freiburg", "Gladbach": "Borussia Monchengladbach",
    "Heidenheim": "1. FC Heidenheim", "Hoffenheim": "TSG 1899 Hoffenheim", "Köln": "1. FC Köln",
    "Leverkusen": "Bayer 04 Leverkusen", "Mainz 05": "1. FSV Mainz 05", "St Pauli": "FC St. Pauli",
    "Stuttgart": "VfB Stuttgart", "Wolfsburg": "VfL Wolfsburg",
    "Atalanta": "Atalanta BC", "Bologna": "Bologna FC 1909", "Cagliari": "Cagliari Calcio",
    "Como": "Como 1907", "Cremonese": "US Cremonese", "Fiorentina": "ACF Fiorentina",
    "Genoa": "Genoa CFC", "Inter": "Inter Milan", "Lazio": "SS Lazio", "Lecce": "US Lecce",
    "Milan": "AC Milan", "Napoli": "SSC Napoli", "Parma": "Parma Calcio 1913", "Pisa": "Pisa SC",
    "Roma": "AS Roma", "Sassuolo": "US Sassuolo Calcio", "Torino": "Torino FC", "Udinese": "Udinese Calcio",
}


def get_json(url, params):
    time.sleep(1.5)
    for attempt in range(4):
        response = SESSION.get(url, params={**params, "format": "json"}, timeout=30)
        if response.status_code not in [429, 502, 503, 504] or attempt == 3:
            break
        delay = int(response.headers.get("Retry-After", "30"))
        print("Waiting for Wikimedia rate limit:", delay, "seconds", flush=True)
        time.sleep(delay)
    response.raise_for_status()
    result = response.json()
    if "error" in result:
        raise ValueError(str(result["error"]))
    return result


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def discover():
    df = pd.read_csv(ROOT / "salida_modelos" / "resultados_jugadores.csv")
    entries = []
    for league, team in df[["league", "team"]].drop_duplicates().sort_values(["league", "team"]).itertuples(index=False, name=None):
        entries.append({"kind": "club", "key": f"{league}|{team}", "query": ALIASES.get(team, team)})
    pilot = df.sort_values(["market_value_eur", "player_name"], ascending=[False, True]).drop_duplicates(["player_name", "league"]).groupby("league", sort=True).head(5)
    for row in pilot.itertuples():
        query = row.player_name
        if row.player_name == "Vitinha":
            query = "Vitinha footballer born March 2000" if row.team == "Genoa" else "Vitinha footballer born February 2000"
        entries.append({"kind": "player", "key": "|".join([row.player_name, row.team, row.league, row.season]),
                        "query": query, "age": row.age})
    previous = {x["key"]: x for x in json.loads(CATALOG.read_text(encoding="utf-8"))} if CATALOG.exists() else {}
    for index, entry in enumerate(entries):
        if entry["key"] in previous and previous[entry["key"]].get("candidates"):
            entries[index] = previous[entry["key"]]
            continue
        results = get_json(WD, {"action": "wbsearchentities", "search": entry["query"], "language": "en", "limit": 5})
        entry["candidates"] = [{k: item.get(k, "") for k in ["id", "label", "description"]} for item in results.get("search", [])]
        entry["approved"] = False
        save_json(CATALOG, entries)
        print(entry["key"], json.dumps(entry["candidates"], ensure_ascii=True), flush=True)


def text_value(metadata, key):
    return html.unescape(re.sub("<[^>]+>", "", metadata.get(key, {}).get("value", ""))).strip()


def download():
    entries = json.loads(CATALOG.read_text(encoding="utf-8"))
    approvals = json.loads(APPROVED.read_text(encoding="utf-8")) if APPROVED.exists() else {}
    for entry in entries:
        if entry["key"] in approvals:
            entry.update(approved=True, entity=approvals[entry["key"]])
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {"club": {}, "player": {}}
    ids = sorted({x["entity"] for x in entries if x.get("approved") and x.get("entity")})
    entities = {}
    for start in range(0, len(ids), 50):
        entities.update(get_json(WD, {"action": "wbgetentities", "ids": "|".join(ids[start:start + 50]),
                                     "props": "claims"})["entities"])
    filenames_by_key = {}
    image_info = {}
    for kind, prop, width in [("club", "P154", 96), ("player", "P18", 320)]:
        filenames = set()
        for entry in entries:
            if entry["kind"] != kind or not entry.get("approved") or not entry.get("entity"):
                continue
            claims = entities[entry["entity"]].get("claims", {}).get(prop, [])
            names = [c["mainsnak"]["datavalue"]["value"] for c in claims
                     if c.get("rank") != "deprecated" and "datavalue" in c["mainsnak"]]
            name = entry.get("file") or (names[0] if names else None)
            if name:
                filenames_by_key[entry["key"]] = name
                filenames.add(name)
        filenames = sorted(filenames)
        for start in range(0, len(filenames), 25):
            query = get_json(COMMONS, {"action": "query",
                "titles": "|".join("File:" + name for name in filenames[start:start + 25]),
                "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": width})
            normalized = {x["from"]: x["to"] for x in query.get("query", {}).get("normalized", [])}
            pages = {page["title"]: page for page in query["query"]["pages"].values()}
            for name in filenames[start:start + 25]:
                title = "File:" + name
                page = pages.get(normalized.get(title, title), {})
                if page.get("imageinfo"):
                    image_info[(kind, name)] = page["imageinfo"][0]
    for entry in entries:
        if not entry.get("approved") or not entry.get("entity"):
            continue
        existing = manifest[entry["kind"]].get(entry["key"], {})
        if existing.get("path") and (MEDIA / existing["path"]).exists():
            continue
        try:
            filename = filenames_by_key.get(entry["key"])
            if not filename:
                print("NO IMAGE", entry["key"], flush=True)
                manifest[entry["kind"]][entry["key"]] = {"status": "no_image", "entity": entry["entity"]}
                save_json(MANIFEST, manifest)
                continue
            info = image_info[(entry["kind"], filename)]
            metadata = info.get("extmetadata", {})
            license_name = text_value(metadata, "LicenseShortName")
            if not license_name:
                raise ValueError("Missing license metadata")
            url = info.get("thumburl") or info["url"]
            if urlparse(url).hostname not in {"upload.wikimedia.org", "thumb.wikimedia.org"}:
                raise ValueError("Unexpected media host")
            time.sleep(0.5)
            response = SESSION.get(url, timeout=40)
            response.raise_for_status()
            with Image.open(io.BytesIO(response.content)) as source:
                source.thumbnail((320, 400) if entry["kind"] == "player" else (96, 96))
                image = source.convert("RGBA")
                path = entry["kind"] + "/" + hashlib.sha256(entry["key"].encode()).hexdigest()[:20] + ".webp"
                target = MEDIA / path
                target.parent.mkdir(parents=True, exist_ok=True)
                image.save(target, "WEBP", quality=85)
            manifest[entry["kind"]][entry["key"]] = {
                "status": "ready", "path": path, "entity": entry["entity"], "file": filename,
                "source": info["descriptionurl"], "author": text_value(metadata, "Artist"),
                "license": license_name, "license_url": text_value(metadata, "LicenseUrl"),
                "credit": text_value(metadata, "Credit"), "modifications": "Resized and converted to WebP; original framing retained",
            }
            print("SAVED", entry["key"], license_name, flush=True)
        except (requests.RequestException, ValueError, KeyError, IndexError, OSError) as exc:
            manifest[entry["kind"]][entry["key"]] = {"status": "unavailable", "entity": entry["entity"], "error": str(exc)}
            print("UNAVAILABLE", entry["key"], str(exc), flush=True)
        save_json(MANIFEST, manifest)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["discover", "download"])
    args = parser.parse_args()
    if args.mode == "discover":
        discover()
    else:
        download()
