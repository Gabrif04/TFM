'''
El presente Script tiene la finalidad de medir la capacidad ofensiva de los jugadores de la liga 
española demostrada en la última temporada 2025/2026.

Se va a realizar un Scoring/Ranking de dichos jugadores en dicha temporada, para ello se dispone 
de las siguientes variables de cada jugador:
    
    - "player_name" --> Nombre del jugador
    - "position" -> Posición del jugador
    - "minutes_played" --> Minutos jugados en toda la temporada
    - "Performance_Gls" --> Número de Goles en toda la temporada
    - "Performance_Ast" --> Número de Asistencias en toda la temporada
    - "Performance_G+A" --> Número de Goles + Asistencias en toda la temporada
    - "Performance_G-PK" --> Número de Goles - Penalitis en toda la temporada
    - "Performance_misc_Fld" --> Número de Faltas recibidas en toda la temporada
    - "Performance_misc_Off" --> Número de Fueras de juego cometidos en toda la temporada
    - "crosses" --> Número de Centros en toda la temporada

Transformaremos esta variables para obtenerlas por cada 90 minutos.

En este punto, es necesario decidir que peso debe tener cada variable para construir nuestro scoring,
para ello utilizaremos la técnica estadística de Compoentes Principales o PCA. Además, como tenemos 
varias variables que están correladas entre si, como "Performance_Gls" y "Performance_G+A", será útil 
para reducir las dimensiones y no permitir que la misma información puntue varias veces para construir 
el Scoring.

Sin embargo, no podemos comparar directamente la capacidad ofensiva de un delantero con la capacidad 
ofensiva de un defensa. Por este motivo, plantearemos 3 PCAs diferentes diferenciando entre Delanteros, 
Mediocentros y Defensas.
'''

import sqlite3
import json
import numpy as np
import pandas as pd

from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA


# ============================================================
# DATASET y CONFIGURACIÓN
# ============================================================
DB_PATH = "/home/alex/Documentos/Master/TFM/atm_scouting.db"
TABLE_NAME = "bronze_fbref"
SEASON = "2025-2026"

'''
Es posible que haya varios jugadores que han disputado pocos minutos y que pueden distorsionar los resultados.
Por ello, limitamos a 450 minutos el número mínimo de minutos que un jugador ha debido disputar en la temporada 
para contemplarlo en el modelo
'''
MIN_MINUTES = 450

# Se fija en 80 el porcentaje de Varianza acumulada mínima explicada por PCA
VARIANCE_THRESHOLD = 0.80

POSITIONS = ["FW", "MF", "DF"]

# Recuperar los datos
conn = sqlite3.connect(DB_PATH)

df_raw = pd.read_sql(
    f"SELECT payload_json FROM {TABLE_NAME}",
    conn
)

conn.close()

print("Filas:", len(df_raw))
print("Columnas:", len(df_raw.columns))

registros = []

for value in df_raw["payload_json"].dropna():

    try:
        obj = json.loads(value)

        if isinstance(obj, dict):
            registros.append(obj)

        elif isinstance(obj, list):
            registros.extend(obj)

    except Exception:
        continue


df = pd.json_normalize(registros)

print("\nRegistros después de JSON:", len(df))

# Filtramos para usar solo la temporada 25/26
df = df[df["season"] == SEASON].copy()

print("Jugadores/registros:", len(df))

# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

def convertir_numerico(df, columnas):
    """
    Convierte las columnas indicadas a formato numérico.
    Los valores no convertibles pasan a NaN.
    """
    for col in columnas:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def percentile_0_100(series):
    """
    Convierte una variable en percentil 0-100.
    """
    return series.rank(pct=True) * 100


def posicion_principal(position):

    if pd.isna(position):
        return np.nan

    return str(position).split(",")[0].strip()


def winsorize_group(group, variables, lower=0.01, upper=0.99):

    group = group.copy()

    for col in variables:

        q_low = group[col].quantile(lower)
        q_high = group[col].quantile(upper)

        group[col] = group[col].clip(
            lower=q_low,
            upper=q_high
        )

    return group


# ============================================================
# TRANSFORMACIÓN DATASET
# ============================================================
VARIABLES_PCA = [
    "Gls90",
    "Ast90",
    "G_minus_PK90",
    "G_plus_A_minus_PK90",
    "Fld90",
    "Off90",
    "Crosses90"
]

columnas_numericas = [
    "minutes_played",
    "Performance_Gls",
    "Performance_Ast",
    "Performance_G+A",
    "Performance_G-PK",
    "Performance_misc_Fld",
    "Performance_misc_Off",
    "crosses"
]

