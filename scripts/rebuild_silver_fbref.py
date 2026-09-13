"""
Reconstruye silver_fbref a partir de bronze_fbref, sin volver a scrapear.

bronze_fbref guarda el payload completo de fbref (43 campos) en payload_json,
pero build_silver_fbref solo conservaba 3 estadísticas. Al ampliar
FBREF_NUMERIC_COLS hace falta regenerar la capa silver: este script expande
el JSON y vuelve a pasar por build_silver_fbref, así que no cuesta ni una
petición de red.

Uso:
    python -m scripts.rebuild_silver_fbref
"""
import json

import pandas as pd

from transform.silver import build_silver_fbref
from utils.database import get_connection, upsert_dataframe
from utils.logger import get_logger

logger = get_logger(__name__)


def _add_missing_columns(conn, table: str, df: pd.DataFrame) -> None:
    """La tabla silver_fbref se creó con el esquema antiguo (3 stats). Se
    añaden las columnas nuevas con ALTER TABLE para no perder los datos ya
    cargados ni tener que recrear la tabla."""
    existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    for col in df.columns:
        if col in existing:
            continue
        sql_type = "REAL" if pd.api.types.is_numeric_dtype(df[col]) else "TEXT"
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {sql_type}")
        logger.info("Columna añadida a %s: %s (%s)", table, col, sql_type)
    conn.commit()


def main() -> None:
    conn = get_connection()
    try:
        bronze = pd.read_sql("SELECT payload_json FROM bronze_fbref", conn)
    finally:
        conn.close()

    if bronze.empty:
        logger.error("bronze_fbref está vacía, nada que reconstruir")
        return

    fbref_raw = pd.DataFrame([json.loads(p) for p in bronze["payload_json"]])
    logger.info("bronze_fbref expandida: %d filas, %d columnas", *fbref_raw.shape)

    silver = build_silver_fbref(fbref_raw)
    logger.info("silver_fbref reconstruida: %d filas, %d columnas", *silver.shape)
    print("Columnas resultantes:", list(silver.columns))

    conn = get_connection()
    try:
        _add_missing_columns(conn, "silver_fbref", silver)
    finally:
        conn.close()

    upsert_dataframe(silver, "silver_fbref")
    print(f"\nsilver_fbref actualizada con {len(silver)} filas.")


if __name__ == "__main__":
    main()
