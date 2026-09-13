"""Three views sharing CSV data, model selection and explicit observation identity."""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from components.profile_identity import render_profile_identity, render_credits

from data.db import (KEY, LABELS, MODELS, load_players, load_metrics, with_model,
                     rank_players, search_key, fmt_market_value)

GREEN = "#55d6b0"
BLUE = "#73a9ff"
LABELS = {**LABELS, **{col: label.replace("(€)", "(M)") for col, label in LABELS.items()
                      if col in ["market_value_eur", "pred_general_eur", "pred_scouting_eur", "estimate", "difference"]}}
LEAGUES = {"ESP": "España", "ENG": "Inglaterra", "ITA": "Italia", "GER": "Alemania",
           "FRA": "Francia", "POR": "Portugal", "NED": "Países Bajos"}
PER90 = ["goals_p90", "assists_p90", "xg_p90", "xa_p90", "tackles_p90",
         "interceptions_p90", "crosses_p90", "fouls_committed_p90",
         "fouls_drawn_p90", "yellow_cards_p90"]
SORT_COLUMNS = ["market_value_eur", "estimate", "difference", "difference_pct", "age",
                "minutes_played", "matches_played", *PER90, "penalties_scored", "starts_ratio",
                "contract_years_left", "height_cm", "team_points", "team_position"]


def dataset():
    try:
        df, warnings = load_players()
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        st.error(f"No se pueden cargar los jugadores: {exc}")
        st.stop()
    for warning in warnings:
        st.warning(warning)
    return df


def chart(fig, height=340):
    fig.update_layout(template="plotly_dark", paper_bgcolor="#192230", plot_bgcolor="#192230",
                      font=dict(color="#edf2f7"), margin=dict(l=24, r=24, t=40, b=24), height=height)
    st.plotly_chart(fig, width="stretch", config={
        "displaylogo": False,
        "responsive": True,
        "scrollZoom": False,
    })


def number(value, decimals=0):
    if pd.isna(value):
        return "-"
    return f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")


def model_selector():
    # Separate durable state from widget state, which Streamlit clears on navigation.
    options = list(MODELS)
    current = st.session_state.get("chosen_model", "General")
    selected = st.sidebar.selectbox("Modelo de valoración", options, index=options.index(current),
                            help="General: incluye contexto de equipo y liga según el CSV. "
                                 "Scouting: descrito como rendimiento individual; sin predicción para porteros.")
    st.session_state["chosen_model"] = selected
    return selected


def filters(df, prefix, market=False):
    saved = st.session_state.get(prefix + "_filters", {})
    values = {}
    with st.sidebar:
        st.subheader("Filtros")
        available = df
        for col in ["league", "team", "position_group", "season"]:
            options = sorted(available[col].dropna().unique())
            initial = [x for x in saved.get(col, []) if x in options]
            widget_key = prefix + "_" + col
            if widget_key in st.session_state:
                # Drop incompatible downstream selections before rendering their widget.
                selected = st.session_state[widget_key]
                valid = [x for x in selected if x in options]
                if valid != selected:
                    st.session_state[widget_key] = valid
                initial = None
            values[col] = st.multiselect(
                LABELS[col], options, default=initial, key=widget_key,
                format_func=(lambda x: LEAGUES.get(x, x)) if col == "league" else str,
                placeholder="Todos")
            if values[col]:
                available = available[available[col].isin(values[col])]
        for name, label, default in [("age_min", "Edad mínima", 0.0),
                                     ("age_max", "Edad máxima", 100.0),
                                     ("minutes", "Minutos mínimos", 0.0)]:
            values[name] = st.number_input(label, min_value=0.0,
                value=float(saved.get(name, default)), step=1.0, format="%.0f", key=prefix + "_" + name)
        if market:
            values["market_max"] = st.number_input("Valor máximo (M); 0 = sin límite",
                min_value=0.0, value=float(saved.get("market_max", 0)), step=0.1, format="%.1f",
                key=prefix + "_market_max")
        if st.button("Restablecer filtros", key=prefix + "_reset"):
            st.session_state.pop(prefix + "_filters", None)
            for name in values:
                st.session_state.pop(prefix + "_" + name, None)
            st.rerun()
    st.session_state[prefix + "_filters"] = values
    mask = pd.Series(True, index=df.index)
    for col in ["league", "team", "position_group", "season"]:
        if values[col]:
            mask &= df[col].isin(values[col])
    # Missing numeric data remains visible when no corresponding restriction is applied.
    if values["age_min"] > 0:
        mask &= df.age.ge(values["age_min"])
    if values["age_max"] < 100:
        mask &= df.age.le(values["age_max"])
    if values["minutes"] > 0:
        mask &= df.minutes_played.ge(values["minutes"])
    if market and values["market_max"] > 0:
        mask &= df.market_value_eur.le(values["market_max"] * 1_000_000)
    if values["age_min"] > values["age_max"]:
        st.warning("La edad mínima supera a la máxima. Ajusta el intervalo.")
    return df.loc[mask].copy()


