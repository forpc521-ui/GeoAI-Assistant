"""Read and independently verify the saved target-road analysis; never write data."""
import numpy as np

from gis_real_test import DATA_DIR, OUT_DIR, BUFFER_M, METRIC_CRS

INPUT_FILES = ("target_road.geojson", "buildings_osm.geojson")
OUTPUT_FILES = ("roads_buffer_500m.geojson", "buildings_500m_results.geojson")


def load_real_results(data_dir=DATA_DIR, out_dir=OUT_DIR):
    from gis_feature import read_layer

    roads = read_layer(data_dir, INPUT_FILES[0], ["LineString", "MultiLineString"])
    buildings = read_layer(data_dir, INPUT_FILES[1], ["Polygon", "MultiPolygon"])
    buffer = read_layer(out_dir, OUTPUT_FILES[0], ["Polygon", "MultiPolygon"])
    selected = read_layer(out_dir, OUTPUT_FILES[1], ["Polygon", "MultiPolygon"], allow_empty=True)
    # Do not apply a Beijing projection to arbitrary replacement data.
    for frame in (roads, buildings):
        west, south, east, north = frame.total_bounds
        if not (114 <= west <= east <= 120 and 0 <= south <= north <= 84):
            raise ValueError("输入数据超出 EPSG:32650 适用区域，请先确认分析投影。")
    road = roads.to_crs(METRIC_CRS).geometry.union_all()
    projected = buildings.to_crs(METRIC_CRS)
    expected_area = road.buffer(BUFFER_M)
    projected["distance_m"] = projected.geometry.distance(road)
    projected["within_500m"] = projected.geometry.intersects(expected_area)
    saved_area = buffer.to_crs(METRIC_CRS).geometry.union_all()
    if (len(buffer) != 1 or "buffer_m" not in buffer
            or not buffer["buffer_m"].eq(BUFFER_M).all()
            or saved_area.hausdorff_distance(expected_area) > 0.001
            or saved_area.symmetric_difference(expected_area).area > 0.01):
        raise ValueError("缓冲区结果与当前道路的 500 米缓冲区不一致，请检查或重新生成结果。")
    # Match every feature (including multiplicity), not just count or dissolved area.
    # Compare in the original geographic CRS, avoiding round-trip coordinate noise.
    expected_original = buildings.loc[projected["within_500m"]]
    for frame in (buildings, selected):
        if ("full_id" not in frame or frame["full_id"].isna().any()
                or frame["full_id"].duplicated().any()):
            raise ValueError("建筑物缺少唯一 full_id，无法可靠核对筛选结果。")
    expected_by_id = expected_original.set_index("full_id")
    selected_by_id = selected.set_index("full_id")
    if (set(selected_by_id.index) != set(expected_by_id.index)
            or any(not geom.equals_exact(expected_by_id.loc[key].geometry, 1e-10, normalize=True)
                   for key, geom in selected_by_id.geometry.items())):
        raise ValueError("建筑物结果与当前相交筛选不一致（要素标识、几何或数量不符）。")
    if ("within_500m" not in selected or not selected["within_500m"].eq(True).all()
            or "nearest_road_m" not in selected):
        raise ValueError("筛选结果缺少正确的相交标记或距离字段。")
    distances = selected.to_crs(METRIC_CRS).geometry.distance(road).to_numpy()
    try:
        saved_distances = selected["nearest_road_m"].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("结果中的道路距离不是有效数值。") from exc
    if not np.allclose(saved_distances, distances, atol=0.011, rtol=0):
        raise ValueError("结果中的道路距离与重新计算不一致。")
    # Keep original source geometries and names; add computed fields for the table.
    buildings["distance_m"] = projected["distance_m"].to_numpy()
    buildings["within_500m"] = projected["within_500m"].to_numpy()
    return roads, buildings, buffer, selected
