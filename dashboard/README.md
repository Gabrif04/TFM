# Scouting Lab

Desde la raíz del repositorio:

```powershell
python -m pip install -r dashboard/requirements.txt
python -m streamlit run dashboard/app.py
```

Abre `http://localhost:8501`. El tema oscuro y la conexión del servidor se
configuran en `.streamlit/config.toml`.

## Compartir el dashboard

En la misma red Wi-Fi, otros dispositivos pueden abrir la dirección `Network URL`
que muestra Streamlit al arrancar. El ordenador debe permanecer encendido y el
proceso de Streamlit, abierto. Esta dirección no funciona desde otra red.

Para compartir una URL estable por internet, publica la aplicación en Streamlit
Community Cloud:

1. Sube a GitHub `.streamlit/`, `dashboard/` y `salida_modelos/`. No hace falta
   subir la base de datos ni el pipeline para ejecutar el visual.
2. En `share.streamlit.io`, crea una aplicación desde ese repositorio y rama.
3. Usa `dashboard/app.py` como archivo de entrada.
4. Comparte la URL `https://...streamlit.app` resultante. Si la aplicación es
   privada, invita a cada compañero desde los ajustes de acceso.

El repositorio incluye versiones fijadas en `dashboard/requirements.txt` para que
el entorno publicado reproduzca el entorno probado localmente.

La aplicación usa exclusivamente los CSV de `salida_modelos/`. La carga comprueba
columnas, identidad de las observaciones y valores numéricos. Los cambios de los
CSV invalidan la caché en la siguiente interacción o recarga de la aplicación.
No ejecuta el pipeline ni consulta SQLite.

- **Datos:** cobertura, diccionario, ausentes y evaluación sobre log(1 + valor).
- **Buscador y perfil:** búsqueda sin distinguir tildes ni mayúsculas, selección
  por jugador/equipo/liga/temporada y comparación entre mercado y modelo.
- **Ranking:** filtros, selector de modelo, orden ascendente/descendente, top
  10/20/25/50, apertura de perfiles, gráfico y descarga del top.

Las diferencias se calculan como estimación menos mercado. El porcentaje utiliza
el mercado como denominador. Los campos `residuo_*` del CSV son cocientes
mercado/estimación. Scouting no cubre los porteros de la muestra. No se interpreta
una diferencia como evidencia suficiente de una oportunidad de fichaje.

No se dispone del entrenamiento, del protocolo de validación ni de un scoring.
La aplicación muestra las estimaciones entregadas y no produce nuevas predicciones.

## Identidad visual

El perfil incluye foto, escudo del club, bandera del país de la liga, calendario e
icono de posición. Las banderas y los iconos son SVG propios; el punto del pequeño
campo indica la zona asociada a cada posición. La bandera no representa la
nacionalidad del jugador.

Fotos y escudos se cargan exclusivamente desde `assets/media/`, sin llamadas de
red al abrir perfiles. `manifest.json` conserva autor, licencia y fuente para el
panel de créditos. La foto se asocia a la observación completa, evitando confundir
homónimos. Cuando falta una imagen confirmada se usa una silueta o escudo neutro.

La prueba de fotos selecciona cinco observaciones de mayor valor por liga.
Las fotos pueden ser de otras fechas o equipaciones; el equipo mostrado siempre
es el del CSV. El CSV deportivo no se modifica.

El script independiente `scripts/prepare_media.py` permite descubrir candidatos
de Wikimedia y descargar únicamente los aprobados en `assets/media/catalog.json`.
La aprobación de ese catálogo implica revisar que la entidad sea la persona o
club correcto. No se ejecuta al iniciar Streamlit.

Pruebas funcionales:

```powershell
python -m unittest discover -s dashboard/tests -v
```
