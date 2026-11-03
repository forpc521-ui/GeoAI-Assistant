"""Local real-data and sample road-buffer views, independent of RAG/API."""
from pathlib import Path
import json
import logging
import hashlib

import geopandas as gpd
import pydeck as pdk
import streamlit as st

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "03_Data" / "gis_samples"
FILES = ("roads.geojson", "buildings.geojson", "buffer_500m.geojson", "selected_buildings.geojson")


def read_layer(directory, filename, geometry_types, allow_empty=False):
    path = Path(directory) / filename
    if not path.is_file():
        raise FileNotFoundError(f"缺少文件：{path}")
    try:
        frame = gpd.read_file(path)
    except Exception as exc:
        raise ValueError(f"无法读取 {filename}，请检查 GeoJSON 格式。") from exc
    if frame.crs is None:
        raise ValueError(f"{filename} 缺少坐标系。")
    if frame.empty and not allow_empty:
        raise ValueError(f"{filename} 没有可用要素。")
    if (frame.geometry.isna().any() or frame.geometry.is_empty.any()
            or not frame.geometry.is_valid.all()
            or not frame.geom_type.isin(geometry_types).all()):
        raise ValueError(f"{filename} 含空几何、无效几何或不支持的几何类型。")
    return frame.to_crs("EPSG:4326")


def calculate(directory):
    roads = read_layer(directory, FILES[0], ["LineString", "MultiLineString"])
    buildings = read_layer(directory, FILES[1], ["Polygon", "MultiPolygon"])
    # Fixed projection is appropriate only for this Beijing-area sample.
    bounds = roads.total_bounds
    if not (114 <= bounds[0] <= bounds[2] <= 120 and 0 <= bounds[1] <= bounds[3] <= 84):
        raise ValueError("本示例仅支持 UTM 50N 区域内的道路，请使用原始北京模拟数据。")
    road = roads.to_crs("EPSG:32650").geometry.union_all()
    projected = buildings.to_crs("EPSG:32650")
    area = road.buffer(500)
    projected["distance_m"] = projected.geometry.distance(road)
    projected["within_500m"] = projected.geometry.intersects(area)
    if "name" not in projected:
        projected["name"] = [f"建筑{i + 1}" for i in range(len(projected))]
    buildings = projected.to_crs("EPSG:4326")
    buffer = gpd.GeoDataFrame({"name": ["道路 500 米缓冲区"]}, geometry=[area], crs="EPSG:32650").to_crs("EPSG:4326")
    return roads, buildings, buffer, buildings[buildings["within_500m"]].copy()


def run_analysis(directory=SAMPLE_DIR):
    roads, buildings, buffer, selected = calculate(directory)
    # Inputs are retained; only the two analysis outputs are regenerated.
    buffer.to_file(Path(directory) / FILES[2], driver="GeoJSON")
    selected.to_file(Path(directory) / FILES[3], driver="GeoJSON")


def load_results(directory=SAMPLE_DIR):
    roads, buildings, expected_buffer, expected_selected = calculate(directory)
    buffer = read_layer(directory, FILES[2], ["Polygon", "MultiPolygon"])
    selected = read_layer(directory, FILES[3], ["Polygon", "MultiPolygon"], allow_empty=True)
    # Avoid showing a map/count from a previous set of input files.
    if (not buffer.geometry.union_all().equals_exact(expected_buffer.geometry.union_all(), 1e-8, normalize=True)
            or len(selected) != len(expected_selected)
            or not selected.geometry.union_all().equals_exact(expected_selected.geometry.union_all(), 1e-8, normalize=True)):
        raise ValueError("结果文件与当前道路、建筑数据不一致，请点击“运行 500 米分析”重新生成。")
    return roads, buildings, buffer, selected


