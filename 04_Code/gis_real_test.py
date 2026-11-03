
from pathlib import Path

import geopandas as gpd
from shapely.ops import unary_union

# 项目根目录：D:\GeoAI-Assistant
ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = ROOT / "03_Data" / "raw_documents" / "osm_test"
OUT_DIR = ROOT / "03_Data" / "gis_target_road_results"

ROADS_FILE = DATA_DIR / "target_road.geojson"
BUILDINGS_FILE = DATA_DIR / "buildings_osm.geojson"

BUFFER_M = 500
METRIC_CRS = "EPSG:32650"  # 北京昌平区适用的米制投影坐标系

def main():
    # 1. 检查文件
    for path in [ROADS_FILE, BUILDINGS_FILE]:
        if not path.exists():
            raise FileNotFoundError(f"找不到数据文件：{path}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 2. 读取真实数据
    roads = gpd.read_file(ROADS_FILE)
    buildings = gpd.read_file(BUILDINGS_FILE)

    print("道路原始数量：", len(roads))
    print("建筑物原始数量：", len(buildings))
    print("道路原始坐标系：", roads.crs)
    print("建筑物原始坐标系：", buildings.crs)

    # 3. 缺少 CRS 时停止，不能通过指定经纬度坐标系猜测数据含义。
    if roads.crs is None or buildings.crs is None:
        raise ValueError("输入数据缺少 CRS，请确认导出坐标系后再运行。")
    for frame in (roads, buildings):
        west, south, east, north = frame.to_crs("EPSG:4326").total_bounds
        if not (114 <= west <= east <= 120 and 0 <= south <= north <= 84):
            raise ValueError("输入超出 EPSG:32650 适用区域，请先确认米制分析投影。")

    # 4. 去掉空几何，保留道路和建筑物对应的几何类型
    roads = roads[roads.geometry.notna()].copy()
    roads = roads[~roads.geometry.is_empty].copy()
    roads = roads[
        roads.geometry.geom_type.isin(["LineString", "MultiLineString"])
    ].copy()

    buildings = buildings[buildings.geometry.notna()].copy()
    buildings = buildings[~buildings.geometry.is_empty].copy()
    buildings = buildings[
        buildings.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    ].copy()

    # 修复无效建筑物面
    buildings.geometry = buildings.geometry.apply(
        lambda geom: geom if geom.is_valid else geom.buffer(0)
    )
    buildings = buildings[
        buildings.geometry.notna()
        & ~buildings.geometry.is_empty
        & buildings.geometry.is_valid
    ].copy()

    if roads.empty:
        raise ValueError("没有可用的道路线，请检查 GeoJSON 图层类型。")
    if buildings.empty:
        raise ValueError("没有可用的建筑物面，请检查 GeoJSON 图层类型。")

    # 5. 转换到米制坐标系，避免直接用经纬度计算 500 米
    roads_m = roads.to_crs(METRIC_CRS)
    buildings_m = buildings.to_crs(METRIC_CRS)

    # 6. 生成全部道路的 500 米缓冲区
    road_union = unary_union(roads_m.geometry.tolist())
    buffer_union = road_union.buffer(BUFFER_M)

    # 7. 计算建筑物到最近道路的距离及是否进入缓冲区
    buildings_m["nearest_road_m"] = (
        buildings_m.geometry.distance(road_union).round(2)
    )
    buildings_m["within_500m"] = (
        buildings_m.geometry.intersects(buffer_union)
    )

    inside_count = int(buildings_m["within_500m"].sum())
    total_count = len(buildings_m)

    
    # 8. 输出结果：只保留 500 米范围内的建筑物
    buffer_gdf = gpd.GeoDataFrame(
        {"buffer_m": [BUFFER_M]},
        geometry=[buffer_union],
        crs=METRIC_CRS,
    ).to_crs("EPSG:4326")

    # 关键：筛选建筑物，不能直接保存全部 buildings_m
    result_gdf = buildings_m[
        buildings_m["within_500m"]
    ].copy()

    result_gdf = result_gdf.to_crs("EPSG:4326")

    buffer_path = OUT_DIR / "roads_buffer_500m.geojson"
    buildings_path = OUT_DIR / "buildings_500m_results.geojson"

    buffer_gdf.to_file(
        buffer_path,
        driver="GeoJSON",
        index=False,
    )

    result_gdf.to_file(
        buildings_path,
        driver="GeoJSON",
        index=False,
    )

    print("\n真实 GIS 分析完成！")
    print(f"有效道路数量：{len(roads_m)}")
    print(f"有效建筑物数量：{total_count}")
    print(f"500 米范围内建筑物：{inside_count}")
    print(f"500 米范围外建筑物：{total_count - inside_count}")
    print(f"最终输出建筑物数量：{len(result_gdf)}")
    print(f"缓冲区结果：{buffer_path}")
    print(f"建筑物结果：{buildings_path}")


if __name__ == "__main__":
    main()