df = convertir_numerico(
    df,
    columnas_numericas
)

# Como hay varios jugadores catalogados en varias posiciones, se opta por elegir unicamente su posición principal
df["Primary_Position"] = (
    df["position"]
    .apply(posicion_principal)
)

df = df[
    df["Primary_Position"].isin(POSITIONS)
].copy()


# Filtro de minutos mínimos
df = df[
    df["minutes_played"] >= MIN_MINUTES
].copy()

print(
    df["Primary_Position"]
    .value_counts()
)


# Transformación de variables por 90 minutos
df["90s_calc"] = (
    df["minutes_played"] / 90
)

# Goles por 90
df["Gls90"] = (
    df["Performance_Gls"] /
    df["90s_calc"]
)


# Asistencias por 90
df["Ast90"] = (
    df["Performance_Ast"] /
    df["90s_calc"]
)


# Goles sin penalti por 90
df["G_minus_PK90"] = (
    df["Performance_G-PK"] /
    df["90s_calc"]
)


# Goles + asistencias sin penalti por 90
df["G_plus_A_minus_PK90"] = (
    (
        df["Performance_G-PK"] +
        df["Performance_Ast"]
    )
    / df["90s_calc"]
)

# Faltas recibidas por 90
df["Fld90"] = (
    df["Performance_misc_Fld"] /
    df["90s_calc"]
)

# Fueras de juego cometidos por 90
df["Off90"] = (
    df["Performance_misc_Off"] /
    df["90s_calc"]
)


# Centros por 90
df["Crosses90"] = (
    df["crosses"] /
    df["90s_calc"]
)


# ============================================================
# Análisis descriptivo variables
# ============================================================

# La técnica de Compoentes Principales es especialmente sensible a los valores perdidos, hacemos una busqueda 
# de ellos y en caso e encontrarlos los eliminamos
print(
    df[VARIABLES_PCA]
    .describe()
    .T
)
# No se encuantran valores missings

# PCA también es sensible a valores outliers, por ello aplicamos una Winsorización para eliminar la influencia
# de valores extremos. Como cada posición presenta distribuciones diferentes, lo aplicamos por posición
df_wins = (
    df
    .groupby("Primary_Position", group_keys=False)
    .apply(
        lambda x: winsorize_group(
            x,
            VARIABLES_PCA
        )
    )
    .reset_index(drop=True)
)


# ============================================================
# PCA POR POSICIÓN
# ============================================================

resultados_ranking = []
resultados_loadings = []
resultados_variance = []
resultados_scores_componentes = []
resultados_correlaciones = []