def make_map(roads, buildings, buffer, selected, basemap=False):
    layers = []
    for layer_id, frame, color, width in (
        ("buffer", buffer, [55, 125, 220, 55], 1),
        ("buildings", buildings, [235, 140, 40, 180], 1),
        ("selected", selected, [30, 170, 100, 220], 2),
        ("roads", roads, [40, 90, 220, 255], 4),
    ):
        layers.append(pdk.Layer(
            "GeoJsonLayer", id=layer_id, data=json.loads(frame.to_json()),
            pickable=True, filled=layer_id != "roads", stroked=True,
            get_fill_color=color, get_line_color=color[:3],
            line_width_min_pixels=width,
        ))
    bounds = buildings.total_bounds
    view = pdk.data_utils.compute_view([
        [float(bounds[0]), float(bounds[1])],
        [float(bounds[2]), float(bounds[3])],
        [float(buffer.total_bounds[0]), float(buffer.total_bounds[1])],
        [float(buffer.total_bounds[2]), float(buffer.total_bounds[3])],
    ])
    return pdk.Deck(
        layers=layers,
        initial_view_state=view,
        map_provider="carto" if basemap else None,
        map_style="light" if basemap else None,
        tooltip={"text": "{name}"},
    )


@st.cache_data(max_entries=4, show_spinner=False)
def cached_real_results(data_dir, out_dir, fingerprint):
    from gis_real_results import load_real_results
    return load_real_results(data_dir, out_dir)


def render_gis_analysis():
    st.subheader("道路 500 米缓冲区分析")
    source = st.selectbox("分析数据", ["真实道路与建筑（OSM）", "模拟数据演示"], key="gis_source")
    if source == "真实道路与建筑（OSM）":
        render_real_analysis()
        return
    st.warning("模拟数据演示：道路和建筑均为人工构造，不代表真实测绘成果，不可用于工程决策。")
    st.markdown("点击运行，统计与道路 500 米缓冲区相交的建筑，并在地图上查看结果。距离为建筑边界到道路的最短距离；接触缓冲区边界也计入。")
    st.caption("计算使用米制投影 EPSG:32650；地图和下载结果使用 EPSG:4326。本功能无需 DeepSeek API。")
    with st.expander("文件位置与恢复方法"):
        st.code(str(SAMPLE_DIR), language=None)
        st.markdown("需要 roads.geojson、buildings.geojson 两个输入；运行后生成 buffer_500m.geojson 和 selected_buildings.geojson。若输入缺失，可在项目根目录运行以下命令，**重新生成并覆盖四份模拟数据**：")
        st.code(r".\venv\Scripts\python.exe .\04_Code\gis_analysis.py", language="powershell")
    if st.button("运行 500 米分析", type="primary", key="run_gis"):
        try:
            with st.spinner("正在计算道路缓冲区和建筑距离…"):
                run_analysis(SAMPLE_DIR)
            st.success("分析完成，已更新缓冲区和选中建筑 GeoJSON。")
        except Exception as exc:
            logging.exception("GIS analysis failed")
            st.error(f"分析失败：{exc}")
            st.info("请检查输入文件和目录写入权限。恢复模拟数据的方法见上方“文件位置与恢复方法”。")
            return
    try:
        roads, buildings, buffer, selected = load_results(SAMPLE_DIR)
    except (FileNotFoundError, ValueError) as exc:
        st.error(str(exc))
        st.info("输入文件缺失或损坏时，请按“文件位置与恢复方法”处理；结果文件缺失或过期时，点击“运行 500 米分析”。")
        return
    except Exception:
        logging.exception("GIS output loading failed")
        st.error("无法加载 GIS 结果，请检查文件读取权限，并查看终端日志。")
        return
    st.caption("当前展示：从本地 GeoJSON 文件读取的分析结果。")
    total, inside, outside = st.columns(3)
    total.metric("模拟建筑总数", len(buildings))
    inside.metric("500 米范围内", len(selected))
    outside.metric("范围外", len(buildings) - len(selected))
    basemap = st.checkbox("显示在线底图（需要网络）", value=False, key="gis_basemap")
    st.caption("蓝线：道路 · 浅蓝面：500 米缓冲区 · 绿色：范围内建筑 · 橙色：范围外建筑。默认仅显示分析图层；可拖动、缩放并悬停查看名称。")
    st.pydeck_chart(make_map(roads, buildings, buffer, selected, basemap),
                    alt="模拟道路、500 米缓冲区和范围内外建筑分布图")
    table = buildings[["name", "distance_m", "within_500m"]].copy()
    table.columns = ["建筑名称", "距道路最短距离（米）", "与500米缓冲区相交"]
    table["距道路最短距离（米）"] = table["距道路最短距离（米）"].round(1)
    st.dataframe(table, hide_index=True, alt="所有模拟建筑的最短道路距离与筛选结果")
    st.subheader("下载模拟分析结果")
    for filename in FILES[2:]:
        st.download_button(f"下载 {filename}", data=(SAMPLE_DIR / filename).read_bytes(),
                           file_name=filename, mime="application/geo+json", key=f"download_{filename}")


