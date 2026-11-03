
from pathlib import Path
import geopandas as gpd
from shapely.geometry import LineString, Polygon

# ========== 1. 项目路径 ==========
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "03_Data" / "gis_samples"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ========== 2. 创建测试道路 ==========
# 模拟数据，非真实道路测绘成果
roads = gpd.GeoDataFrame(
    {"name": ["测试道路"]},
    geometry=[
        LineString([
            (116.395, 39.900),
            (116.405, 39.900)
        ])
    ],
    crs="EPSG:4326"
)

# ========== 3. 创建测试建筑 ==========
buildings = gpd.GeoDataFrame(
    {
        "name": [
            "建筑A",
            "建筑B",
            "建筑C"
        ]
    },
    geometry=[
        Polygon([
            (116.398, 39.901),
            (116.399, 39.901),
            (116.399, 39.9015),
            (116.398, 39.9015)
        ]),
        Polygon([
            (116.402, 39.903),
            (116.403, 39.903),
            (116.403, 39.9035),
            (116.402, 39.9035)
        ]),
        Polygon([
            (116.398, 39.915),
            (116.399, 39.915),
            (116.399, 39.9155),
            (116.398, 39.9155)
        ])
    ],
    crs="EPSG:4326"
)

# ========== 4. 转换为米制投影 ==========
# 测试地点位于北京附近，使用UTM 50N
roads_m = roads.to_crs("EPSG:32650")
buildings_m = buildings.to_crs("EPSG:32650")

# ========== 5. 创建500米缓冲区 ==========
road_geometry = roads_m.geometry.iloc[0]
buffer_polygon = road_geometry.buffer(500)

# ========== 6. 统计建筑物 ==========
buildings_m["distance_m"] = (
    buildings_m.geometry.distance(road_geometry)
)

buildings_m["within_500m"] = (
    buildings_m.geometry.intersects(buffer_polygon)
)

selected = buildings_m[
    buildings_m["within_500m"]
].copy()

print("GIS空间分析完成！")
print(f"建筑物总数：{len(buildings_m)}")
print(f"500米范围内建筑物数量：{len(selected)}")

for _, row in buildings_m.iterrows():
    print(
        f"{row['name']}："
        f"距离道路 {row['distance_m']:.1f} 米，"
        f"是否位于500米范围：{row['within_500m']}"
    )

# ========== 7. 保存GeoJSON ==========
roads.to_file(
    OUTPUT_DIR / "roads.geojson",
    driver="GeoJSON"
)

buildings.to_file(
    OUTPUT_DIR / "buildings.geojson",
    driver="GeoJSON"
)

buffer_gdf = gpd.GeoDataFrame(
    geometry=[buffer_polygon],
    crs=roads_m.crs
)

buffer_gdf.to_crs("EPSG:4326").to_file(
    OUTPUT_DIR / "buffer_500m.geojson",
    driver="GeoJSON"
)

selected.to_crs("EPSG:4326").to_file(
    OUTPUT_DIR / "selected_buildings.geojson",
    driver="GeoJSON"
)

print(f"\n分析结果已保存：{OUTPUT_DIR}")
