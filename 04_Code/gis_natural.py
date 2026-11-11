"""Constrained task parsing and real GIS execution. No generated code is executed."""
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re

import geopandas as gpd

from gis_real_test import DATA_DIR, METRIC_CRS

MAX_DISTANCE_M = 5000
DISTANCE = re.compile(r"(?<![\d.+-])(\d+(?:\.\d+)?)\s*(千米|公里|km|米|m)(?![A-Za-z])", re.I)
COMMAND = re.compile(
    r"(?:请)?(?:帮我)?(?:分析|统计|筛选|查找|找出|查询|查看)\s*"
    r"(?P<road>[\w\u4e00-\u9fff·]+(?:路|街|道))\s*"
    r"(?:周边|周围|附近|两侧)?\s*(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>千米|公里|km|米|m)\s*(?:范围)?(?:内|以内)?(?:的)?\s*"
    r"(?:建筑物|建筑|楼宇)(?:数量|总数|有多少(?:个)?)?[。！？?!]?", re.I)

# Optional reporting clauses, not a second spatial operation. Keep this grammar
# bounded: unknown clauses must not silently disappear in local-rule mode.
STAT_SCOPE = r"(?:范围内(?:和|及|与)范围外|范围内|范围外)"
STAT_ITEM = STAT_SCOPE + r"(?:的)?(?:建筑物|建筑|楼宇)?(?:的)?(?:数量|总数|占比|比例)"
STAT_CLAUSE = r"(?:并|同时|以及)?(?:统计|计算)" + STAT_ITEM + r"(?:(?:和|及|与|、)" + STAT_ITEM + r")*"
STAT_SUFFIX = re.compile(r"[，,；;。]\s*" + STAT_CLAUSE
                         + r"(?:[，,；;]\s*" + STAT_CLAUSE + r")*[。！？?!]?$")

# Check the complete request before either parser can discard unsupported goals.
# The model's valid buffer JSON does not prove that it captured every intent.
UNSUPPORTED_INTENTS = (
    (re.compile(r"高度|高程|海拔|层高|层数|楼层|建筑面积|建筑密度|容积率|体积|人口|房价|"
                r"\b(?:height|elevation|volume|population)\b", re.I),
     "高度、属性或其他指标统计"),
    (re.compile(r"预测|预估|预报|未来|今后|将来|明年|后年|趋势|变化|时序|历年|历史|"
                r"\b(?:predict\w*|forecast\w*|future|trend\w*)\b", re.I),
     "预测或时间变化分析"),
    (re.compile(r"最短路径|路径规划|可达性|热力|核密度|坡度|坡向|淹没|聚类|"
                r"\b(?:routing|clustering)\b", re.I),
     "其他空间分析"),
)


def validate_intent(text):
    """Reject unsupported goals even when mixed with a valid buffer request."""
    for pattern, description in UNSUPPORTED_INTENTS:
        if pattern.search(text):
            raise ValueError(
                f"当前不支持{description}。仅支持单条道路、单个距离的缓冲区相交建筑物分析，"
                "以及范围内/范围外建筑物数量和占比统计。请移除不支持的要求后重试。")


def split_statistics(text):
    """Separate explicitly supported reporting from the spatial request."""
    match = STAT_SUFFIX.search(text)
    return text[:match.start()].rstrip() if match else text


@dataclass(frozen=True)
class BufferTask:
    road_name: str
    distance_m: float
    operation: str = "road_buffer_buildings"


def validate_task(payload, available_roads):
    if not isinstance(payload, dict) or set(payload) != {"road_name", "distance_m", "operation"}:
        raise ValueError("解析结果字段不完整，仅支持道路缓冲区内建筑物分析。")
    if payload["operation"] != "road_buffer_buildings":
        raise ValueError("当前仅支持道路缓冲区相交建筑物分析。")
    name, distance = payload["road_name"], payload["distance_m"]
    if not isinstance(name, str) or name not in available_roads:
        raise ValueError("道路不存在于当前数据。可用道路：" + "、".join(available_roads))
    if (isinstance(distance, bool) or not isinstance(distance, (float, int))
            or not math.isfinite(distance) or not 0 < distance <= MAX_DISTANCE_M):
        raise ValueError(f"距离必须大于 0 且不超过 {MAX_DISTANCE_M} 米。")
    return BufferTask(name, float(distance))


def explicit_distance(text):
    matches = list(DISTANCE.finditer(text))
    if len(matches) != 1:
        raise ValueError("请只指定一个距离，使用阿拉伯数字和米/公里单位，例如 500 米。")
    match = matches[0]
    # Signed, approximate, ranged and negated requests are outside this first version.
    if re.search(r"[-−~～至到]$", text[:match.start()].rstrip()):
        raise ValueError("请提供单个明确的正数距离。")
    return float(match[1]) * (1000 if match[2].lower() in ("千米", "公里", "km") else 1)


