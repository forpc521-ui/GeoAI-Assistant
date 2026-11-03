"""Static, offline evaluation reports; metrics never count skipped runs as successes."""
import csv
import json
import math
from pathlib import Path
import statistics


def rate(passed, total):
    return {"passed": passed, "total": total, "percent": round(100 * passed / total, 2) if total else None}


def timing(values):
    values = sorted(value for value in values if isinstance(value, (int, float)) and math.isfinite(value))
    if not values:
        return {"n": 0, "p50_ms": None, "p95_ms": None}
    position = (len(values) - 1) * .95
    low = int(position)
    p95 = values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (position - low)
    return {"n": len(values), "p50_ms": round(statistics.median(values), 2), "p95_ms": round(p95, 2)}


def summarize(rows, modes):
    result = {}
    for mode in modes:
        subset = [r for r in rows if r["mode"] == mode and r["status"] != "skipped"]
        valid = [r for r in subset if r["expected"] == "accept"]
        invalid = [r for r in subset if r["expected"] == "reject"]
        executed = [r for r in valid if r.get("workflow")]
        result[mode] = {
            "status": "executed" if subset else "skipped",
            "behavior_accuracy": rate(sum(r["parse_correct"] for r in subset), len(subset)),
            "valid_parse_accuracy": rate(sum(r["parse_correct"] for r in valid), len(valid)),
            "invalid_handling_accuracy": rate(sum(r["parse_correct"] for r in invalid), len(invalid)),
            "task_success": rate(sum(bool(r.get("workflow", {}).get("business_pass")) for r in valid), len(valid)),
            "closed_loop_success": rate(sum(bool(r.get("workflow", {}).get("closed_loop_pass")) for r in valid), len(valid)),
            "independent_spatial_check": rate(sum(r["workflow"]["spatial_pass"] for r in executed), len(executed)),
            "reproduction_check": rate(sum(r["workflow"]["reproduction_pass"] for r in executed), len(executed)),
            "categories": {category: rate(sum(r["parse_correct"] for r in subset if r["category"] == category),
                                          sum(r["category"] == category for r in subset))
                           for category in ("standard", "paraphrase", "invalid")},
            "parse_latency": timing([r["parse_ms"] for r in subset]),
            "workflow_latency": timing([r["workflow"]["workflow_ms"] for r in executed if r["workflow"]["business_pass"]]),
            "reproduction_latency": timing([r["workflow"]["reproduction_ms"] for r in executed]),
            "api_errors": sum(r["status"] == "error" for r in subset),
            "api_requests": sum(r.get("api_requests", 0) for r in subset),
            "usage_reported_calls": sum(len(r.get("usage", [])) for r in subset),
            "reported_total_tokens": sum(u.get("total_tokens", 0) or 0 for r in subset for u in r.get("usage", [])),
        }
    return result


def display_rate(item):
    return f"{item['passed']}/{item['total']}（{item['percent']:g}%）" if item["total"] else "未执行/无样本"


