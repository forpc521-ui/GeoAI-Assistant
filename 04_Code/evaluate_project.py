r"""CLI evaluation with frozen evidence, real optional API requests, and offline reports.

Examples:
  venv\Scripts\python.exe 04_Code\evaluate_project.py --mode local
  venv\Scripts\python.exe 04_Code\evaluate_project.py --mode both
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
from uuid import uuid4
import zipfile

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import shape
from shapely import transform

from evaluation_report import summarize, write_reports
from gis_history import environment, export_record, load_layers, reproduce_run, save_run
from gis_natural import BufferTask, DATA_DIR, parse_task
from gis_real_test import METRIC_CRS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "03_Data" / "evaluation" / "cases_v1.json"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_cases(path):
    suite = json.loads(Path(path).read_text(encoding="utf-8"))
    seen = set()
    for case in suite["cases"]:
        if case["id"] in seen or case["expected"] not in ("accept", "reject"):
            raise ValueError("用例编号重复或标签无效。")
        seen.add(case["id"])
        if case["expected"] == "accept":
            if not isinstance(case["road_name"], str) or not isinstance(case["distance_m"], (int, float)):
                raise ValueError("有效用例缺少人工标注的道路或距离。")
    return suite


def task_matches(task, case):
    return (task.operation == "road_buffer_buildings" and task.road_name == case["road_name"]
            and math.isclose(task.distance_m, case["distance_m"], rel_tol=0, abs_tol=1e-8))


class TracedClient:
    def __init__(self, real_client):
        self.real = real_client
        self.requests = 0
        self.responses = []
        self.usage = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests += 1
        response = self.real.chat.completions.create(**kwargs)
        self.responses.append({"response_id": response.id, "model": response.model,
                               "content": response.choices[0].message.content,
                               "finish_reason": response.choices[0].finish_reason})
        if response.usage is not None:
            self.usage.append(response.usage.model_dump())
        return response


def assess_parse(case, mode, available, real_client=None, skip_reason=None):
    row = {"case_id": case["id"], "mode": mode, "category": case["category"],
           "query": case["query"], "expected": case["expected"], "label": case,
           "status": "skipped", "parse_correct": False, "parse_ms": None,
           "actual_task": None, "error": skip_reason}
    if skip_reason:
        return row
    trace = TracedClient(real_client) if real_client is not None else None
    start = time.perf_counter()
    try:
        task = parse_task(case["query"], available, trace)
        row.update(status="accepted", actual_task=asdict(task))
        row["parse_correct"] = case["expected"] == "accept" and task_matches(task, case)
    except ValueError as exc:
        row.update(status="rejected", error=str(exc), parse_correct=case["expected"] == "reject")
    except Exception as exc:
        # Do not serialize headers, request objects, credentials or full API exception strings.
        row.update(status="error", error=type(exc).__name__, http_status=getattr(exc, "status_code", None))
    row["parse_ms"] = round((time.perf_counter() - start) * 1000, 3)
    if trace:
        row.update(api_requests=trace.requests, responses=trace.responses, usage=trace.usage)
    return row


def independent_reference(data_dir, road_name, radius):
    """Brute-force distance oracle; no calls to product read/execute/filter methods."""
    paths = [Path(data_dir) / name for name in ("target_road.geojson", "buildings_osm.geojson")]
    raw_roads, raw_buildings = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    frames = [gpd.read_file(path) for path in paths]
    transformers = [Transformer.from_crs(frame.crs, METRIC_CRS, always_xy=True).transform for frame in frames]
    roads = [transform(shape(feature["geometry"]), transformers[0], interleaved=False) for feature in raw_roads["features"]
             if feature["properties"].get("name") == road_name]
    if not roads:
        raise ValueError("参考实现找不到指定道路。")
    distances = {}
    for feature in raw_buildings["features"]:
        identifier = feature["properties"]["full_id"]
        if identifier in distances:
            raise ValueError("建筑物标识重复，无法建立可信参考。")
        geometry = transform(shape(feature["geometry"]), transformers[1], interleaved=False)
        distances[identifier] = min(geometry.distance(road) for road in roads)
    return {"road_name": road_name, "distance_m": radius, "roads": len(roads), "total": len(distances),
            "selected_ids": sorted(key for key, distance in distances.items() if distance <= radius),
            "distances_m": distances, "method": "min(polygon.distance(each matching road)) <= radius"}


def validate_spatial(layers, reference):
    roads, buildings, buffer, selected = layers
    expected = set(reference["selected_ids"])
    actual = selected.full_id.tolist()
    checks = {
        "road_count": len(roads) == reference["roads"],
        "total_count": len(buildings) == reference["total"],
        "selected_ids": set(actual) == expected and len(actual) == len(expected),
        "all_ids": set(buildings.full_id) == set(reference["distances_m"]),
        "flags": all(bool(row.intersects_buffer) == (row.full_id in expected) for _, row in buildings.iterrows()),
        "distances": all(abs(row.nearest_road_m - reference["distances_m"][row.full_id]) <= .011
                         for _, row in buildings.iterrows()),
        "buffer_radius": len(buffer) == 1 and bool(buffer.buffer_m.eq(reference["distance_m"]).all()),
        "crs_and_geometry": all(frame.crs and frame.crs.to_epsg() == 4326 and frame.is_valid.all() for frame in layers),
    }
    return {"passed": all(checks.values()), "checks": {k: bool(v) for k, v in checks.items()},
            "missing_ids": sorted(expected - set(actual)), "unexpected_ids": sorted(set(actual) - expected)}


def check_workflow(row, reference, inputs, records, exports):
    task = BufferTask(**row["actual_task"])
    result = {"business_pass": False, "closed_loop_pass": False, "spatial_pass": False,
              "reproduction_pass": False, "workflow_ms": None, "reproduction_ms": None}
    timings = {}
    def stage(name, function):
        start = time.perf_counter()
        try:
            return function()
        finally:
            timings[name] = round((time.perf_counter() - start) * 1000, 3)
    try:
        record = stage("compute_and_save_ms", lambda: save_run(task, row["query"],
            "DeepSeek（真实API评测）" if row["mode"] == "deepseek" else "本地规则（开发评测）",
            data_dir=inputs, history_dir=records))
        result["task_id"] = record["task_id"]
        layers = stage("reload_ms", lambda: load_layers(record["task_id"], records))
        spatial = stage("reference_check_ms", lambda: validate_spatial(layers, reference))
        result.update(spatial_pass=spatial["passed"], spatial_details=spatial,
                      intersect_count=len(layers[3]), total_count=len(layers[1]))
        package = stage("zip_export_ms", lambda: export_record(record["task_id"], records))
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            zip_ok = all(digest(archive.read(name)) == item["sha256"] for name, item in manifest["files"].items())
        exports.mkdir(exist_ok=True)
        (exports / f"{row['mode']}_{row['case_id']}.zip").write_bytes(package)
        result["zip_pass"] = zip_ok
        result["business_pass"] = spatial["passed"] and zip_ok
        result["workflow_ms"] = round(row["parse_ms"] + sum(timings.get(k, 0) for k in ("compute_and_save_ms", "reload_ms", "zip_export_ms")), 3)
        replay = stage("reproduction_ms", lambda: reproduce_run(record["task_id"], records))
        replay_layers = load_layers(replay["task_id"], records)
        replay_reference = validate_spatial(replay_layers, reference)
        result["reproduction_pass"] = replay["reproduction"]["matches"] and replay_reference["passed"]
        result["reproduction_task_id"] = replay["task_id"]
        result["reproduction_details"] = replay["reproduction"]
        result["reproduction_ms"] = timings["reproduction_ms"]
        result["closed_loop_pass"] = result["business_pass"] and result["reproduction_pass"]
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}" if not row.get("api_requests") else type(exc).__name__
        result["reproduction_ms"] = timings.get("reproduction_ms")
    result["stage_timings"] = timings
    return result


def run_evaluation(output, mode="local", cases_path=DEFAULT_CASES, data_dir=DATA_DIR, regression=True):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    now = datetime.now(timezone(timedelta(hours=8)))
    evidence = output / "evidence"
    inputs, code = evidence / "inputs", evidence / "code"
    inputs.mkdir(parents=True)
    code.mkdir()
    suite = load_cases(cases_path)
    (output / "cases.json").write_bytes(Path(cases_path).read_bytes())
    provenance = {"created_at": now.isoformat(), "environment": environment(), "inputs": {}, "code": {},
                  "cases_sha256": digest(Path(cases_path).read_bytes()), "dataset_version": suite["version"],
                  "source_data_coverage": "未核实下载区域边界，不代表完整区域数据", "model": "deepseek-chat",
                  "temperature": 0, "api_timeout_seconds": 20, "api_retries": 0, "api_workers": 3}
    for name in ("target_road.geojson", "buildings_osm.geojson"):
        source = Path(data_dir) / name
        payload = source.read_bytes()
        (inputs / name).write_bytes(payload)
        provenance["inputs"][name] = {"path": str(source.resolve()), "sha256": digest(payload)}
    for source in Path(__file__).parent.glob("*.py"):
        shutil.copy2(source, code / source.name)
        provenance["code"][source.name] = digest(source.read_bytes())
    (output / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    available = sorted(gpd.read_file(inputs / "target_road.geojson")["name"].dropna().unique().tolist())
    references = {}
    for case in suite["cases"]:
        if case["expected"] == "accept":
            key = f"{case['distance_m']:g}"
            if key not in references:
                references[key] = independent_reference(inputs, case["road_name"], case["distance_m"])
    (output / "reference.json").write_text(json.dumps(references, ensure_ascii=False, indent=2), encoding="utf-8")
    regression_result = {"status": "skipped", "reason": "--skip-regression"}
    if regression:
        print("Running Streamlit and engineering regression tests...", flush=True)
        start = time.perf_counter()
        completed = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "04_Code", "-p", "test_gis*.py"],
                                   cwd=ROOT, capture_output=True, timeout=240)
        log = completed.stdout.decode("utf-8", errors="replace") + completed.stderr.decode("utf-8", errors="replace")
        (output / "regression.log").write_text(log, encoding="utf-8")
        count = re.search(r"Ran (\d+) tests?", log)
        regression_result = {"status": "passed" if completed.returncode == 0 else "failed", "returncode": completed.returncode,
                             "tests_run": int(count[1]) if count else None, "seconds": round(time.perf_counter() - start, 2)}
    rows = []
    modes = ("local", "deepseek")
    for parser_mode in modes:
        skip_reason = None
        client = None
        if mode not in (parser_mode, "both"):
            skip_reason = "本次运行未选择此解析方式"
        elif parser_mode == "deepseek":
            from dotenv import load_dotenv
            from openai import OpenAI
            load_dotenv(ROOT / ".env")
            key = os.getenv("DEEPSEEK_API_KEY")
            if not key:
                skip_reason = "未配置DEEPSEEK_API_KEY"
            else:
                client = OpenAI(api_key=key, base_url="https://api.deepseek.com", timeout=20, max_retries=0)
        try:
            if client:
                with ThreadPoolExecutor(max_workers=3) as pool:
                    futures = {pool.submit(assess_parse, case, parser_mode, available, client): case for case in suite["cases"]}
                    parsed = []
                    for future in as_completed(futures):
                        row = future.result()
                        parsed.append(row)
                        print(f"{parser_mode} {row['case_id']}: {row['status']} correct={row['parse_correct']}", flush=True)
                        with (output / "parse_events.jsonl").open("a", encoding="utf-8") as stream:
                            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                parsed.sort(key=lambda row: [c["id"] for c in suite["cases"]].index(row["case_id"]))
            else:
                parsed = [assess_parse(case, parser_mode, available, skip_reason=skip_reason) for case in suite["cases"]]
            for row in parsed:
                if row["expected"] == "accept" and row["parse_correct"]:
                    reference = references[f"{row['label']['distance_m']:g}"]
                    row["workflow"] = check_workflow(row, reference, inputs, evidence / "tasks", evidence / "downloads")
                    print(f"{parser_mode} {row['case_id']}: closed_loop={row['workflow']['closed_loop_pass']}", flush=True)
                rows.append(row)
                # Keep completed rows even if a later task is interrupted.
                (output / "progress.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            if client:
                client.close()
    report = {"created_at": now.isoformat(), "run_id": output.name, "suite_version": suite["version"],
              "rows": rows, "summary": summarize(rows, modes), "references": references,
              "regression": regression_result, "provenance": provenance}
    write_reports(report, output)
    print(json.dumps({"output": str(output), "summary": report["summary"], "regression": regression_result}, ensure_ascii=True), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("local", "deepseek", "both"), default="local")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--skip-regression", action="store_true")
    args = parser.parse_args()
    directory = args.output_dir or ROOT / "05_Demo" / "evaluation_reports" / (datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:6])
    run_evaluation(directory, args.mode, args.cases, regression=not args.skip_regression)


if __name__ == "__main__":
    main()