def parse_task(text, available_roads, client=None):
    text = text.strip()
    # 将常见中文距离表达转换为标准数字格式
    text = text.replace("半公里", "0.5公里")
    text = text.replace("半千米", "0.5公里")
    if not text or len(text) > 500:
        raise ValueError("请输入不超过 500 字的分析指令。")
    validate_intent(text)
    distance = explicit_distance(text)
    if not 0 < distance <= MAX_DISTANCE_M:
        raise ValueError(f"距离必须大于 0 且不超过 {MAX_DISTANCE_M} 米。")
    spatial_text = split_statistics(text)
    if any(word in spatial_text for word in ("之外", "范围外", "不在", "不相交", "完全包含", "完全位于", "删除", "覆盖")):
        raise ValueError("当前仅支持缓冲区相交分析；可附加统计范围内/范围外数量和占比，不支持范围外筛选、完全包含或数据修改。")
    if client is None:
        match = COMMAND.fullmatch(spatial_text)
        if not match:
            raise ValueError("本地规则仅支持约定句式。请使用：分析昌盛路周边500米范围内的建筑物，统计范围内和范围外的数量，并计算范围内建筑物占比。其他表述可尝试DeepSeek模式。")
        payload = {"road_name": match["road"], "distance_m": distance,
                   "operation": "road_buffer_buildings"}
    else:
        response = client.chat.completions.create(
            model="deepseek-chat", temperature=0, max_tokens=300,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": (
                "你只提取GIS任务，不回答分析结果。只支持一条道路、一个明确距离的缓冲区相交建筑物分析。"
                "只返回JSON，字段严格为 operation、road_name、distance_m。"
                "operation必须为road_buffer_buildings；distance_m为米制数值。"
                "附加统计范围内、范围外数量或占比仍属于同一个任务，不增加JSON字段。"
                "范围内指与缓冲区相交（含边界接触），范围外为当前建筑物数据的补集；"
                "占比分母为当前输入建筑物总数。范围外筛选、完全包含及数据修改不支持。"
                "平均高度等属性统计、预测未来、未来十年变化及其他时序分析均不支持。"
                "只要整条指令包含任何不支持的要求，即使还包含合法缓冲区任务，也必须返回null；"
                "不得丢弃不支持的要求后退化为普通缓冲区统计。"
                "缺少参数、多个道路/距离或其他任务时使用null，不猜测。"
                "可用道路：" + json.dumps(available_roads, ensure_ascii=False))},
                {"role": "user", "content": text}])
        try:
            payload = json.loads(response.choices[0].message.content)
        except (TypeError, ValueError, IndexError, AttributeError) as exc:
            raise ValueError("模型未返回有效任务，请改用本地规则解析。") from exc
    task = validate_task(payload, available_roads)
    # A regional library can contain numeric names (e.g. "5") which must not
    # match the distance "500", and short names contained in longer names.
    mention_names = sorted({name for name in available_roads if name and not name.isdigit()}, key=lambda name: (-len(name), name))
    pattern = '|'.join(re.escape(name) for name in mention_names)
    named_roads = list(dict.fromkeys(match.group(0) for match in re.finditer(pattern, text))) if pattern else []
    if named_roads != [task.road_name] or not math.isclose(task.distance_m, distance, abs_tol=1e-8):
        raise ValueError("解析参数与原指令不一致，请明确指定一条可用道路及一个距离。")
    if not any(word in text for word in ("建筑", "楼宇")):
        raise ValueError("请明确指定分析对象为建筑物。")
    return task


def read_inputs(data_dir=DATA_DIR):
    from gis_feature import read_layer
    data_dir = Path(data_dir)
    roads = read_layer(data_dir, "target_road.geojson", ["LineString", "MultiLineString"])
    buildings = read_layer(data_dir, "buildings_osm.geojson", ["Polygon", "MultiPolygon"])
    if "name" not in roads or roads["name"].dropna().empty:
        raise ValueError("道路文件没有可用于匹配的名称。")
    for frame in (roads, buildings):
        west, south, east, north = frame.total_bounds
        if not (114 <= west <= east <= 120 and 0 <= south <= north <= 84):
            raise ValueError("输入超出 EPSG:32650 适用区域，请确认分析投影。")
    return roads, buildings


def execute_task(task, data_dir=DATA_DIR):
    roads, buildings = read_inputs(data_dir)
    available = sorted(roads["name"].dropna().unique().tolist())
    task = validate_task(asdict(task), available)
    roads = roads.loc[roads["name"].eq(task.road_name)].copy()
    road = roads.to_crs(METRIC_CRS).geometry.union_all()
    projected = buildings.to_crs(METRIC_CRS)
    area = road.buffer(task.distance_m)
    buildings = buildings.copy()
    buildings["nearest_road_m"] = projected.geometry.distance(road).round(2).to_numpy()
    buildings["intersects_buffer"] = projected.geometry.intersects(area).to_numpy()
    selected = buildings.loc[buildings["intersects_buffer"]].copy()
    buffer = gpd.GeoDataFrame({"name": [f"{task.road_name} {task.distance_m:g}米缓冲区"],
                               "buffer_m": [task.distance_m]}, geometry=[area], crs=METRIC_CRS).to_crs(4326)
    return roads, buildings, buffer, selected
