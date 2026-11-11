"""Persistent history, frozen-data replay, integrity and UI regression tests."""
import hashlib
import io
import importlib
import json
from pathlib import Path
import shutil
import tempfile
import sys
from types import ModuleType
import unittest
from unittest.mock import patch
import zipfile

import geopandas as gpd
from streamlit.testing.v1 import AppTest

import gis_history as history
from gis_natural import DATA_DIR, BufferTask


class HistoryTests(unittest.TestCase):
    def test_history_import_with_cached_old_natural_page(self):
        import gis_history_ui
        from gis_result_view import render_analysis_result
        # A server upgraded in place may still hold the pre-history page module.
        stale_page = ModuleType("gis_natural_ui")
        with patch.dict(sys.modules, {"gis_natural_ui": stale_page}):
            importlib.reload(gis_history_ui)
            self.assertIs(gis_history_ui.render_analysis_result, render_analysis_result)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inputs = self.root / "live_inputs"
        self.inputs.mkdir()
        self.records = self.root / "records"
        for name in history.INPUT_NAMES:
            shutil.copy2(DATA_DIR / name, self.inputs / name)

    def save(self, radius=500, **kwargs):
        return history.save_run(BufferTask("昌盛路", radius), f"分析昌盛路周边{radius}米范围内的建筑物",
                                "本地规则（无需API）", data_dir=self.inputs, history_dir=self.records, **kwargs)

    def test_snapshots_export_and_unique_runs(self):
        first = self.save()
        second = self.save()
        self.assertNotEqual(first["task_id"], second["task_id"])
        records, errors = history.list_records(self.records)
        self.assertEqual(len(records), 2)
        self.assertFalse(errors)
        self.assertEqual(first["statistics"], {"roads": 4, "buildings_total": 510,
                                             "buildings_intersect": 105, "buildings_outside": 405})
        self.assertEqual(first["analysis"]["predicate"], "intersects")
        self.assertEqual([len(g) for g in history.load_layers(first["task_id"], self.records)], [4, 510, 1, 105])
        with zipfile.ZipFile(io.BytesIO(history.export_record(first["task_id"], self.records))) as archive:
            self.assertEqual(set(archive.namelist()), {"manifest.json", *history.ARTIFACTS})
            self.assertNotIn(".env", archive.namelist())
            for source in first["sources"]:
                self.assertEqual(hashlib.sha256(archive.read(source["snapshot"])).hexdigest(), source["sha256"])

    def test_replay_uses_snapshot_after_live_inputs_changed(self):
        original = self.save()
        parent = history.record_path(original["task_id"], self.records)
        before = {p: p.read_bytes() for p in parent.rglob("*") if p.is_file()}
        (self.inputs / "buildings_osm.geojson").write_text("source changed", encoding="utf-8")
        replay = history.reproduce_run(original["task_id"], self.records)
        self.assertTrue(replay["reproduction"]["matches"])
        self.assertEqual(replay["parent_task_id"], original["task_id"])
        self.assertEqual(replay["statistics"], original["statistics"])
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)

    def test_corruption_is_reported_and_cannot_replay(self):
        record = self.save()
        path = history.record_path(record["task_id"], self.records) / "results" / "selected_buildings.geojson"
        path.write_text("{}", encoding="utf-8")
        records, errors = history.list_records(self.records)
        self.assertFalse(records)
        self.assertEqual(len(errors), 1)
        with self.assertRaisesRegex(ValueError, "校验"):
            history.reproduce_run(record["task_id"], self.records)
        with self.assertRaisesRegex(ValueError, "编号"):
            history.load_record("../outside", self.records)

    def test_stale_input_and_failed_write_do_not_publish_partial_runs(self):
        with self.assertRaisesRegex(ValueError, "变化"):
            self.save(expected_fingerprint=("wrong", "fingerprint"))
        with patch("gis_history.execute_task", side_effect=ValueError("calculation interrupted")):
            with self.assertRaisesRegex(ValueError, "interrupted"):
                self.save()
        self.assertEqual(list(self.records.iterdir()), [])
        with patch("gis_history.Path.write_text", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.save()
        self.assertEqual(list(self.records.iterdir()), [])

    def test_different_result_is_not_reported_as_reproduced(self):
        record = self.save()
        saved = history.load_layers(record["task_id"], self.records)
        from gis_natural import execute_task
        other = execute_task(BufferTask("昌盛路", 300), self.inputs)
        report = history.compare_layers(saved, other)
        self.assertFalse(report["matches"])
        self.assertFalse(report["layers"]["buffer.geojson"])
        self.assertFalse(report["layers"]["selected_buildings.geojson"])

    def test_zero_matches_can_be_saved_loaded_and_replayed(self):
        path = self.inputs / "buildings_osm.geojson"
        buildings = gpd.read_file(path)
        buildings.geometry = buildings.geometry.translate(xoff=0.2)
        path.write_text(buildings.to_json(drop_id=True), encoding="utf-8")
        record = self.save(radius=1)
        self.assertEqual(record["statistics"]["buildings_intersect"], 0)
        self.assertEqual(len(history.load_layers(record["task_id"], self.records)[3]), 0)
        self.assertTrue(history.reproduce_run(record["task_id"], self.records)["reproduction"]["matches"])

    def test_ui_save_history_replay_and_no_duplicate_on_rerun(self):
        with patch("gis_natural_ui.HISTORY_DIR", self.records), patch("gis_history_ui.HISTORY_DIR", self.records), patch("gis_natural_ui.DATA_DIR", self.inputs):
            app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=60).run()
            app.sidebar.radio[0].set_value("分析任务记录").run()
            self.assertFalse(app.exception)
            self.assertTrue(app.info)
            app.sidebar.radio[0].set_value("自然语言空间分析").run()
            app.radio(key="analysis_dataset").set_value("昌盛路验收样本").run()
            app.text_input(key="nl_query").set_value("分析昌盛路周边500米范围内的建筑物")
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual([m.value for m in app.metric], ["510", "105", "405"])
            app.checkbox(key="nl_selected_only").uncheck().run()
            self.assertEqual(len(history.list_records(self.records)[0]), 1)
            # History must not depend on the current live files.
            (self.inputs / "buildings_osm.geojson").unlink()
            app.sidebar.radio[0].set_value("分析任务记录").run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            self.assertEqual([m.value for m in app.metric], ["510", "105", "405"])
            app.button(key="history_reproduce").click().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            self.assertTrue(any("复现结果与原任务一致" in item.value for item in app.success))
            self.assertEqual(len(history.list_records(self.records)[0]), 2)
            app.run()
            self.assertEqual(len(history.list_records(self.records)[0]), 2)


if __name__ == "__main__":
    unittest.main()
