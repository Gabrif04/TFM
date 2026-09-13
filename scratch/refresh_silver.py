import sqlite3
import pandas as pd
import json
from transform.silver import build_silver_fbref, build_silver_understat
from utils.database import upsert_dataframe

conn = sqlite3.connect('data/atm_scouting.db')

# 1. Update FBref (mainly to fix positions since bronze contains raw positions and payload)
print("Reprocesando FBref...")
bronze_fbref = pd.read_sql("SELECT * FROM bronze_fbref", conn)
# We need to recreate the raw dataframe from bronze_fbref to pass to build_silver_fbref
raw_fbref_list = []
for _, row in bronze_fbref.iterrows():
    try:
        data = json.loads(row['payload_json'])
        data['player_name'] = row['player_name']
        data['team'] = row['team']
        data['league'] = row['league']
        data['season'] = row['season']
        raw_fbref_list.append(data)
    except:
        pass
if raw_fbref_list:
    raw_fbref_df = pd.DataFrame(raw_fbref_list)
    silver_fbref = build_silver_fbref(raw_fbref_df)
    upsert_dataframe(silver_fbref, "silver_fbref")
    print(f" -> FBref procesado: {len(silver_fbref)} filas")

# 2. Update Understat (to extract the newly promoted columns)
print("Reprocesando Understat...")
bronze_understat = pd.read_sql("SELECT * FROM bronze_understat", conn)
raw_u_list = []
for _, row in bronze_understat.iterrows():
    try:
        data = json.loads(row['payload_json'])
        data['player_name'] = row['player_name']
        data['team'] = row['team']
        data['league'] = row['league']
        data['season'] = row['season']
        raw_u_list.append(data)
    except:
        pass
if raw_u_list:
    raw_u_df = pd.DataFrame(raw_u_list)
    silver_understat = build_silver_understat(raw_u_df)
    upsert_dataframe(silver_understat, "silver_understat")
    print(f" -> Understat procesado: {len(silver_understat)} filas")

conn.close()
print("¡Actualización de datos locales completada!")
