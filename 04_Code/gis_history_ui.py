"""Historical runs can be viewed without the current live input files."""
import json
import logging

import streamlit as st

from gis_history import (HISTORY_DIR, engine_hashes, environment, export_record,
                         list_records, load_layers, load_record, reproduce_run)
from gis_natural import BufferTask
from gis_result_view import render_analysis_result


def render_history():
    st.subheader("分析任务记录")
    st.caption("每次成功分析自动保存指令、参数、数据快照、统计与结果。复现使用当时的数据和参数，不再请求模型。")
    st.session_state.setdefault("history_reproduction", None)
    st.caption(f"保存位置：{HISTORY_DIR}")
    try:
        records, problems = list_records(HISTORY_DIR)
    except OSError as exc:
        st.error(f"无法读取任务目录：{exc}")
        return
    for problem in problems:
        st.warning("有记录无法通过完整性核验：" + problem)
    if not records:
        st.info("暂无完整的分析任务记录。请到“自然语言空间分析”提交一次任务；升级前的分析不会自动补记。")
        return
    st.dataframe([{"时间（北京时间）": item["created_at"], "任务编号": item["task_id"],
                   "道路": item["task"]["road_name"], "距离（米）": item["task"]["distance_m"],
                   "建筑物总数": item["statistics"]["buildings_total"],
                   "相交建筑物": item["statistics"]["buildings_intersect"],
                   "原任务编号": item["parent_task_id"] or ""} for item in records],
                 hide_index=True, alt="已保存的分析任务时间、参数和统计列表")
    indexed = {item["task_id"]: item for item in records}
    selected_id = st.selectbox("选择历史任务", list(indexed), key="history_task",
        format_func=lambda key: f"{indexed[key]['created_at']} · {indexed[key]['task']['road_name']} · {indexed[key]['task']['distance_m']:g}米 · {key[-6:]}")
    try:
        manifest = load_record(selected_id, HISTORY_DIR)
        layers = load_layers(selected_id, HISTORY_DIR)
    except Exception as exc:
        st.error(f"无法打开历史任务：{exc}")
        return
    if manifest.get("dataset_source"):
        st.info(manifest["dataset_source"]["coverage"])
        st.caption("本地导入数据集：" + manifest["dataset_source"]["dataset_id"])
    if manifest.get("online_source"):
        st.info(manifest["online_source"]["coverage"])
        st.markdown("在线数据来源：[© OpenStreetMap contributors](https://www.openstreetmap.org/copyright)。复现使用获取时的输入快照，不重新联网。")
    st.write("原始指令：" + manifest["query"])
    st.caption(f"解析方式：{manifest['parser']}；任务编号：{selected_id}。")
    if manifest.get("parent_task_id"):
        st.caption("复现自任务：" + manifest["parent_task_id"])
    with st.expander("任务参数、数据来源与计算环境"):
        st.json(manifest)
    current_changed = manifest["engine_hashes"] != engine_hashes() or manifest["environment"] != environment()
    if current_changed:
        st.info("当前计算代码或依赖版本与原任务不同。复现会使用已存输入快照和当前计算程序，并报告结果是否一致。归档代码仅供追溯，不自动执行。")
    if st.button("使用当时数据复现", key="history_reproduce", type="primary"):
        st.session_state.history_reproduction = None
        try:
            with st.spinner("正在用输入快照重新计算并比对原结果…"):
                replay = reproduce_run(selected_id, HISTORY_DIR)
            st.session_state.history_reproduction = {"parent_id": selected_id, "record": replay}
        except Exception as exc:
            logging.exception("Historical GIS replay failed")
            st.error(f"复现失败，原任务未改写：{exc}")
    replay_info = st.session_state.history_reproduction
    if replay_info and replay_info["parent_id"] == selected_id:
        replay = replay_info["record"]
        if replay["reproduction"]["matches"]:
            st.success("复现结果与原任务一致：道路、建筑物、缓冲区、筛选结果及距离核验通过。")
        else:
            st.warning("复现结果与原任务存在差异，请展开报告查看。原结果和复现结果均已保留。")
        st.caption("已另存复现任务：" + replay["task_id"] + "。刷新任务列表后可选中查看。")
        with st.expander("复现对比报告"):
            st.json(replay["reproduction"])
    st.download_button("下载完整任务包（ZIP）", data=export_record(selected_id, HISTORY_DIR),
                       file_name=selected_id + ".zip", mime="application/zip", key="history_zip")
    st.download_button("下载任务记录（JSON）", data=json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                       file_name=selected_id + ".json", mime="application/json", key="history_manifest")
    render_analysis_result(layers, BufferTask(**manifest["task"]), prefix="history")