def overview():
    df = dataset()
    st.title("Datos que dan contexto")
    st.caption("Una muestra de jugadores, dos estimaciones de valor y una lectura transparente de sus límites.")
    for container, label, value in zip(st.columns(3),
            ["Observaciones", "Ligas", "Temporadas"],
            [len(df), df.league.nunique(), df.season.nunique()]):
        container.metric(label, number(value))
    st.markdown("Cada observación corresponde a un **jugador, equipo, liga y temporada**. "
                "Un jugador puede tener varios registros si aparece en distintos equipos. "
                "El valor de mercado es la referencia recogida en la muestra; no es un precio de traspaso "
                "ni una cotización actualizada en directo.")
    a, b = st.columns(2)
    with a:
        st.subheader("Cobertura por liga")
        counts = df.groupby("league").size().rename("Registros").reset_index()
        counts["Liga"] = counts.league.map(lambda x: LEAGUES.get(x, x))
        chart(px.bar(counts, x="Liga", y="Registros", color_discrete_sequence=[GREEN]))
    with b:
        st.subheader("Distribución por posición")
        counts = df.groupby("position_group").size().rename("Registros").reset_index()
        chart(px.bar(counts, x="Registros", y="position_group", orientation="h",
                     labels={"position_group": "Posición"}, color_discrete_sequence=[BLUE]))
    st.subheader("Cómo leer las valoraciones")
    st.markdown("**General** incorpora equipo y liga según la descripción entregada. "
                "**Scouting** está descrito como basado en rendimiento individual. "
                "El selector de las otras vistas permite explorar ambas estimaciones.")
    st.info("Diferencia (€) = estimación − valor de mercado. "
            "Diferencia (%) = diferencia / valor de mercado × 100. "
            "Una diferencia positiva indica una estimación superior al mercado; por sí sola no demuestra una oportunidad de fichaje.")
    with st.expander("Evaluación de los modelos", expanded=True):
        try:
            metrics = load_metrics().copy()
            metrics["ape_mediano"] *= 100
            st.dataframe(metrics.rename(columns={
                "modelo": "Modelo", "n": "Observaciones", "r2": "R² · log1p",
                "mae": "MAE · log1p", "rmse": "RMSE · log1p",
                "ape_mediano": "Error porcentual mediano (%)"}),
                hide_index=True, width="stretch")
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            st.warning(f"Métricas no disponibles: {exc}")
        st.caption("R², MAE y RMSE se reproducen aplicando log(1 + valor) a mercado y estimación; "
                   "MAE y RMSE no están expresados en euros. No consta si la evaluación es de entrenamiento, "
                   "test o validación cruzada. No se dispone del código ni de la fecha de referencia del modelo.")
    st.caption("Fuentes exclusivas: resultados_jugadores.csv y metricas_modelos.csv · salida_modelos/")


def comparison_circles(row, model):
    valid = pd.notna(row.estimate) and pd.notna(row.market_value_eur) and row.market_value_eur > 0
    ratio = row.estimate / row.market_value_eur if valid else None
    arrow = "↑" if valid and ratio > 1 else "↓" if valid and ratio < 1 else "→" if valid else "—"
    color = GREEN if valid and ratio > 1 else "#ff9b9b" if valid and ratio < 1 else "#b7c5d8"
    percentage = abs((ratio - 1) * 100) if valid else None
    percentage_text = number(percentage, 1) + " %" if valid else "-"
    st.html(f"""
    <style>
    .valuation-comparison {{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) minmax(0,.85fr);
        align-items:center;gap:10px;min-height:280px;padding:20px 0;}}
    .valuation-circle {{border:3px solid {BLUE};border-radius:50%;width:100%;max-width:155px;box-sizing:border-box;
        aspect-ratio:1;display:flex;flex-direction:column;align-items:center;justify-content:center;
        background:#192230;flex-shrink:0;}}
    .valuation-circle.model {{border-color:{color};}}
    .valuation-circle strong {{font-size:clamp(1rem,1.5vw,1.4rem);color:#edf2f7;white-space:nowrap;}}
    .valuation-circle span {{color:#b7c5d8;font-size:.85rem;}}
    .valuation-ratio {{text-align:center;color:{color};}}
    .valuation-ratio strong {{display:block;font-size:1.4rem;white-space:nowrap;}}
    .valuation-ratio small {{color:#b7c5d8;}}
    @media(max-width:600px) {{
        .valuation-comparison {{grid-template-columns:minmax(0,1fr) minmax(0,1fr);
            min-height:0;gap:14px 8px;padding:12px 0 20px;}}
        .valuation-circle {{max-width:140px;justify-self:center;}}
        .valuation-ratio {{grid-column:1 / -1;}}
    }}
    </style>
    <div class="valuation-comparison">
      <div class="valuation-circle"><strong>{fmt_market_value(row.market_value_eur)}</strong><span>Mercado</span></div>
      <div class="valuation-circle model"><strong>{fmt_market_value(row.estimate)}</strong><span>{model}</span></div>
      <div class="valuation-ratio"><strong>{arrow} {percentage_text}</strong><small>Respecto al mercado</small></div>
    </div>
    """)


