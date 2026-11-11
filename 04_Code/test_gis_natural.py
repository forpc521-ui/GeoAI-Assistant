"""Check variable-radius GIS results, parsing boundaries and page interaction."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile
from unittest.mock import Mock, patch

import geopandas as gpd
from shapely.geometry import LineString, box
from streamlit.testing.v1 import AppTest

from gis_natural import DATA_DIR, BufferTask, execute_task, parse_task
from gis_real_results import OUT_DIR


class NaturalGISTests(unittest.TestCase):
    @staticmethod
    def buffer_client(distance=500):
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content=json.dumps(
                asdict(BufferTask("昌盛路", distance)))))])
        return client

    def test_unsupported_intents_rejected_before_model(self):
        base = "分析昌盛路周边500米范围内的建筑物"
        requests = (
            base + "平均高度", base + "，计算建筑物的平均高度",
            base + "，预测未来建筑数量", base + "，分析未来十年变化",
            "预测未来", "未来十年变化", "平均高度",
            "预测未来十年昌盛路周边500米建筑物数量变化",
            base + "，统计平均高度，计算范围内占比。",
            base + "，计算楼层数", base + "，分析房价趋势",
        )
        for text in requests:
            for client in (None, self.buffer_client()):
                with self.subTest(text=text, model=client is not None):
                    with self.assertRaisesRegex(ValueError, "当前不支持"):
                        parse_task(text, ["昌盛路"], client)
                    if client is not None:
                        client.chat.completions.create.assert_not_called()

    def test_four_distance_guards_in_both_modes(self):
        for text in ("分析昌盛路周边的建筑物", "分析昌盛路周边0米的建筑物",
                     "分析昌盛路周边6000米的建筑物",
                     "分析昌盛路周边300米和500米的建筑物"):
            for client in (None, self.buffer_client()):
                with self.subTest(text=text, model=client is not None):
                    with self.assertRaises(ValueError):
                        parse_task(text, ["昌盛路"], client)
                    if client is not None:
                        client.chat.completions.create.assert_not_called()

    def test_legal_distances_in_both_modes(self):
        for value, distance in (("300米", 300), ("500米", 500), ("1000米", 1000),
                                ("0.5公里", 500), ("半公里", 500), ("5000米", 5000)):
            for client in (None, self.buffer_client(distance)):
                with self.subTest(value=value, model=client is not None):
                    self.assertEqual(parse_task(f"分析昌盛路周边{value}范围内的建筑物",
                                                ["昌盛路"], client), BufferTask("昌盛路", distance))

    def test_page_rejects_unsupported_before_saving_or_computing(self):
        app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=60).run()
        app.sidebar.radio[0].set_value("自然语言空间分析").run()
        app.radio(key="analysis_dataset").set_value("昌盛路验收样本").run()
        client = self.buffer_client()
        # Use an in-memory dummy key; never load or change the real API settings.
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only"}), \
                patch("openai.OpenAI", return_value=client), \
                patch("gis_natural_ui.save_run") as save, \
                patch("gis_history.execute_task") as execute:
            for mode in ("本地规则（无需API）", "DeepSeek（使用已有API配置）"):
                for suffix in ("，计算平均高度", "，预测未来", "，分析未来十年变化"):
                    with self.subTest(mode=mode, suffix=suffix):
                        app.selectbox(key="nl_mode").set_value(mode)
                        app.text_input(key="nl_query").set_value(
                            "分析昌盛路周边500米范围内的建筑物" + suffix)
                        app.button[0].click().run()
                        self.assertFalse(app.exception)
                        self.assertTrue(app.warning)
                        self.assertIn("当前不支持", app.warning[0].value)
                        self.assertFalse(app.metric)
                        self.assertFalse(app.get("deck_gl_json_chart"))
                        self.assertIsNone(app.session_state["nl_result"])
            save.assert_not_called()
            execute.assert_not_called()
            client.chat.completions.create.assert_not_called()

    def test_reporting_clauses_in_local_mode(self):
        base = "分析昌盛路周边500米范围内的建筑物"
        for suffix in ("，统计范围内数量。", "，统计范围外的建筑物数量。",
                       "，计算范围内建筑物占比。", "，计算范围外占比。",
                       "，统计范围内和范围外的数量，并计算范围内建筑物占比。",
                       ",统计范围内数量和范围外数量,计算范围内比例。"):
            with self.subTest(suffix=suffix):
                self.assertEqual(parse_task(base + suffix, ["昌盛路"]), BufferTask("昌盛路", 500))

    def test_outside_selection_and_unknown_clauses_still_rejected(self):
        for text in ("筛选昌盛路周边500米范围外的建筑物",
                     "分析昌盛路周边500米范围内的建筑物，筛选范围外建筑物",
                     "分析昌盛路周边500米范围内的建筑物，删除范围外建筑物",
                     "分析完全位于昌盛路周边500米范围内的建筑物",
                     "分析昌盛路周边500米范围内的建筑物，统计范围外数量并删除建筑物"):
            for client in (None, Mock()):
                with self.subTest(text=text, model=client is not None), self.assertRaises(ValueError):
                    parse_task(text, ["昌盛路"], client)
                if client is not None:
                    client.chat.completions.create.assert_not_called()
        with self.assertRaisesRegex(ValueError, "本地规则仅支持约定句式"):
            parse_task("请以昌盛路为中心建立500米缓冲区，查看建筑物", ["昌盛路"])

    def test_reporting_in_model_mode(self):
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content=json.dumps(asdict(BufferTask("昌盛路", 500)))))])
        text = "分析昌盛路周边500米范围内的建筑物，统计范围内和范围外的数量，并计算范围内建筑物占比。"
        self.assertEqual(parse_task(text, ["昌盛路"], client), BufferTask("昌盛路", 500))
        messages = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual(messages[1]["content"], text)
        self.assertIn("占比分母", messages[0]["content"])
        client.chat.completions.create.return_value.choices[0].message.content = json.dumps(
            asdict(BufferTask("昌盛路", 1000)))
        with self.assertRaisesRegex(ValueError, "解析参数与原指令不一致"):
            parse_task(text, ["昌盛路"], client)

    def test_intersection_keeps_crossing_and_boundary_touch(self):
        roads = gpd.GeoDataFrame({"name": ["昌盛路"]}, geometry=[
            LineString([(500000, 3000000), (500000, 3000100)])], crs=32650)
        buildings = gpd.GeoDataFrame({"full_id": ["inside", "crossing", "touch", "outside"]},
            geometry=[box(500010, 3000010, 500020, 3000020),
                      box(500490, 3000010, 500510, 3000020),
                      box(500500, 3000030, 500510, 3000040),
                      box(500501, 3000050, 500510, 3000060)], crs=32650)
        with patch("gis_natural.read_inputs", return_value=(roads, buildings)):
            _, all_buildings, _, selected = execute_task(BufferTask("昌盛路", 500))
        self.assertEqual(set(selected.full_id), {"inside", "crossing", "touch"})
        self.assertEqual(all_buildings.intersects_buffer.tolist(), [True, True, True, False])
        self.assertEqual(len(all_buildings) - len(selected), 1)
        self.assertEqual(len(selected) / len(all_buildings), 0.75)

    def test_rules_and_clear_errors(self):
        for text, distance in (("分析昌盛路周边500米范围内的建筑物", 500),
                               ("统计昌盛路附近0.5公里内的建筑数量", 500),
                               ("请帮我查询昌盛路周边1000米的建筑物", 1000)):
            task = parse_task(text, ["昌盛路"])
            self.assertEqual(task.road_name, "昌盛路")
            self.assertEqual(task.distance_m, distance)
        for text in ("分析昌盛路附近的建筑物", "分析不存在路周边500米的建筑物",
                     "分析昌盛路周边300米到500米的建筑物", "分析昌盛路周边500米之外的建筑物",
                     "分析昌盛路周边-500米的建筑物", "分析昌盛路周边0米的建筑物",
                     "分析昌盛路周边10000米的建筑物", "分析昌盛路周边500米的医院"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_task(text, ["昌盛路"])

    def test_model_output_validation(self):
        client = Mock()
        def response(payload):
            client.chat.completions.create.return_value = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
        text = "分析昌盛路周边500米范围内的建筑物"
        payload = asdict(BufferTask("昌盛路", 500))
        response(payload)
        self.assertEqual(parse_task(text, ["昌盛路"], client).distance_m, 500)
        for invalid in ({**payload, "distance_m": 1000}, {**payload, "road_name": "其他路"},
                        {**payload, "operation": "run_python"}, {**payload, "distance_m": True},
                        {**payload, "code": "untrusted"}, {**payload, "distance_m": None}):
            response(invalid)
            with self.assertRaises(ValueError):
                parse_task(text, ["昌盛路"], client)

    def test_recompute_three_radii_and_preserve_files(self):
        paths = list(DATA_DIR.glob("*.geojson")) + list(OUT_DIR.glob("*.geojson"))
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        selected_ids, areas = [], []
        counts = []
        for radius in (300, 500, 1000):
            roads, buildings, buffer, selected = execute_task(BufferTask("昌盛路", radius))
            counts.append(len(selected))
            self.assertEqual(len(roads), 4)
            self.assertEqual(len(buildings), 510)
            # Independently check containment of selected source IDs via the returned buffer.
            expected = buildings.to_crs(32650).intersects(buffer.to_crs(32650).geometry.iloc[0])
            self.assertEqual(set(buildings.loc[expected, "full_id"]), set(selected.full_id))
            selected_ids.append(set(selected.full_id))
            areas.append(buffer.to_crs(32650).area.iloc[0])
            self.assertEqual(json.loads(selected.to_json())["type"], "FeatureCollection")
        self.assertEqual(counts[1], 105)
        self.assertTrue(selected_ids[0] < selected_ids[1] < selected_ids[2])
        self.assertTrue(areas[0] < areas[1] < areas[2])
        print("300m / 500m / 1000m intersect counts:", counts)
        for path, digest in before.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_page_submit_rerun_and_invalid_request(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        history_patch = patch("gis_natural_ui.HISTORY_DIR", Path(temporary.name))
        history_patch.start()
        self.addCleanup(history_patch.stop)
        app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=60).run()
        app.sidebar.radio[0].set_value("自然语言空间分析").run()
        app.radio(key="analysis_dataset").set_value("昌盛路验收样本").run()
        self.assertFalse(app.exception)
        self.assertFalse(app.metric)
        app.text_input(key="nl_query").set_value("分析昌盛路周边500米范围内的建筑物，统计范围内和范围外的数量，并计算范围内建筑物占比。")
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual([m.value for m in app.metric], ["510", "105", "405"])
        self.assertTrue(any("20.59%" in m.value and "79.41%" in m.value for m in app.markdown))
        self.assertEqual(len(app.dataframe[0].value), 105)
        app.checkbox(key="nl_selected_only").uncheck().run()
        self.assertEqual(len(app.dataframe[0].value), 510)
        app.text_input(key="nl_query").set_value("分析昌盛路周边300米范围内的建筑物")
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertLess(int(app.metric[1].value), 105)
        app.text_input(key="nl_query").set_value("分析不存在路周边500米的建筑物")
        app.button[0].click().run()
        self.assertTrue(app.warning)
        self.assertFalse(app.metric)
        self.assertFalse(app.get("deck_gl_json_chart"))


if __name__ == "__main__":
    unittest.main()
