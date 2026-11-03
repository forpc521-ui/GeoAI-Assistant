# GeoAI Assistant

面向AI产品经理求职展示的本地GIS分析MVP：受约束指令 → 参数校验 → 真实空间计算 → 地图/统计/表格 → CSV/GeoJSON → 任务快照与历史复现。另保留GIS知识问答原型。

## 先运行已验证的环境

PowerShell：

```powershell
Set-Location 'D:\GeoAI-Assistant'
& '.\venv\Scripts\python.exe' -m streamlit run '.\04_Code\app.py' --server.address 127.0.0.1
```

打开 http://localhost:8501 ，侧边栏选择“自然语言空间分析”，使用“本地规则（无需API）”，输入：

```text
分析昌盛路周边500米范围内的建筑物
```

当前样本预期：510个建筑物，105个相交，405个在范围外，范围内占比20.59%。300/1000米相交数为53/191。每次成功提交自动保存新任务；过滤和下载不重复保存。历史页面可查看、导出ZIP/JSON及用输入快照重算。

已有服务占用8501时先使用原地址；不要重复启动。服务运行期间终端保持占用，Ctrl+C停止。图层显示要求浏览器支持WebGL；在线底图/前端资源可能依赖网络。

## 验证命令与结果

```powershell
Set-Location 'D:\GeoAI-Assistant'
& '.\venv\Scripts\python.exe' -m unittest discover -s 04_Code -p 'test_gis*.py' -v
& '.\venv\Scripts\python.exe' '.\04_Code\evaluate_project.py' --mode local
```

2026-10-18现有环境：39项回归通过。冻结30条开发指令中本地规则标准表达12/12、同义改写0/8、异常10/10；有效任务端到端与复现均12/20（60%），已执行12条空间/复现核验各12/12。详细分母见01_Product/Metrics.md；不能称为模型准确率、用户效果或100%总体闭环。真实DeepSeek与RAG在线质量本轮未测。

## 环境与新机器安装

当前验证环境：Windows、Python3.12.3、Streamlit1.65.0。直接依赖固定在requirements-demo.txt；全量已安装版本记录在environment-verified.txt。现有环境无需升级。下列新环境步骤尚未经干净机器验证：

```powershell
Set-Location 'D:\GeoAI-Assistant'
py -3.12 -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-demo.txt
& '.\.venv\Scripts\python.exe' -m streamlit run '.\04_Code\app.py' --server.address 127.0.0.1
```

新环境请在两条验证命令中相应将venv改为.venv。若缺包或版本无法安装，保留错误信息另建环境处理，不覆盖原环境。

空间主线需要 `03_Data/raw_documents/osm_test/target_road.geojson` 与 `buildings_osm.geojson`。固定500米页面还需要 `03_Data/gis_target_road_results/` 既有结果；全量测试还需要 `03_Data/gis_samples/` 模拟图层。数据未随公开源码默认分发，迁移需另备经授权数据。

可选DeepSeek：复制.env.example为.env后由使用者填入自己的DEEPSEEK_API_KEY；已有.env不要覆盖。问答还需要knowledge_base、vector_database及BAAI/bge-small-zh-v1.5缓存/下载；ingest.py可建库但会写入索引，先备份。API解析仅提取参数，GIS才计算结果。

## 能力与数据边界

- 当前只有昌盛路、单距离0至5000米（不含0），建筑物相交筛选与内外数量/占比；本地规则限定句式。
- 同名道路合并，EPSG:32650米制计算；intersects包括部分相交与边界接触；输出4326。占比分母是本次输入，不是行政区全量。
- 自然语言与历史页面支持汇总/明细CSV和空间GeoJSON；固定500米旧页面保留原GeoJSON导出，功能不完全对称。
- 不支持任意任务规划、文件上传、多道路比较、高度/人口、时序预测、路径规划或CAD/BIM。知识问答是独立入口。
- 本地qmd有OpenStreetMap署名及许可链接；下载日期、渠道、完整范围和许可链仍待补证，详见DataSources.md。

## 材料导航

| 材料 | 文件 |
|---|---|
| 产品需求与流程 | 01_Product/PRD.md、UserFlow.md |
| 来源/边界与指标 | 01_Product/DataSources.md、Metrics.md |
| 实际架构 | 02_Technology/Architecture.md |
| 验收摘要 | 05_Demo/acceptance_20261018/ |
| 演示与录屏 | 05_Demo/DemoScript.md |
| 环境与安全 | 05_Demo/DeliveryAndSecurity.md |
| 求职与面试 | 05_Demo/ResumeAndInterview.md |

密钥、环境、正式任务记录和待审核数据已加入.gitignore。任务包不含.env，但含指令、原始几何和本机路径，分享前审阅。本轮未公开发布项目；本地演示不等于生产部署。

## 求职作品集

- [AI 产品 PRD](05_Demo/Portfolio/GeoAI-Assistant_PRD_v2.0_AI产品版.md)
- [方案选型与 AI 指标](05_Demo/Portfolio/GeoAI_作品集_方案选型与AI指标.md)
- [评测报告](05_Demo/acceptance_20261018/report.md)
- [演示脚本](05_Demo/DemoScript.md)

公开仓库提供源码、文档与历史验收证据；原始空间数据、个人简历、API 密钥、虚拟环境及任务快照留在本机。克隆后需自行准备经授权的数据，才能运行空间分析和依赖该数据的测试。GitHub 仓库链接用于源码与材料展示，尚非在线应用。