def profile(row, model):
    st.divider()
    credits = render_profile_identity(row)
    if pd.isna(row.estimate):
        st.info("Este registro no tiene estimación del modelo seleccionado. "
                "El CSV no contiene predicciones de scouting para porteros.")
    elif pd.isna(row.market_value_eur):
        st.info("Sin valor de mercado de referencia para comparar.")
    left, right = st.columns([1, 1])
    with left:
        st.subheader("Mercado y modelo")
        comparison_circles(row, model)
    with right:
        st.subheader("Ficha del jugador")
        fields = ["age", "minutes_played", "matches_played", "height_cm", "foot",
                  "contract_years_left", "starts_ratio", "team_points", "team_position"]
        values = []
        for col in fields:
            val = row[col]
            display = "-" if pd.isna(val) else str(val) if col == "foot" else number(val, 2 if col in ["contract_years_left", "starts_ratio"] else 0)
            if col == "height_cm" and pd.notna(val):
                display = number(val) + " cm"
            values.append({"Dato": LABELS[col], "Valor": display})
        st.dataframe(pd.DataFrame(values), hide_index=True, width="stretch")
    st.subheader("Rendimiento por 90 minutos")
    for offset in range(0, len(PER90), 5):
        for container, col in zip(st.columns(5), PER90[offset:offset + 5]):
            container.metric(LABELS[col], number(row[col], 2))
    st.caption("Las tasas describen frecuencia, no una puntuación de calidad. "
               "Entradas corresponde a entradas ganadas. No hay métricas específicas suficientes para evaluar porteros.")
    render_credits(credits)


def explorer():
    df = dataset()
    st.title("Encuentra a tu próximo jugador")
    st.caption("Busca un nombre, acota la muestra y explora cada observación por separado.")
    model = model_selector()
    pending = st.session_state.pop("pending_record", None)
    if pending:
        st.session_state.pop("record_picker", None)
        st.session_state.pop("search_filters", None)
        for col in ["league", "team", "season", "position_group", "age_min", "age_max", "minutes"]:
            st.session_state.pop("search_" + col, None)
        st.session_state["player_query"] = ""
        st.session_state["selected_record"] = pending
    query = st.text_input("Buscar jugador", key="player_query", placeholder="Escribe un nombre: Mbappé, Pedri…")
    filtered = filters(with_model(df, model), "search")
    if query.strip():
        filtered = filtered[filtered.search_name.str.contains(search_key(query.strip()), regex=False, na=False)]
    st.caption(f"{len(filtered):,} observaciones · {filtered.player_name.nunique():,} nombres distintos".replace(",", "."))
    if filtered.empty:
        st.info("No hay jugadores con estos filtros. Prueba otro nombre o restablece los filtros.")
        return
    filtered = filtered.sort_values(KEY)
    options = filtered.record_id.tolist()
    previous = st.session_state.get("selected_record")
    if st.session_state.get("record_picker") not in options:
        st.session_state.pop("record_picker", None)
    index = options.index(previous) if previous in options else 0
    selected = st.selectbox("Jugador · equipo · liga · temporada", options, index=index, key="record_picker")
    st.session_state["selected_record"] = selected
    profile(filtered.loc[filtered.record_id.eq(selected)].iloc[0], model)