for position in POSITIONS:

    print(f"PCA - POSICIÓN: {position}")

    data_pos = df_wins[
        df_wins["Primary_Position"] == position
    ].copy()

    X = data_pos[
        VARIABLES_PCA
    ].copy()


    # Aplicamos estandarización por posición de manera independiente
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    #PCA
    pca_full = PCA()

    X_pca_full = pca_full.fit_transform(
        X_scaled
    )


    explained = (
        pca_full.explained_variance_ratio_
    )

    cumulative = np.cumsum(
        explained
    )

    n_components = np.argmax(
        cumulative >= VARIANCE_THRESHOLD
    ) + 1


    print(
        f"\nComponentes retenidas: "
        f"{n_components}"
    )

    print(
        f"Varianza explicada acumulada: "
        f"{cumulative[n_components - 1]:.4f}"
    )


    pca = PCA(
        n_components=n_components
    )

    component_scores = pca.fit_transform(
        X_scaled
    )


    for i, var in enumerate(
        pca.explained_variance_ratio_,
        start=1
    ):

        resultados_variance.append({
            "Position": position,
            "Component": f"PC{i}",
            "Explained_Variance": var,
            "Cumulative_Variance": sum(
                pca.explained_variance_ratio_[:i]
            )
        })

    loadings = (
        pca.components_.T
    )


    for variable_idx, variable in enumerate(
        VARIABLES_PCA
    ):

        row = {
            "Position": position,
            "Variable": variable
        }

        for component_idx in range(
            n_components
        ):

            row[
                f"PC{component_idx + 1}"
            ] = loadings[
                variable_idx,
                component_idx
            ]

        resultados_loadings.append(row)


    for i in range(
        n_components
    ):

        data_pos[
            f"PC{i + 1}"
        ] = component_scores[:, i]

    #Pesos
    weights = (
        pca.explained_variance_ratio_ /
        pca.explained_variance_ratio_.sum()
    )

    #Score
    data_pos["PCA_raw"] = 0

    for i in range(
        n_components
    ):

        data_pos["PCA_raw"] += (
            data_pos[f"PC{i + 1}"] *
            weights[i]
        )


    mean_offensive = X_scaled.mean(axis=1)

    correlation = np.corrcoef(
        data_pos["PCA_raw"],
        mean_offensive
    )[0, 1]


    if correlation < 0:

        data_pos["PCA_raw"] *= -1

        for i in range(
            n_components
        ):
            data_pos[
                f"PC{i + 1}"
            ] *= -1


    data_pos["Offensive_Score"] = (
        percentile_0_100(
            data_pos["PCA_raw"]
        )
    )


    data_pos = data_pos.sort_values(
        "Offensive_Score",
        ascending=False
    ).reset_index(drop=True)


    data_pos["Rank"] = (
        np.arange(len(data_pos)) + 1
    )

    #Guardamos resultados
    columnas_resultado = [
        "player_name",
        "team",
        "season",
        "Primary_Position",
        "minutes_played",

        "Performance_Gls",
        "Performance_Ast",
        "Performance_G+A",
        "Performance_G-PK",   
        "Performance_misc_Fld",
        "Performance_misc_Off",

        "Gls90",
        "Ast90",
        "G_minus_PK90",
        "G_plus_A_minus_PK90",
        "Fld90",
        "Off90",
        "Crosses90",

        "PCA_raw",
        "Offensive_Score",
        "Rank"
    ]

    columnas_resultado = [
        c for c in columnas_resultado
        if c in data_pos.columns
    ]

    resultados_ranking.append(
        data_pos[columnas_resultado]
    )


    columnas_pc = [
        f"PC{i + 1}"
        for i in range(n_components)
    ]

    component_df = data_pos[
        [
            "player_name",
            "team",
            "Primary_Position"
        ] + columnas_pc
    ].copy()

    resultados_scores_componentes.append(
        component_df
    )

ranking_final = pd.concat(
    resultados_ranking,
    ignore_index=True
)


ranking_final = ranking_final.sort_values(
    [
        "Primary_Position",
        "Offensive_Score"
    ],
    ascending=[
        True,
        False
    ]
)


loadings_final = pd.DataFrame(
    resultados_loadings
)

print(f"Loadings:")

print("===== FW =====")
print(loadings_final[loadings_final["Position"] == "FW"])

'''
===== FW =====
  Position             Variable       PC1       PC2       PC3       PC4
0       FW                Gls90  0.541564 -0.037776 -0.012910 -0.072917
1       FW                Ast90 -0.060372  0.755872  0.333148 -0.088140
2       FW         G_minus_PK90  0.552605  0.001811 -0.041247 -0.080618
3       FW  G_plus_A_minus_PK90  0.492573  0.383441  0.132003 -0.117774
4       FW                Fld90 -0.200225  0.503315 -0.405729  0.467282
5       FW                Off90  0.102878 -0.162785  0.666685  0.716461
6       FW            Crosses90 -0.323094  0.019372  0.510524 -0.484639

La primera compoente para los delanteroes está claramente asociada a la Producción Goleadora como tal, la capacidad 
del jugador para anotar Gol. Por otro lado la PC2 tiene un indice superior en las asistencias y las faltas recibidas, 
lo que está muy asociado con la creación de oprtunidades de gol. La PC3 presenta cargas elevadas en los fueras de 
juego y los centros, por lo que parece representar aspectos relacionados con la movilidad ofensiva y la búsqueda 
de profundidad. Finalmente, la PC4 está especialmente asociada con los fueras de juego y, en sentido contrario, 
con los centros, por lo que puede interpretarse como una dimensión adicional relacionada con el desmarque y la 
ocupación de espacios en profundidad.
'''

print("===== MF =====")
print(loadings_final[loadings_final["Position"] == "MF"])

