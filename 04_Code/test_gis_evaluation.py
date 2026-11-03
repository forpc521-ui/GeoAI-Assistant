"""Verify scoring denominators and reference checks independently of product tests."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from evaluation_report import summarize, timing
from evaluate_project import assess_parse, independent_reference, load_cases, validate_spatial
from gis_natural import BufferTask, DATA_DIR, execute_task


class EvaluationTests(unittest.TestCase):
    def test_failed_valid_and_api_errors_remain_in_denominators(self):
        rows = [
            {"mode": "local", "expected": "accept", "category": "standard", "status": "accepted", "parse_correct": True, "parse_ms": 1,
             "workflow": {"business_pass": True, "closed_loop_pass": True, "spatial_pass": True, "reproduction_pass": True, "workflow_ms": 10, "reproduction_ms": 20}},
            {"mode": "local", "expected": "accept", "category": "paraphrase", "status": "rejected", "parse_correct": False, "parse_ms": 2},
            {"mode": "local", "expected": "reject", "category": "invalid", "status": "error", "parse_correct": False, "parse_ms": 3},
            {"mode": "deepseek", "expected": "accept", "category": "standard", "status": "skipped", "parse_correct": False, "parse_ms": None},
        ]
        metrics = summarize(rows, ("local", "deepseek"))
        self.assertEqual(metrics["local"]["valid_parse_accuracy"]["percent"], 50)
        self.assertEqual(metrics["local"]["closed_loop_success"]["total"], 2)
        self.assertEqual(metrics["local"]["invalid_handling_accuracy"]["passed"], 0)
        self.assertIsNone(metrics["deepseek"]["closed_loop_success"]["percent"])

    def test_api_failure_cannot_count_as_correct_rejection(self):
        client = Mock()
        client.chat.completions.create.side_effect = RuntimeError("not a model refusal")
        case = {"id": "error", "category": "invalid", "query": "分析不存在路周边500米的建筑物", "expected": "reject"}
        row = assess_parse(case, "deepseek", ["昌盛路"], client)
        self.assertEqual(row["status"], "error")
        self.assertFalse(row["parse_correct"])
        self.assertEqual(row["api_requests"], 1)

    def test_reference_checks_ids_not_only_counts(self):
        reference = independent_reference(DATA_DIR, "昌盛路", 500)
        self.assertEqual(len(reference["selected_ids"]), 105)
        layers = execute_task(BufferTask("昌盛路", 500))
        self.assertTrue(validate_spatial(layers, reference)["passed"])
        wrong = layers[3].copy()
        wrong.iloc[0, wrong.columns.get_loc("full_id")] = "wrong-building"
        result = validate_spatial((*layers[:3], wrong), reference)
        self.assertFalse(result["passed"])
        self.assertTrue(result["unexpected_ids"])

    def test_case_ids_and_latency_interpolation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cases.json"
            path.write_text(json.dumps({"cases": [{"id": "a", "expected": "reject"}, {"id": "a", "expected": "reject"}]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_cases(path)
        self.assertEqual(timing([0, 100])["p95_ms"], 95)
        self.assertIsNone(timing([])["p50_ms"])


if __name__ == "__main__":
    unittest.main()
