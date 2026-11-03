"""Shared result display, independent of natural-language and history pages."""
import streamlit as st
import pandas as pd

from gis_feature import make_map


def result_csv(layers, task, only_selected=True):
    """Export the current result layers, including an empty detail header."""
    roads, buildings, _, selected = layers
    frame = selected if only_selected else buildings
    fields = [key for key in ("full_id", "name", "nearest_road_m", "intersects_buffer") if key in frame]
    detail = frame[fields].copy()
    detail.insert(0, "distance_m", task.distance_m)
    detail.insert(0, "road_name", task.road_name)
    count = len(buildings)
    summary = pd.DataFrame([{
        "road_name": task.road_name, "distance_m": task.distance_m,
        "road_features": len(roads), "buildings_total": count,
        "buildings_intersect": len(selected), "buildings_outside": count - len(selected),
        "intersect_ratio": len(selected) / count if count else None,
        "outside_ratio": (count - len(selected)) / count if count else None,
    }])
    return tuple(table.to_csv(index=False).encode("utf-8-sig") for table in (summary, detail))


def render_analysis_result(layers, task, prefix="nl"):
    roads, buildings, buffer, selected = layers
    radius = f"{task.distance_m:g}"
    st.success(f"已执行：{task.road_name} · {radius}米缓冲区 · 相交建筑物分析")
    total, inside, outside = st.columns(3)
    total.metric("建筑物总数", len(buildings))
    inside.metric(f"与{radius}米缓冲区相交", len(selected))
    outside.metric("范围外", len(buildings) - len(selected))
    if len(buildings):
        st.write(f"范围内建筑物占比：{len(selected) / len(buildings):.2%}；"
                 f"范围外建筑物占比：{(len(buildings) - len(selected)) / len(buildings):.2%}。")
    else:
        st.write("范围内/范围外建筑物占比：无数据（建筑物总数为0）。")
    st.caption("统计口径：范围内为与缓冲区相交的建筑物（含边界接触）；范围外为当前输入建筑物中其余要素；占比分母为当前输入建筑物总数。")
    st.write(f"当前导出的{task.road_name}含{len(roads)}个道路要素；在{len(buildings)}个建筑物中，"
             f"{len(selected)}个与{radius}米缓冲区相交（含边界接触）。")
    st.caption("蓝线：道路 · 浅蓝面：缓冲区 · 绿色：相交建筑物 · 橙色：范围外建筑物。计算使用EPSG:32650，显示与下载使用EPSG:4326。")
    basemap = st.checkbox("显示在线底图（需要网络）", key=f"{prefix}_basemap")
    st.pydeck_chart(make_map(roads, buildings, buffer, selected, basemap), alt="本次分析的缓冲区和建筑物分布")
    only_selected = st.checkbox("仅查看相交建筑物", value=True, key=f"{prefix}_selected_only")
    frame = selected if only_selected else buildings
    fields = [key for key in ("full_id", "name", "nearest_road_m", "intersects_buffer") if key in frame]
    st.dataframe(frame[fields].rename(columns={"full_id": "OSM标识", "name": "建筑名称",
        "nearest_road_m": "距道路最短距离（米）", "intersects_buffer": "与缓冲区相交"}),
        hide_index=True, alt="本次分析的建筑物、道路距离和相交结果")
    st.subheader("下载本次分析结果")
    summary_csv, detail_csv = result_csv(layers, task, only_selected)
    st.download_button("下载统计汇总 CSV", data=summary_csv,
                       file_name=f"summary_{radius}m.csv", mime="text/csv",
                       key=f"{prefix}_summary_csv", on_click="ignore")
    scope = "相交建筑物" if only_selected else "全部建筑物"
    st.download_button(f"下载当前表格 CSV（{scope}）", data=detail_csv,
                       file_name=f"buildings_{radius}m_{'selected' if only_selected else 'all'}.csv",
                       mime="text/csv", key=f"{prefix}_detail_csv", on_click="ignore")
    st.caption("CSV来自当前已保存任务的结果图层。明细范围与上方表格一致；汇总始终统计全部输入建筑物。占比为0至1的小数，总数为0时留空；CSV不含几何，空间图层请下载GeoJSON。")
    for label, layer, filename in (("缓冲区", buffer, f"roads_buffer_{radius}m.geojson"),
                                   ("相交建筑物", selected, f"buildings_{radius}m_results.geojson")):
        st.download_button(f"下载{label}", data=layer.to_json(ensure_ascii=False, drop_id=True).encode("utf-8"),
                           file_name=filename, mime="application/geo+json", key=f"{prefix}_download_{label}")
    st.caption("任务记录已保留本次输入快照和结果文件；原始数据和已有500米结果文件保持不变。")
