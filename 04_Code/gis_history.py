"""Atomic, file-backed GIS runs with immutable inputs and reproducibility checks."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
from importlib.metadata import version
import io
import json
from pathlib import Path
import platform
import re
import shutil
from uuid import uuid4
import zipfile

import geopandas as gpd
import numpy as np

from gis_natural import BufferTask, execute_task
from gis_real_test import DATA_DIR, METRIC_CRS

HISTORY_DIR = Path(__file__).resolve().parents[1] / "03_Data" / "analysis_tasks"
INPUT_NAMES = ("target_road.geojson", "buildings_osm.geojson")
OUTPUT_NAMES = ("roads.geojson", "buildings.geojson", "buffer.geojson", "selected_buildings.geojson")
ENGINE_NAMES = ("gis_natural.py", "gis_feature.py", "gis_real_test.py", "gis_history.py")
ARTIFACTS = tuple("inputs/" + name for name in INPUT_NAMES) + tuple("results/" + name for name in OUTPUT_NAMES) + tuple("engine/" + name for name in ENGINE_NAMES)
TASK_ID = re.compile(r"\d{8}T\d{12}_[0-9a-f]{12}")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def environment():
    return {"python": platform.python_version(), **{name: version(name) for name in
            ("geopandas", "shapely", "pyproj", "pyogrio", "numpy")}}


def engine_hashes():
    return {name: sha256(Path(__file__).with_name(name).read_bytes()) for name in ENGINE_NAMES}


def record_path(task_id, history_dir=HISTORY_DIR):
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise ValueError("任务编号格式无效。")
    root = Path(history_dir).resolve()
    path = (root / task_id).resolve()
    if path.parent != root:
        raise ValueError("任务目录超出记录范围。")
    return path


def statistics(layers):
    roads, buildings, _, selected = layers
    return {"roads": len(roads), "buildings_total": len(buildings),
            "buildings_intersect": len(selected), "buildings_outside": len(buildings) - len(selected)}


def load_record(task_id, history_dir=HISTORY_DIR):
    path = record_path(task_id, history_dir)
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        if (manifest["schema_version"] != 1 or manifest["task_id"] != task_id
                or manifest["status"] != "completed" or set(manifest["files"]) != set(ARTIFACTS)):
            raise ValueError("记录结构或版本不支持。")
        for filename in ARTIFACTS:
            artifact = (path / filename).resolve()
            if not artifact.is_relative_to(path) or sha256(artifact.read_bytes()) != manifest["files"][filename]["sha256"]:
                raise ValueError(f"记录文件校验失败：{filename}")
        BufferTask(**manifest["task"])
        for key in ("created_at", "query", "parser", "statistics", "sources", "environment", "engine_hashes"):
            if key not in manifest:
                raise ValueError(f"记录缺少字段：{key}")
        return manifest
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"任务记录不完整或无法读取：{task_id}") from exc


def list_records(history_dir=HISTORY_DIR):
    records, problems = [], []
    root = Path(history_dir)
    if not root.exists():
        return records, problems
    for path in sorted(root.iterdir(), reverse=True):
        if not path.is_dir() or not TASK_ID.fullmatch(path.name):
            continue
        try:
            records.append(load_record(path.name, root))
        except ValueError as exc:
            problems.append(f"{path.name}：{exc}")
    return records, problems


def load_layers(task_id, history_dir=HISTORY_DIR):
    manifest = load_record(task_id, history_dir)
    path = record_path(task_id, history_dir)
    layers = tuple(gpd.read_file(path / "results" / name) for name in OUTPUT_NAMES)
    if statistics(layers) != manifest["statistics"]:
        raise ValueError("保存的统计与图层数量不一致。")
    return layers


def compare_layers(saved, replayed):
    details = {}
    for name, old, new in zip(OUTPUT_NAMES, saved, replayed):
        if len(old) != len(new):
            details[name] = False
            continue
        if len(old) == 0:
            details[name] = True
            continue
        old = old.to_crs(4326).reset_index(drop=True)
        new = new.to_crs(4326).reset_index(drop=True)
        matches = all(a.equals_exact(b, 1e-9, normalize=True) for a, b in zip(old.geometry, new.geometry))
        for field in ("full_id", "intersects_buffer"):
            if field in old or field in new:
                matches = matches and field in old and field in new and old[field].equals(new[field])
        if "nearest_road_m" in old or "nearest_road_m" in new:
            matches = (matches and "nearest_road_m" in old and "nearest_road_m" in new
                       and np.allclose(old.nearest_road_m, new.nearest_road_m, atol=0.011, rtol=0))
        details[name] = bool(matches)
    return {"matches": all(details.values()), "layers": details,
            "saved_statistics": statistics(saved), "replayed_statistics": statistics(replayed),
            "geometry_tolerance_degrees": 1e-9, "distance_tolerance_m": 0.011}


def save_run(task, query, parser, data_dir=DATA_DIR, expected_fingerprint=None,
             history_dir=HISTORY_DIR, parent_id=None):
    """Compute against captured bytes, then publish all files with one directory rename."""
    sources = [Path(data_dir) / name for name in INPUT_NAMES]
    source_bytes = [path.read_bytes() for path in sources]
    fingerprints = tuple(sha256(data) for data in source_bytes)
    if expected_fingerprint is not None and fingerprints != tuple(expected_fingerprint):
        raise ValueError("分析前源数据发生变化，请重新提交。")
    parent = load_record(parent_id, history_dir) if parent_id else None
    root = Path(history_dir)
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone(timedelta(hours=8)))
    task_id = now.strftime("%Y%m%dT%H%M%S%f") + "_" + uuid4().hex[:12]
    staging = root / (".pending-" + uuid4().hex)
    staging.mkdir()
    try:
        for directory in ("inputs", "results", "engine"):
            (staging / directory).mkdir()
        for name, data in zip(INPUT_NAMES, source_bytes):
            (staging / "inputs" / name).write_bytes(data)
        layers = execute_task(task, staging / "inputs")
        # Store human-readable output even for zero selected features.
        for name, layer in zip(OUTPUT_NAMES, layers):
            (staging / "results" / name).write_text(layer.to_json(ensure_ascii=False, drop_id=True), encoding="utf-8")
        for name in ENGINE_NAMES:
            shutil.copy2(Path(__file__).with_name(name), staging / "engine" / name)
        original_inputs = [gpd.read_file(staging / "inputs" / name) for name in INPUT_NAMES]
        manifest = {
            "schema_version": 1, "task_id": task_id, "status": "completed",
            "created_at": now.isoformat(), "query": query, "parser": parser,
            "parser_config": ({"provider": "DeepSeek", "model": "deepseek-chat", "temperature": 0}
                              if parser.startswith("DeepSeek") else {"provider": "local", "mode": parser}),
            "task": asdict(task), "statistics": statistics(layers), "parent_task_id": parent_id,
            "analysis": {"metric_crs": METRIC_CRS, "output_crs": "EPSG:4326",
                         "predicate": "intersects", "boundary_touch_included": True,
                         "distance": "geometry distance to union of matching road features",
                         "coverage": "仅本地导出数据；下载区域边界未核实"},
            "sources": [{"original_path": str(path.resolve()), "snapshot": "inputs/" + name,
                         "sha256": digest, "crs": str(frame.crs), "feature_count": len(frame)}
                        for path, name, digest, frame in zip(sources, INPUT_NAMES, fingerprints, original_inputs)],
            "environment": environment(),
            "engine_hashes": {name: sha256((staging / "engine" / name).read_bytes()) for name in ENGINE_NAMES},
            "files": {name: {"sha256": sha256((staging / name).read_bytes()),
                             "bytes": (staging / name).stat().st_size} for name in ARTIFACTS},
        }
        if parent:
            manifest["reproduction"] = compare_layers(load_layers(parent_id, history_dir), layers)
            manifest["reproduction"]["environment_changed"] = parent["environment"] != manifest["environment"]
            manifest["reproduction"]["engine_changed"] = parent["engine_hashes"] != manifest["engine_hashes"]
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        staging.rename(root / task_id)
        return manifest
    finally:
        if staging.exists():
            if staging.resolve().parent != root.resolve() or not staging.name.startswith(".pending-"):
                raise ValueError("临时目录超出任务记录范围，已停止清理。")
            shutil.rmtree(staging)


def reproduce_run(task_id, history_dir=HISTORY_DIR):
    manifest = load_record(task_id, history_dir)
    return save_run(BufferTask(**manifest["task"]), manifest["query"], "历史参数复现（跳过模型）",
                    data_dir=record_path(task_id, history_dir) / "inputs",
                    expected_fingerprint=[manifest["sources"][i]["sha256"] for i in range(2)],
                    history_dir=history_dir, parent_id=task_id)


def export_record(task_id, history_dir=HISTORY_DIR):
    load_record(task_id, history_dir)
    path = record_path(task_id, history_dir)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("manifest.json",) + ARTIFACTS:
            archive.writestr(name, (path / name).read_bytes())
    return output.getvalue()