def ranking():
    df = dataset()
    st.title("El ranking, a tu medida")
    st.caption("Ordena la muestra por valor, diferencia o rendimiento. Abre cualquier observación para consultar su perfil.")
    model = model_selector()
    filtered = filters(with_model(df, model), "ranking", market=True)
    with st.sidebar:
        metric = st.selectbox("Ordenar por", SORT_COLUMNS, format_func=lambda x: LABELS[x])
        direction = st.selectbox("Sentido", ["Mayor a menor", "Menor a mayor"])
        top_n = st.selectbox("Tamaño del top", [10, 20, 25, 50])
    excluded = int(filtered[metric].isna().sum())
    ranked = rank_players(filtered, metric, direction == "Menor a mayor", top_n)
    st.caption(f"{len(filtered)} observaciones filtradas · {excluded} sin {LABELS[metric].lower()} "
               f"excluidas del ranking · mostrando {len(ranked)}")
    if ranked.empty:
        st.info("No hay observaciones disponibles para esta combinación de filtros y métrica.")
        return
    columns = ["player_name", "team", "league", "season", "position_group", "age",
               "minutes_played", "market_value_eur", "estimate", "difference", "difference_pct"]
    if metric not in columns:
        columns.append(metric)
    display = ranked[columns].copy()
    for col in ["market_value_eur", "estimate", "difference"]:
        display[col] = display[col] / 1_000_000
    display["difference_pct"] = display["difference_pct"].round(1)
    if metric in PER90 + ["starts_ratio", "contract_years_left"]:
        display[metric] = display[metric].round(2)
    display = display.rename(columns=LABELS).reset_index(drop=True)
    display.insert(0, "Puesto", range(1, len(display) + 1))
    money = [LABELS[c] for c in ["market_value_eur", "estimate", "difference"]]
    formats = {label: (lambda x: number(x, 1) + " M") for label in money}
    if "height_cm" in columns:
        formats[LABELS["height_cm"]] = lambda x: number(x) + " cm"
    styled = display.style.format(formats, na_rep="-", precision=2, decimal=",", thousands=".")
    event = st.dataframe(styled, hide_index=True, width="stretch",
                         on_select="rerun", selection_mode="single-row",
                         key="ranking_table_" + str(pd.util.hash_pandas_object(ranked[["record_id", metric]], index=False).sum()))
    st.caption("Selecciona una fila y pulsa Abrir perfil. Los valores ausentes se muestran como -.")
    if event.selection.rows:
        selected_index = event.selection.rows[0]
        if selected_index < len(ranked) and st.button("Abrir perfil seleccionado", type="primary"):
            st.session_state["pending_record"] = ranked.iloc[selected_index].record_id
            st.session_state.pop("record_picker", None)
            st.switch_page(st.Page(explorer, title="Buscador y perfil", icon="🔎"))
    export = ranked[columns].copy()
    export.insert(0, "puesto", range(1, len(export) + 1))
    export["modelo"] = model
    st.download_button("Descargar este top · CSV", export.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"ranking_{model.lower()}_top{top_n}.csv", mime="text/csv")
    st.subheader("¿Dónde se sitúa cada jugador?")
    points = filtered.dropna(subset=["market_value_eur", "estimate"]).copy()
    st.caption(f"Gráfico de toda la muestra filtrada: {len(points)} observaciones con ambos valores. "
               "Por encima de la diagonal, la estimación supera al mercado.")
    if points.empty:
        st.info("No hay pares de mercado y estimación disponibles para el gráfico.")
        return
    points["Mercado (M)"] = points.market_value_eur / 1e6
    points["Estimación (M)"] = points.estimate / 1e6
    fig = px.scatter(points, x="Mercado (M)", y="Estimación (M)", color="position_group",
                     render_mode="webgl",
                     hover_name="player_name", hover_data={"team": True, "league": True, "season": True,
                     "Mercado (M)": ":.1f", "Estimación (M)": ":.1f"},
                     labels={"position_group": "Posición", "team": "Equipo", "league": "Liga", "season": "Temporada"},
                     color_discrete_sequence=[GREEN, BLUE, "#c7a5ff", "#ffbf70"])
    limit = float(max(points["Mercado (M)"].max(), points["Estimación (M)"].max()) * 1.05)
    fig.add_trace(go.Scatter(x=[0, limit], y=[0, limit], mode="lines", name="Mercado = estimación",
                            line=dict(color="#a4b1c3", dash="dash"), hoverinfo="skip"))
    fig.update_layout(separators=",.", hoverlabel=dict(namelength=-1))
    fig.update_xaxes(range=[0, limit], tickformat=".1f", ticksuffix=" M")
    fig.update_yaxes(range=[0, limit], tickformat=".1f", ticksuffix=" M")
    chart(fig, 500)
