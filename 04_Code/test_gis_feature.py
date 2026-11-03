r"""Run with: venv\Scripts\python.exe -m unittest discover -s 04_Code -p test_gis_feature.py"""
from pathlib import Path
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import gis_feature as gis

CODE_DIR = Path(__file__).resolve().parent


class GISFeatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        for filename in gis.FILES:
            shutil.copy2(gis.SAMPLE_DIR / filename, self.directory / filename)

    def test_saved_outputs_and_recalculation(self):
        inputs = [(self.directory / name).read_bytes() for name in gis.FILES[:2]]
        roads, buildings, buffer, selected = gis.load_results(self.directory)
        self.assertEqual((len(buildings), len(selected)), (3, 2))
        self.assertEqual(buildings.within_500m.tolist(), [True, True, False])
        self.assertAlmostEqual(buildings.distance_m.iloc[0], 110.98, places=2)
        gis.run_analysis(self.directory)
        self.assertEqual(inputs, [(self.directory / name).read_bytes() for name in gis.FILES[:2]])
        self.assertEqual(len(gis.load_results(self.directory)[3]), 2)
        deck = json.loads(gis.make_map(roads, buildings, buffer, selected).to_json())
        self.assertEqual(len(deck["layers"]), 4)
        self.assertIsNone(deck.get("mapProvider"))

    def test_missing_corrupt_and_stale_files(self):
        path = self.directory / gis.FILES[2]
        path.unlink()
        with self.assertRaisesRegex(FileNotFoundError, "buffer_500m.geojson"):
            gis.load_results(self.directory)
        gis.run_analysis(self.directory)
        path = self.directory / gis.FILES[3]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["features"] = payload["features"][:1]
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "不一致"):
            gis.load_results(self.directory)
        (self.directory / gis.FILES[0]).write_text("broken", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "无法读取 roads.geojson"):
            gis.run_analysis(self.directory)

    def test_zero_matches(self):
        path = self.directory / gis.FILES[1]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["features"] = payload["features"][2:]
        path.write_text(json.dumps(payload), encoding="utf-8")
        gis.run_analysis(self.directory)
        self.assertEqual(len(gis.load_results(self.directory)[3]), 0)

    def test_app_navigation_run_rerun_and_missing_files(self):
        with patch.object(gis, "SAMPLE_DIR", self.directory):
            app = AppTest.from_file(str(CODE_DIR / "app.py"), default_timeout=60).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.text_input[0].label, "请输入你的GIS问题：")
            app.button[0].click().run()
            self.assertTrue(app.warning)
            app.sidebar.radio[0].set_value("道路500米缓冲区分析").run()
            app.selectbox(key="gis_source").select("模拟数据演示").run()
            self.assertFalse(app.exception)
            self.assertEqual([m.value for m in app.metric], ["3", "2", "1"])
            self.assertEqual(len(app.get("deck_gl_json_chart")), 1)
            app.button(key="run_gis").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.success)
            app.checkbox(key="gis_basemap").check().run()
            self.assertEqual(len(app.dataframe[0].value), 3)
            (self.directory / gis.FILES[2]).unlink()
            app.run()
            self.assertFalse(app.exception)
            self.assertIn("buffer_500m.geojson", app.error[0].value)
            app.button(key="run_gis").click().run()
            self.assertEqual([m.value for m in app.metric], ["3", "2", "1"])
            (self.directory / gis.FILES[0]).unlink()
            app.button(key="run_gis").click().run()
            self.assertFalse(app.exception)
            self.assertIn("roads.geojson", app.error[0].value)


if __name__ == "__main__":
    unittest.main()
