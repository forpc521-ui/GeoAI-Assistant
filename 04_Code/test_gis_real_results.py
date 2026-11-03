"""Regression checks for saved real results and UI counts; inputs stay read-only."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from streamlit.testing.v1 import AppTest
from gis_real_results import DATA_DIR, OUT_DIR, INPUT_FILES, OUTPUT_FILES, load_real_results


class RealResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "input"
        self.out = self.root / "output"
        self.data.mkdir()
        self.out.mkdir()
        for directory, target, names in ((DATA_DIR, self.data, INPUT_FILES), (OUT_DIR, self.out, OUTPUT_FILES)):
            for name in names:
                shutil.copy2(directory / name, target / name)

    def test_real_results_and_no_writes(self):
        before = {p: hashlib.sha256(p.read_bytes()).digest() for p in self.root.rglob("*.geojson")}
        roads, buildings, buffer, selected = load_real_results(self.data, self.out)
        self.assertEqual([len(g) for g in (roads, buildings, buffer, selected)], [4, 510, 1, 105])
        self.assertEqual(int(buildings.within_500m.sum()), 105)
        self.assertEqual(len(buildings) - len(selected), 405)
        self.assertEqual(len(set(roads["name"])), 1)
        self.assertTrue(roads.oneway.eq("yes").all())
        for path, digest in before.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), digest)

    def test_stale_same_count_and_invalid_flags(self):
        path = self.out / OUTPUT_FILES[1]
        original = path.read_text(encoding="utf-8")
        payload = json.loads(original)
        payload["features"][0]["properties"]["full_id"] = "wrong-id"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "不一致"):
            load_real_results(self.data, self.out)
        payload = json.loads(original)
        payload["features"][0]["properties"]["within_500m"] = False
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "标记"):
            load_real_results(self.data, self.out)
        payload = json.loads(original)
        payload["features"][0]["properties"]["nearest_road_m"] = 9999
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "距离.*不一致"):
            load_real_results(self.data, self.out)

    def test_stale_buffer_and_missing_file(self):
        path = self.out / OUTPUT_FILES[0]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["features"][0]["properties"]["buffer_m"] = 200
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "缓冲区.*不一致"):
            load_real_results(self.data, self.out)
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            load_real_results(self.data, self.out)

    def test_real_page_and_table_toggle(self):
        app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=60).run()
        self.assertFalse(app.exception)
        app.sidebar.radio[0].set_value("道路500米缓冲区分析").run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual([m.value for m in app.metric], ["510", "105", "405"])
        self.assertEqual(len(app.dataframe[0].value), 105)
        deck = json.loads(app.get("deck_gl_json_chart")[0].proto.json)
        self.assertEqual([len(layer["data"]["features"]) for layer in deck["layers"]], [1, 510, 105, 4])
        app.checkbox(key="gis_selected_only").uncheck().run()
        self.assertEqual(len(app.dataframe[0].value), 510)
        app.button(key="run_gis").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.success)


if __name__ == "__main__":
    unittest.main()
