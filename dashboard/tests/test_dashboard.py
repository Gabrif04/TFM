"""Contract and UI regression checks using the supplied CSV, without SQLite."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import pandas as pd
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.db import load_players, with_model, rank_players, search_key
from components.profile_identity import ASSETS, media_entry


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df, _ = load_players()

    def view(self, name):
        dashboard = str(Path(__file__).resolve().parents[1])
        app = AppTest.from_string(
            f"import sys\nsys.path.insert(0, {dashboard!r})\nfrom views import {name}\n{name}()"
        ).run(timeout=30)
        self.assertFalse(app.exception)
        return app

    def test_csv_contract(self):
        self.assertEqual(len(self.df), 1863)
        self.assertTrue(self.df.record_id.is_unique)
        self.assertLess(self.df.minutes_played.min(), 900)
        self.assertEqual(self.df.league.nunique(), 5)
        self.assertEqual(search_key("MBAPPÉ"), "mbappe")

    def test_model_math_and_rankings(self):
        for model in ["General", "Scouting"]:
            df = with_model(self.df, model)
            for n in [10, 20, 25, 50]:
                for asc in [True, False]:
                    top = rank_players(df, "estimate", asc, n)
                    self.assertEqual(len(top), n)
                    self.assertFalse(top.estimate.isna().any())
                    self.assertTrue(top.estimate.is_monotonic_increasing if asc else top.estimate.is_monotonic_decreasing)
            row = df.dropna(subset=["estimate"]).iloc[0]
            self.assertAlmostEqual(row.difference, row.estimate - row.market_value_eur)
            self.assertAlmostEqual(row.difference_pct, 100 * row.difference / row.market_value_eur)
        scouting = with_model(self.df, "Scouting")
        self.assertTrue(scouting.loc[scouting.position_group.eq("Portero"), "estimate"].isna().all())

    def test_overview_without_database(self):
        with patch("sqlite3.connect", side_effect=AssertionError("SQLite must not be accessed")):
            app = self.view("overview")
        self.assertEqual(app.metric[0].value, "1 863")

    def test_search_and_empty_results(self):
        app = self.view("explorer")
        self.assertEqual(len(next(x for x in app.selectbox if x.label.startswith("Jugador ·")).options), 1863)
        app.text_input[0].set_value("mbappe").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(next(x for x in app.selectbox if x.label.startswith("Jugador ·")).options), 2)
        app.text_input[0].set_value("[unknown literal search").run()
        self.assertFalse(app.exception)
        self.assertIn("No hay jugadores", app.info[0].value)

    def test_goalkeeper_scouting_and_reset(self):
        app = self.view("explorer")
        next(x for x in app.selectbox if x.label == "Modelo de valoración").select("Scouting").run()
        app.multiselect[2].select("Portero").run()
        self.assertFalse(app.exception)
        self.assertTrue(any("no tiene estimación" in item.value for item in app.info))
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(next(x for x in app.selectbox if x.label.startswith("Jugador ·")).options), 1863)

    def test_rank_metric_and_empty_scouting(self):
        app = self.view("ranking")
        next(x for x in app.selectbox if x.label == "Tamaño del top").select(50).run()
        self.assertEqual(len(app.dataframe[0].value), 50)
        next(x for x in app.selectbox if x.label == "Modelo de valoración").select("Scouting").run()
        next(x for x in app.selectbox if x.label == "Ordenar por").select("estimate").run()
        app.multiselect[2].select("Portero").run()
        self.assertFalse(app.exception)
        self.assertIn("No hay observaciones", app.info[0].value)

    def test_pending_record_selects_exact_team(self):
        app = self.view("explorer")
        duplicated = self.df[self.df.player_name.duplicated(keep=False)].iloc[-1]
        app.session_state["pending_record"] = duplicated.record_id
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(next(x for x in app.selectbox if x.label.startswith("Jugador ·")).value, duplicated.record_id)

    def test_cascading_filters(self):
        for view in ["explorer", "ranking"]:
            with self.subTest(view=view):
                app = self.view(view)
                app.multiselect[0].set_value(["ESP"]).run()
                spanish = sorted(self.df.loc[self.df.league.eq("ESP"), "team"].unique())
                self.assertEqual(app.multiselect[1].options, spanish)
                app.multiselect[1].select(spanish[0]).run()
                app.multiselect[0].set_value(["ENG"]).run()
                self.assertFalse(app.exception)
                self.assertEqual(app.multiselect[1].value, [])
                self.assertEqual(app.multiselect[1].options,
                    sorted(self.df.loc[self.df.league.eq("ENG"), "team"].unique()))
                app.multiselect[0].set_value(["ENG", "ESP"]).run()
                self.assertEqual(app.multiselect[1].options,
                    sorted(self.df.loc[self.df.league.isin(["ENG", "ESP"]), "team"].unique()))
                app.multiselect[0].set_value([]).run()
                self.assertEqual(app.multiselect[1].options, sorted(self.df.team.unique()))

    def test_local_profile_media(self):
        row = self.df.loc[self.df.player_name.eq("Erling Haaland")].iloc[0]
        key = "|".join(str(row[col]) for col in ["player_name", "team", "league", "season"])
        photo = media_entry("player", key)
        self.assertIsNotNone(photo)
        self.assertTrue((ASSETS / "media" / photo["path"]).is_file())
        self.assertTrue(photo["source"].startswith("https://commons.wikimedia.org/"))
        self.assertTrue(photo["license"])
        self.assertTrue((ASSETS / "icons" / "flag-ENG.svg").is_file())
        self.assertTrue((ASSETS / "icons" / "forward.svg").is_file())

    def test_vitinha_identity_correction(self):
        rows = self.df.loc[self.df.player_name.eq("Vitinha")].set_index("team")
        self.assertEqual(rows.loc["PSG", "market_value_eur"], 140_000_000)
        self.assertEqual(rows.loc["Genoa", "market_value_eur"], 8_000_000)
        self.assertIn("corregido", rows.loc["Genoa", "data_note"])
        self.assertNotEqual(rows.loc["PSG", "record_id"], rows.loc["Genoa", "record_id"])


if __name__ == "__main__":
    unittest.main()
