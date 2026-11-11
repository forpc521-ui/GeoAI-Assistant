"""Product acceptance: real-result exports, public errors and task persistence."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from gis_history import load_layers, load_record
from gis_natural import BufferTask, execute_task
from gis_result_view import result_csv


class ProductUITests(unittest.TestCase):
    def page(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.history = Path(temporary.name)
        replacement = patch("gis_natural_ui.HISTORY_DIR", self.history)
        replacement.start()
        self.addCleanup(replacement.stop)
        app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=60).run()
        app.sidebar.radio[0].set_value("自然语言空间分析").run()
        app.radio(key="analysis_dataset").set_value("昌盛路验收样本").run()
        self.assertFalse(app.exception)
        return app

    def submit(self, app, text="分析昌盛路周边500米范围内的建筑物"):
        app.text_input(key="nl_query").set_value(text)
        app.button[0].click().run()
        self.assertFalse(app.exception)

    def test_exports_match_real_layers_at_three_distances(self):
        for distance in (300, 500, 1000):
            task = BufferTask("昌盛路", distance)
            layers = execute_task(task)
            for only_selected in (True, False):
                summary_bytes, detail_bytes = result_csv(layers, task, only_selected)
                self.assertTrue(summary_bytes.startswith(b"\xef\xbb\xbf"))
                summary = pd.read_csv(io.BytesIO(summary_bytes)).iloc[0]
                detail = pd.read_csv(io.BytesIO(detail_bytes))
                expected = layers[3] if only_selected else layers[1]
                self.assertEqual(summary.buildings_total, len(layers[1]))
                self.assertEqual(summary.buildings_intersect, len(layers[3]))
                self.assertEqual(summary.buildings_outside, len(layers[1]) - len(layers[3]))
                self.assertAlmostEqual(summary.intersect_ratio, len(layers[3]) / len(layers[1]))
                self.assertEqual(detail.full_id.tolist(), expected.full_id.tolist())
                self.assertEqual(detail.intersects_buffer.tolist(), expected.intersects_buffer.tolist())
                self.assertEqual(detail.nearest_road_m.tolist(), expected.nearest_road_m.tolist())
                self.assertTrue(detail.distance_m.eq(distance).all())
                self.assertTrue(detail.road_name.eq("昌盛路").all())

    def test_zero_selected_and_zero_total_csv(self):
        task = BufferTask("昌盛路", 500)
        roads, buildings, buffer, selected = execute_task(task)
        for frame in (buildings, buildings.iloc[:0]):
            layers = (roads, frame, buffer, selected.iloc[:0])
            summary_bytes, detail_bytes = result_csv(layers, task)
            summary = pd.read_csv(io.BytesIO(summary_bytes)).iloc[0]
            detail = pd.read_csv(io.BytesIO(detail_bytes))
            self.assertTrue(detail.empty)
            self.assertIn("intersects_buffer", detail.columns)
            self.assertEqual(summary.buildings_intersect, 0)
            self.assertEqual(summary.buildings_outside, len(frame))
            if frame.empty:
                self.assertTrue(pd.isna(summary.intersect_ratio))
                self.assertTrue(pd.isna(summary.outside_ratio))

    def test_page_downloads_follow_table_and_current_task_without_duplicate(self):
        app = self.page()
        with patch("streamlit.download_button", wraps=st.download_button) as downloads:
            self.submit(app)
            task_id = app.session_state["nl_result"]["task_id"]
            manifest = load_record(task_id, self.history)
            self.assertIn("参数说明与统计口径", [e.label for e in app.expander])
            self.assertIn("本次数据来源与坐标系", [e.label for e in app.expander])
            visible = " ".join(x.value for kind in (app.text, app.caption, app.markdown) for x in kind)
            self.assertIn("待补充", visible)
            for source in manifest["sources"]:
                self.assertIn(source["snapshot"], visible)
                self.assertIn(source["crs"], visible)
                self.assertIn(source["sha256"], visible)
            for only_selected in (True, False):
                downloads.reset_mock()
                app.checkbox(key="nl_selected_only").set_value(only_selected).run()
                exported = {c.kwargs.get("key"): c.kwargs for c in downloads.call_args_list}
                detail = pd.read_csv(io.BytesIO(exported["nl_detail_csv"]["data"]))
                self.assertEqual(len(detail), len(app.dataframe[0].value))
                self.assertEqual(detail.full_id.tolist(), app.dataframe[0].value["OSM标识"].tolist())
                self.assertEqual(exported["nl_detail_csv"]["on_click"], "ignore")
                self.assertEqual(len(list(self.history.iterdir())), 1)
                self.assertEqual(app.session_state["nl_result"]["task_id"], task_id)
            downloads.reset_mock()
            self.submit(app, "分析昌盛路周边300米范围内的建筑物")
            exported = {c.kwargs.get("key"): c.kwargs for c in downloads.call_args_list}
            summary = pd.read_csv(io.BytesIO(exported["nl_summary_csv"]["data"])).iloc[0]
            current_id = app.session_state["nl_result"]["task_id"]
            layers = load_layers(current_id, self.history)
            self.assertNotEqual(task_id, current_id)
            self.assertEqual(summary.distance_m, 300)
            self.assertEqual(summary.buildings_intersect, len(layers[3]))
            self.assertEqual(len(list(self.history.iterdir())), 2)

    def test_validation_and_unsupported_clear_previous_result(self):
        app = self.page()
        self.submit(app)
        with patch("gis_natural_ui.save_run") as save:
            for query, label in (("", "输入校验未通过"),
                                 ("分析昌盛路周边6000米的建筑物", "输入校验未通过"),
                                 ("分析不存在路周边500米的建筑物", "输入校验未通过"),
                                 ("分析昌盛路周边500米的建筑物，计算平均高度", "当前不支持")):
                self.submit(app, query)
                self.assertIn(label, app.warning[0].value)
                self.assertFalse(app.error)
                self.assertFalse(app.metric)
                self.assertFalse(app.get("download_button"))
                self.assertIsNone(app.session_state["nl_result"])
            save.assert_not_called()

    def test_execution_exceptions_hide_internal_details(self):
        app = self.page()
        secret = "private-token C:/private/data traceback"
        for exception in (ValueError(secret), OSError(secret), RuntimeError(secret)):
            with patch("gis_natural_ui.save_run", side_effect=exception):
                self.submit(app)
                self.assertIn("执行异常", app.error[0].value)
                self.assertNotIn(secret, app.error[0].value)
                self.assertFalse(app.warning)
                self.assertFalse(app.metric)
                self.assertFalse(app.get("download_button"))
                self.assertIsNone(app.session_state["nl_result"])
        with patch("gis_natural_ui.parse_task", side_effect=ValueError(secret)):
            self.submit(app)
            self.assertIn("执行异常", app.error[0].value)
            self.assertNotIn(secret, app.error[0].value)

    def test_load_errors_hide_internal_details(self):
        app = self.page()
        secret = "private-token C:/private/data traceback"
        with patch("gis_natural_ui.source_fingerprint", side_effect=OSError(secret)):
            app.run()
            self.assertIn("执行异常", app.error[0].value)
            self.assertNotIn(secret, app.error[0].value)
        app.run()
        self.submit(app)
        with patch("gis_natural_ui.load_record", side_effect=ValueError(secret)):
            app.run()
            self.assertIn("执行异常", app.error[0].value)
            self.assertNotIn(secret, app.error[0].value)
            self.assertFalse(app.metric)
            self.assertFalse(app.get("download_button"))

    def test_deepseek_configuration_and_connection_failures(self):
        app = self.page()
        app.selectbox(key="nl_mode").set_value("DeepSeek（使用已有API配置）")
        with patch("gis_natural_ui.os.getenv", return_value=None), patch("gis_natural_ui.save_run") as save:
            self.submit(app)
            self.assertIn("DeepSeek尚未配置", app.error[0].value)
            save.assert_not_called()
        with patch("gis_natural_ui.os.getenv", return_value="test-only"), \
                patch("openai.OpenAI"), \
                patch("gis_natural_ui.parse_task", side_effect=RuntimeError("private-token")), \
                patch("gis_natural_ui.save_run") as save:
            self.submit(app)
            self.assertIn("执行异常", app.error[0].value)
            self.assertNotIn("private-token", app.error[0].value)
            self.assertFalse(app.get("download_button"))
            save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
