"""
Migración puntual: normaliza la columna `league` en las tablas silver ya
cargadas en la BBDD, para no tener que relanzar toda la extracción.

El problema: los extractores de fbref/understat sobreescriben league con el
código corto ('ESP'), pero aggregate_player_match_stats de whoscored agrupa
por la columna nativa de soccerdata y conserva el nombre largo
('ESP-La Liga'). Resultado: joins y filtros por `league` entre fuentes no
casan.

A partir de ahora build_silver_* ya llama a normalize_league, así que este
script solo hace falta una vez sobre los datos antiguos.

Uso:
    python -m scripts.backfill_league_codes          # muestra qué cambiaría
    python -m scripts.backfill_league_codes --apply  # lo escribe
"""
import argparse

import pandas as pd

from transform.cleaning import normalize_league
from utils.database import get_connection
from utils.logger import get_logger

logger = get_logger(__name__)

TABLES = [
    "silver_fbref", "silver_understat", "silver_whoscored",
    "silver_teams", "silver_standings",
]


def main(apply: bool = False) -> None:
    conn = get_connection()
    try:
        for table in TABLES:
            try:
                df = pd.read_sql(f"SELECT DISTINCT league FROM {table}", conn)
            except Exception:
                logger.warning("%s: no existe o no tiene columna league, se omite", table)
                continue
            if df.empty:
                continue

            changes = {
                raw: normalize_league(raw)
                for raw in df["league"].dropna().unique()
                if normalize_league(raw) != raw
            }
            if not changes:
                print(f"{table}: ya está normalizada")
                continue

            for raw, clean in changes.items():
                n = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE league = ?", (raw,)
                ).fetchone()[0]
                print(f"{table}: {raw!r} -> {clean!r} ({n} filas)")
                if apply:
                    conn.execute(
                        f"UPDATE {table} SET league = ? WHERE league = ?", (clean, raw)
                    )
        if apply:
            conn.commit()
            print("\nCambios aplicados.")
        else:
            print("\nSimulación (dry-run). Relanza con --apply para escribir.")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="escribe los cambios en la BBDD")
    main(**vars(parser.parse_args()))
