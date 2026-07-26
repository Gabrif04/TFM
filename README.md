## 1. Requisitos previos

- **Python 3.11+**
- **Google Chrome** instalado — lo usa `selenium` (vía `soccerdata`) para extraer WhoScored
- Claves de API gratuitas (opcionales pero recomendadas):
  - [football-data.org](https://www.football-data.org/client/register) → `FOOTBALL_DATA_API_KEY`
  - [API-Football](https://www.api-football.com/) → `API_FOOTBALL_KEY`

---

## 2. Configuración del entorno

Desde la raíz del proyecto:

```powershell
# Crear entorno virtual
python -m venv venv

# Activar entorno virtual (Windows / PowerShell)
venv\Scripts\Activate.ps1

# Instalar dependencias
pip install -r requirements.txt
```

### Variables de entorno

Copia `.env.example` a `.env` y rellena tus claves:

```powershell
Copy-Item .env.example .env
```

```
FOOTBALL_DATA_API_KEY=tu_clave_aqui
API_FOOTBALL_KEY=tu_clave_aqui
```

Si dejas alguna clave vacía, el pipeline sigue funcionando pero esa fuente concreta no traerá datos (football-data.org y API-Football).

### Inicializar la base de datos

Crea el esquema (tablas bronze/silver) en `data/atm_scouting.db`:

```powershell
python -c "from utils.database import init_db; init_db()"
```

---

## 3. Lanzar el pipeline

El pipeline principal (`pipeline_main.py`) orquesta la extracción bronze→silver de FBref, Understat, equipos/standings, Transfermarkt y WhoScored para las ligas y temporada indicadas.

### Uso básico

```powershell
python pipeline_main.py --leagues ESP --season 2025-2026
```

Esto extrae **la liga completa** (todos los jugadores de La Liga), lo que implica cientos de búsquedas contra Transfermarkt (rate-limited a 1 cada ~3s) y, si no se acota, el calendario completo de WhoScored (~380 partidos, 1 cada 5s) — puede tardar **30-60+ minutos**.

### `--top-n`: la forma rápida de probar el pipeline

`--top-n N` limita Transfermarkt a los **N jugadores con más minutos jugados** de la extracción (en vez de buscar a todos los jugadores de la liga). Es la manera recomendada de probar cambios o ejecutar el pipeline sin esperar decenas de minutos:

```powershell
python pipeline_main.py --leagues ESP --season 2025-2026 --top-n 20
```

Con `--top-n 20`, en vez de ~600 búsquedas en Transfermarkt solo se hacen 20 (unos ~2 minutos en vez de 30-60). FBref/Understat/equipos/standings siempre se extraen completos independientemente de este flag — solo afecta a Transfermarkt.

Para acotar también WhoScored (que es independiente de `--top-n`), usa `--whoscored-max-matches`:

```powershell
python pipeline_main.py --leagues ESP --season 2025-2026 --top-n 20 --whoscored-max-matches 5
```

Esto limita WhoScored a los 5 primeros partidos del calendario en vez de la temporada completa.

### Otras opciones útiles

```powershell
# Histórico multi-temporada (FBref/Understat), 5 temporadas hacia atrás desde --season
python pipeline_main.py --leagues ESP --season 2025-2026 --seasons-back 5 --top-n 20

# Varias ligas a la vez (por defecto usa todas las configuradas en config.py)
python pipeline_main.py --leagues ESP,ENG,ITA --top-n 20

# Además, transferencias/lesiones vía API-Football (consume cuota diaria ~100/día)
python pipeline_main.py --leagues ESP --top-n 20 --run-api-football --api-football-top-n 10

# Además, histórico de valor de mercado de Transfermarkt (1 petición extra/jugador)
python pipeline_main.py --leagues ESP --top-n 20 --run-market-value-history --market-value-history-top-n 10
```

| Flag | Qué hace |
|---|---|
| `--leagues` | Códigos de liga separados por coma (`ESP,ENG,...`). Por defecto, todas las de `config.py`. |
| `--season` | Temporada final a extraer, formato `YYYY-YYYY`. |
| `--seasons-back N` | Extrae N temporadas hacia atrás desde `--season` (histórico para el futuro modelo predictivo). |
| `--top-n N` | **Recomendado en pruebas.** Limita Transfermarkt a los N jugadores con más minutos. |
| `--whoscored-max-matches N` | Limita WhoScored a los N primeros partidos del calendario. |
| `--run-api-football` | Ejecuta además transfers/injuries vía API-Football (opt-in, consume cuota diaria). |
| `--run-market-value-history` | Ejecuta además el histórico de valor de mercado de Transfermarkt (opt-in). |

### Verificar los resultados

```powershell
python -c "from utils.database import read_table; print(read_table('silver_fbref').head())"
O instalar DB Browser for SQLite para ver tablas en aplicativoy lanzar consultas SQL.
```

Los logs de cada ejecución quedan en `logs/pipeline.log`.

---

## 4. Probar extractores por separado

```powershell
python -m extractors.football_data_api
python -m extractors.soccerdata_extractor
python -m extractors.transfermarkt_extractor
python -m extractors.whoscored_extractor
```

---

## 5. Estructura del proyecto

```
TFM/
├── config.py              Configuración (ligas, temporada por defecto, claves API)
├── pipeline_main.py        Orquestador del pipeline
├── requirements.txt
├── .env / .env.example
├── extractors/              Un extractor por fuente de datos
├── transform/                Limpieza (cleaning.py) y construcción de tablas silver (silver.py)
├── utils/                     Logger, acceso a BBDD, validaciones de calidad
├── data/
│   └── atm_scouting.db      SQLite, arquitectura medallón (bronze/silver)
└── logs/
    └── pipeline.log
```
