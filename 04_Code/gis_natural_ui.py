"""Natural-language task UI. Saved 500 m outputs remain untouched."""
import hashlib
import logging
import os

import streamlit as st

from gis_result_view import render_analysis_result
from gis_natural import DATA_DIR, BufferTask, parse_task, read_inputs
from gis_history import HISTORY_DIR, load_layers, load_record, save_run


def source_fingerprint():
    return tuple(hashlib.sha256((DATA_DIR / name).read_bytes()).hexdigest()
                 for name in ("target_road.geojson", "buildings_osm.geojson"))


@st.cache_data(max_entries=12, show_spinner=False)
def cached_inputs(directory, fingerprint):
    return read_inputs(directory)


def show_parse_error(exc):
    """Map existing parser validation to public guidance; never echo exceptions."""
    message = str(exc)
    if message.startswith(("当前不支持", "当前仅支持")):
        st.warning("当前不支持该能力：仅支持单条道路、单个距离的缓冲区相交建筑物分析，以及范围内/范围外数量和占比统计。请移除其他要求后重试。")
        return
    guidance = (
        (("请输入不超过",), "请输入1至500字的分析指令。"),
        (("请只指定一个距离", "请提供单个明确", "距离必须"), "请指定一个大于0且不超过5000米的距离，使用阿拉伯数字和米/公里单位。"),
        (("道路不存在",), "道路不在当前数据中，请使用上方列出的可用道路。"),
        (("本地规则仅支持",), "本地规则未识别该句式。请参照示例，或尝试DeepSeek模式。"),
        (("解析结果字段", "模型未返回", "解析参数与原指令"), "未能确认有效任务，请明确指定一条可用道路、一个距离及建筑物对象，或改用本地规则。"),
        (("请明确指定分析对象",), "请明确指定分析对象为建筑物。"),
    )
    for prefixes, hint in guidance:
        if message.startswith(prefixes):
            st.warning("输入校验未通过：" + hint)
            return
    logging.exception("Unexpected parser validation failure")
    st.error("执行异常：指令解析未能完成，请重试或改用本地规则。")


def render_natural_analysis():
    st.subheader("自然语言空间分析")
    st.session_state.setdefault("nl_result", None)
    st.markdown("输入道路、距离和建筑物分析任务，自动生成缓冲区、统计及地图。")
    st.caption("示例：分析昌盛路周边300米范围内的建筑物。也支持500米、1000米或0.5公里。")
    st.caption("本地规则支持约定句式，可附加：统计范围内和范围外的数量，并计算范围内建筑物占比。其他自然语言表述可尝试DeepSeek，仍仅支持单条道路缓冲区建筑物分析。")
    try:
        fingerprint = source_fingerprint()
        input_roads, _ = cached_inputs(DATA_DIR, fingerprint)
        available = sorted(input_roads["name"].dropna().unique().tolist())
    except Exception:
        logging.exception("Natural GIS input loading failed")
        st.error("执行异常：无法加载分析数据，请检查输入文件、坐标系和读取权限。详细信息见终端日志。")
        return
    st.caption("当前可用道路：" + "、".join(available) + "。范围为本地导出数据；距离支持大于0且不超过5000米。")
    with st.expander("参数说明与统计口径"):
        st.write("道路：仅限上方列出的单条道路；同名道路要素合并后计算。距离：大于0且不超过5000米，支持米/公里，半公里等于500米。")
        st.write("范围内：建筑物与道路缓冲区相交，包含部分相交和边界接触；范围外：当前输入建筑物中的其余要素。按要素计数，不按建筑面积或人口统计。")
        st.write("占比分母为当前输入建筑物总数；总数为0时占比记为无数据。距离为建筑几何到合并道路几何的最短距离，结果保留两位小数。")
        st.caption("统计仅覆盖本地导出数据，不代表整个行政区。DeepSeek仅提取任务参数；地图、距离和数量由空间计算产生。")
    with st.form("nl_form"):
        text = st.text_input("请输入空间分析指令", placeholder="分析昌盛路周边500米范围内的建筑物", key="nl_query")
        mode = st.selectbox("指令解析方式", ["本地规则（无需API）", "DeepSeek（使用已有API配置）"], key="nl_mode")
        submitted = st.form_submit_button("解析并执行分析", type="primary")
    if submitted:
        st.session_state.nl_result = None
        stage = "parse"
        try:
            with st.spinner("正在解析指令并执行真实空间分析…"):
                client = None
                if mode.startswith("DeepSeek"):
                    from openai import OpenAI
                    api_key = os.getenv("DEEPSEEK_API_KEY")
                    if not api_key:
                        st.error("执行异常：DeepSeek尚未配置，请配置API或改用本地规则。")
                        return
                    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=30, max_retries=0)
                task = parse_task(text, available, client)
                stage = "execute"
                manifest = save_run(task, text, mode, data_dir=DATA_DIR,
                                    expected_fingerprint=fingerprint, history_dir=HISTORY_DIR)
                st.session_state.nl_result = {"task_id": manifest["task_id"]}
        except ValueError as exc:
            if stage == "parse":
                show_parse_error(exc)
            else:
                logging.exception("Natural GIS execution validation failed")
                st.error("执行异常：数据或结果校验未通过。请检查输入数据；若源数据已更新，请重新提交。详细信息见终端日志。")
            return
        except OSError:
            logging.exception("GIS task could not be saved")
            st.error("执行异常：本次任务未能完成保存，请检查任务目录的写入权限和磁盘空间，再重新提交。")
            return
        except Exception:
            logging.exception("Natural language GIS analysis failed")
            st.error("执行异常：本次分析失败。若使用DeepSeek，请检查API连接或额度；也可改用本地规则。详细信息见终端日志。")
            return
    result = st.session_state.nl_result
    if result is None:
        return
    if "task_id" not in result:
        st.info("任务记录功能已更新，请重新提交一次指令以保存任务。")
        return
    try:
        manifest = load_record(result["task_id"], HISTORY_DIR)
        task = BufferTask(**manifest["task"])
        layers = load_layers(result["task_id"], HISTORY_DIR)
    except Exception:
        logging.exception("Natural GIS saved result loading failed")
        st.error("执行异常：无法读取或核验本次结果，请重新提交分析，或检查任务记录文件。详细信息见终端日志。")
        return
    st.caption(f"任务已保存：{manifest['task_id']}。可在侧边栏“分析任务记录”中查看和复现。")
    st.caption(f"本次指令：{manifest['query']}；解析方式：{manifest['parser']}。地图与统计由GeoPandas计算。")
    with st.expander("查看解析后的任务"):
        st.json(manifest["task"])
    with st.expander("本次数据来源与坐标系"):
        for source in manifest["sources"]:
            st.text(f"输入快照：{source['snapshot']}；原始坐标系：{source['crs']}；要素数：{source['feature_count']}")
            st.text("SHA-256：" + source["sha256"])
        st.write(f"计算坐标系：{manifest['analysis']['metric_crs']}（米）；输出坐标系：{manifest['analysis']['output_crs']}。")
        st.caption("以上来自本次任务保存的输入元数据与内容校验值。文件名含osm不能独立证明上游来源。数据提供方、下载日期、下载区域边界、许可及完整性：待补充。")
    render_analysis_result(layers, task)