def render_real_analysis():
    from gis_real_results import DATA_DIR, OUT_DIR, INPUT_FILES, OUTPUT_FILES

    st.markdown("读取目标道路的真实 500 米缓冲区，统计与缓冲区相交的建筑物。建筑物只要部分相交或接触边界就计入；距离为建筑边界到最近道路的最短距离。")
    st.caption("计算：EPSG:32650（米）；地图与下载：EPSG:4326。统计范围仅限本地建筑物数据集。无需 DeepSeek API。")
    with st.expander("数据来源与文件位置"):
        st.code(str(DATA_DIR), language=None)
        st.write("输入：" + "、".join(INPUT_FILES))
        st.code(str(OUT_DIR), language=None)
        st.write("结果：" + "、".join(OUTPUT_FILES))
        st.caption("页面只读取并核验文件，不覆盖原始数据或结果。若结果过期，请先检查输入，再使用 gis_real_test.py 重新生成。")
    recheck = st.button("运行 500 米分析", type="primary", key="run_gis")
    try:
        paths = [DATA_DIR / name for name in INPUT_FILES] + [OUT_DIR / name for name in OUTPUT_FILES]
        # Content hashes invalidate the cache even if files are replaced in place.
        fingerprint = tuple(hashlib.sha256(path.read_bytes()).hexdigest() for path in paths)
        if recheck:
            cached_real_results.clear()
        with st.spinner("正在读取真实数据并核验缓冲区、建筑物与距离…"):
            roads, buildings, buffer, selected = cached_real_results(DATA_DIR, OUT_DIR, fingerprint)
    except Exception as exc:
        logging.exception("Real GIS result validation failed")
        st.error(f"真实数据核验失败：{exc}")
        st.info("请检查上述输入与结果文件、CRS 和几何；页面不会回退到模拟结果。")
        return
    if recheck:
        st.success("重新计算核验通过：保存的缓冲区、筛选要素及道路距离与当前输入一致。")
    names = "、".join(roads["name"].dropna().astype(str).unique()) if "name" in roads else "未命名"
    st.caption(f"当前展示：真实 OSM 数据 · 目标道路：{names} · 道路要素 {len(roads)} 个 · 已通过输入与结果一致性核验。")
    total, inside, outside = st.columns(3)
    total.metric("建筑物总数", len(buildings))
    inside.metric("与500米缓冲区相交", len(selected))
    outside.metric("范围外", len(buildings) - len(selected))
    basemap = st.checkbox("显示在线底图（需要网络）", value=False, key="gis_basemap")
    st.caption("蓝线：目标道路 · 浅蓝面：500 米缓冲区 · 绿色：相交建筑物 · 橙色：范围外建筑物。可拖动、缩放并悬停查看名称。")
    st.pydeck_chart(make_map(roads, buildings, buffer, selected, basemap),
                    alt="真实目标道路、500米缓冲区及相交建筑物分布图")
    only_selected = st.checkbox("仅查看相交建筑物", value=True, key="gis_selected_only")
    table = buildings.loc[buildings["within_500m"]].copy() if only_selected else buildings.copy()
    columns = [key for key in ("full_id", "name", "distance_m", "within_500m") if key in table]
    table = table[columns].rename(columns={"full_id": "OSM标识", "name": "建筑名称",
        "distance_m": "距道路最短距离（米）", "within_500m": "与500米缓冲区相交"})
    table["距道路最短距离（米）"] = table["距道路最短距离（米）"].round(2)
    st.dataframe(table, hide_index=True, alt="真实建筑物的OSM标识、名称、道路距离及相交筛选结果")
    st.subheader("下载真实分析结果")
    for filename in OUTPUT_FILES:
        st.download_button(f"下载 {filename}", data=(OUT_DIR / filename).read_bytes(),
                           file_name=filename, mime="application/geo+json", key=f"real_download_{filename}")