'''
===== MF =====
   Position             Variable       PC1       PC2       PC3       PC4
7        MF                Gls90  0.474515 -0.405751 -0.009924  0.114616
8        MF                Ast90  0.355290  0.467449 -0.170044 -0.497682
9        MF         G_minus_PK90  0.480594 -0.407991 -0.054379  0.072633
10       MF  G_plus_A_minus_PK90  0.525599  0.050118 -0.151562 -0.272836
11       MF                Fld90  0.072173 -0.091614  0.930295 -0.345532
12       MF                Off90  0.293808  0.213261  0.237717  0.699391
13       MF            Crosses90  0.223266  0.627707  0.151986  0.225656

La primera componente para los centrocampistas está claramente asociada con la producción ofensiva, ya que 
presenta cargas elevadas en los goles, los goles sin penalti y, especialmente, en la combinación de goles y 
asistencias sin penalti. Por otro lado, la PC2 está principalmente relacionada con las asistencias y los 
centros, lo que parece representar una dimensión vinculada con la creación de oportunidades de gol y la 
participación en la generación ofensiva. La PC3 está fuertemente asociada con las faltas recibidas, por lo que 
puede interpretarse como una dimensión relacionada con la capacidad del jugador para generar contacto y 
participar activamente en acciones ofensivas. Finalmente, la PC4 presenta una carga elevada en los fueras de 
juego, por lo que parece representar otro aspecto del juego relacionado con la movilidad ofensiva y la búsqueda
de profundidad.
'''

print("===== DF =====")
print(loadings_final[loadings_final["Position"] == "DF"])

'''
===== DF =====
   Position             Variable       PC1       PC2       PC3
14       DF                Gls90  0.441200 -0.458088  0.086144
15       DF                Ast90  0.380237  0.425035 -0.294940
16       DF         G_minus_PK90  0.443498 -0.455732  0.083248
17       DF  G_plus_A_minus_PK90  0.548421  0.041301 -0.159395
18       DF                Fld90  0.148442  0.259700  0.932530
19       DF                Off90  0.306856  0.211688 -0.002292
20       DF            Crosses90  0.217053  0.536513 -0.060295

La primera componente para los defensas está claramente asociada con la producción ofensiva, ya que presenta 
cargas elevadas en los goles, los goles sin penalti y, especialmente, en la combinación de goles y asistencias 
sin penalti. Por otro lado, la PC2 está principalmente relacionada con las asistencias y los centros, lo que 
parece representar una dimensión vinculada con la creación de oportunidades y la participación ofensiva desde 
posiciones más alejadas del área. Finalmente, la PC3 está fuertemente asociada con las faltas recibidas, por lo 
que parece representar una dimensión relacionada con la capacidad del jugador para generar contacto y participar 
en acciones ofensivas. En el caso de los defensas, a diferencia de los centrocampistas y delanteros, los fueras 
de juego no presentan una carga relevante en ninguna de las componentes, por lo que no parecen constituir una 
dimensión diferenciada dentro de su perfil ofensivo.

'''

variance_final = pd.DataFrame(
    resultados_variance
)

print(f"Varianza:")

print("===== FW =====")
print(variance_final[variance_final["Position"] == "FW"])

print("===== MF =====")
print(variance_final[variance_final["Position"] == "MF"])

print("===== DF =====")
print(variance_final[variance_final["Position"] == "DF"])


component_scores_final = pd.concat(
    resultados_scores_componentes,
    ignore_index=True
)


#TOP 10 DE CADA POSICIÓN

print("\n")
print("=" * 70)
print("TOP 10 - FW")
print("=" * 70)

print(
    ranking_final[
        ranking_final["Primary_Position"] == "FW"
    ][
        [
            "Rank",
            "player_name",
            "team",
            "Offensive_Score"
        ]
    ]
    .head(10)
    .to_string(index=False)
)


print("\n")
print("=" * 70)
print("TOP 10 - MF")
print("=" * 70)

print(
    ranking_final[
        ranking_final["Primary_Position"] == "MF"
    ][
        [
            "Rank",
            "player_name",
            "team",
            "Offensive_Score"
        ]
    ]
    .head(10)
    .to_string(index=False)
)


print("\n")
print("=" * 70)
print("TOP 10 - DF")
print("=" * 70)

print(
    ranking_final[
        ranking_final["Primary_Position"] == "DF"
    ][
        [
            "Rank",
            "player_name",
            "team",
            "Offensive_Score"
        ]
    ]
    .head(10)
    .to_string(index=False)
)


# Expotar(coemntado)

ranking_final.to_csv(
    "ranking_ofensivo_2025_26.csv",
    index=False
)


# Rankings independientes
for position in POSITIONS:

    ranking_final[
        ranking_final["Primary_Position"] == position
    ].to_csv(
        f"ranking_ofensivo_{position}_2025_26.csv",
        index=False
    )

# Loadings
loadings_final.to_csv(
    "pca_ofensiva_loadings_2025_26.csv",
    index=False
)

#Varianza
variance_final.to_csv(
    "pca_ofensiva_variance_2025_26.csv",
    index=False
)