def write_reports(report, directory):
    directory = Path(directory)
    (directory / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    headers = ["mode", "case_id", "category", "query", "expected", "status", "parse_correct", "parse_ms", "actual_task", "error", "business_pass", "closed_loop_pass", "intersect_count", "workflow_ms", "reproduction_ms", "task_id"]
    with (directory / "case_results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        for row in report["rows"]:
            flat = {key: row.get(key, "") for key in headers}
            flat["actual_task"] = json.dumps(row.get("actual_task"), ensure_ascii=False)
            workflow = row.get("workflow", {})
            for key in headers[10:]:
                flat[key] = workflow.get(key, "")
            # Prevent spreadsheet formula interpretation of externally returned errors.
            for key, value in flat.items():
                if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                    flat[key] = "'" + value
            writer.writerow(flat)
    lines = ["# GeoAI Assistant 自动评测报告", "", f"评测时间：{report['created_at']}；运行编号：{report['run_id']}", "",
             "## 评测口径", "", "- 冻结的30条开发用例：12条标准表达、8条同义改写、10条异常指令。由开发者编写，未经过外部用户或独立评审复核，不代表线上用户分布或盲测集。",
             "- 参数正确：道路、距离及操作全部与人工标签一致；异常正确：明确拒绝或要求澄清。API错误不计作正确拒绝。",
             "- 业务任务成功：有效指令解析正确，真实计算通过独立参考核对，任务保存、重载及下载文件校验通过。分母为全部有效指令，包含解析失败。",
             "- 闭环成功：业务任务成功，且使用输入快照复现后，图层和参考结果均一致。复现跳过模型，不代表模型回答可复现。",
             "- 空间交叉核验：对原始建筑物逐一计算其到每条道路的最短距离，按距离≤阈值筛选；参考实现不调用产品的计算或筛选函数。底层仍共享Shapely/PROJ，不是QGIS或测绘真值。",
             "- 延迟为本机单轮观测。解析延迟含模型网络时间；业务延迟=解析+计算保存+重载+ZIP导出，不含队列等待、参考核对、复现及浏览器渲染。P95采用线性插值，不是服务SLA。",
             "- 所有阶段和失败均留原始明细、用例、数据及代码摘要；评测任务与正式任务记录隔离。", "",
             "## 指标", "", "| 指标 | 本地规则 | DeepSeek应用链路 |", "|---|---|---|"]
    metric_names = [("behavior_accuracy", "整体指令行为正确率（含异常）"), ("valid_parse_accuracy", "有效指令参数正确率"),
                    ("invalid_handling_accuracy", "异常指令正确处理率"), ("task_success", "业务任务成功率"),
                    ("closed_loop_success", "闭环验证通过率"), ("independent_spatial_check", "已执行任务的空间交叉核验"),
                    ("reproduction_check", "已执行任务的复现核验")]
    for key, label in metric_names:
        cells = [display_rate(report["summary"][mode][key]) for mode in ("local", "deepseek")]
        lines.append(f"| {label} | {cells[0]} | {cells[1]} |")
    lines += ["", "### 分类表现", "", "| 类别 | 本地规则 | DeepSeek应用链路 |", "|---|---|---|"]
    for category, label in (("standard", "标准表达"), ("paraphrase", "同义改写"), ("invalid", "异常指令")):
        values = [display_rate(report["summary"][mode]["categories"][category]) for mode in ("local", "deepseek")]
        lines.append(f"| {label} | {values[0]} | {values[1]} |")
    lines += ["", "### 延迟和API观测", ""]
    for mode, summary in report["summary"].items():
        lines.append(f"- {mode}：状态={summary['status']}；API请求={summary['api_requests']}；接口错误={summary['api_errors']}；已返回usage的调用={summary['usage_reported_calls']}；这些调用的总tokens={summary['reported_total_tokens']}。未返回usage的消耗未知，不估算费用。")
        for field, label in (("parse_latency", "解析"), ("workflow_latency", "成功业务任务"), ("reproduction_latency", "复现")):
            item = summary[field]
            lines.append(f"  - {label}：n={item['n']}；P50={item['p50_ms']} ms；P95={item['p95_ms']} ms。")
    regression = report["regression"]
    lines += ["", "## 页面与工程回归", "", f"状态：{regression['status']}；测试数：{regression.get('tests_run', '未执行')}；耗时：{regression.get('seconds', '未执行')}秒。完整日志见 regression.log。",
              "AppTest覆盖页面入口、统计、图层数据、表格切换、任务保存及复现；不验证真实浏览器渲染，也不代替用户可用性测试。", "",
              "## 独立参考统计", "", "| 距离（米） | 本地建筑物总数 | 相交参考数量 |", "|---|---|---|"]
    for radius, reference in sorted(report["references"].items(), key=lambda item: float(item[0])):
        lines.append(f"| {radius} | {reference['total']} | {len(reference['selected_ids'])} |")
    failures = [row for row in report["rows"] if row["status"] != "skipped" and (not row["parse_correct"] or (row["expected"] == "accept" and not row.get("workflow", {}).get("closed_loop_pass")))]
    lines += ["", "## 失败案例（完整保留）", ""]
    if not failures:
        lines.append("本轮已执行用例未发现失败；小规模开发测试不代表任意指令均可靠。")
    for row in failures:
        lines.append(f"- {row['mode']} / {row['case_id']}：{row['query']}；预期={row['expected']}；实际={row['status']}；参数={json.dumps(row.get('actual_task'), ensure_ascii=False)}；说明={row.get('error') or row.get('workflow', {}).get('error') or '请查明细中的核验结果'}。")
    skipped = [row for row in report["rows"] if row["status"] == "skipped"]
    if skipped:
        lines += ["", f"未执行项：{len(skipped)} 条；原因：{skipped[0].get('error')}。未执行项不计入已执行准确率。"]
    lines += ["", "## 结论边界与下一轮建议", "",
              "- 当前仅评测昌盛路及本地建筑数据；输入覆盖范围尚未核实，统计不代表区域内全部建筑。",
              "- 本地规则只支持有限句式，泛化表现应以同义改写组为准；DeepSeek表现是本轮、当前模型返回版本、当前提示词与前置校验共同作用的结果。",
              "- 若出现异常指令被接受，应优先补充道路/任务范围校验，再使用独立新增用例回归；若仅同义改写失败，应区分当前支持边界和需改进的理解能力。",
              "- 尚未测量真实用户完成率、人工操作基线、节省时间、生产并发或线上稳定性，不能据本报告宣称这些收益。",
              "- 本轮用于建立基线，不修改产品解析逻辑，也不把失败样本从分母剔除。简历引用时必须注明样本数、有效指令分母、数据范围及评测日期。", "",
              "## 证据", "", "cases.json：冻结用例；results.json：全部指标/原始响应/参数/阶段耗时；case_results.csv：逐例结果；reference.json：逐建筑距离与参考筛选；provenance.json：数据、代码、环境摘要；evidence/：输入、代码及独立任务记录；regression.log：工程测试日志。"]
    markdown = "\n".join(lines) + "\n"
    (directory / "report.md").write_text(markdown, encoding="utf-8")
    # The report is fully offline, with no external resources or executable JS.
    import markdown_it
    body = markdown_it.MarkdownIt("commonmark", {"html": False}).enable("table").render(markdown)
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GeoAI评测报告</title><style>body{max-width:1100px;margin:40px auto;padding:0 24px;font:16px/1.8 system-ui,"Microsoft YaHei",sans-serif;color:#182b40}h1,h2{color:#145a75}table{border-collapse:collapse;width:100%;margin:20px 0}td,th{border:1px solid #cad6df;padding:9px;text-align:left}th{background:#edf5fa}code{overflow-wrap:anywhere}li{margin:6px 0}a{color:#12607a}</style>' + body + '</html>'
    (directory / "report.html").write_text(page, encoding="utf-8")
