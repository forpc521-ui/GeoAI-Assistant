# 北京本地数据包筛选

## 使用入口

```powershell
Set-Location 'D:\GeoAI-Assistant'
& '.\venv\Scripts\python.exe' -m streamlit run '.\04_Code\local_app.py' --server.address 127.0.0.1 --server.port 8503
```

打开 http://localhost:8503 。原app.py也增加了“北京本地数据包（离线筛选）”选项。

展开“首次导入或更新本地数据包”，上传配套道路、建筑物GeoJSON或GeoPackage；GeoPackage需提供正确图层名称。填写来源和实际覆盖范围。点击导入后，数据持久保存至本机03_Data/beijing_library，之后无需重复上传，无需在线道路搜索接口。

如两种图层在同一个GeoPackage中，可在两个文件框选择同一文件，并分别填写图层名。导入失败不会切换已使用的数据包。

道路要求：明确CRS、线或多线几何、name字段中的可用名称。建筑物要求：明确CRS、面或多面几何。无效或不支持的几何、无名道路、名称及几何完全重复对象被排除，数量写入导入元数据。当前继续使用EPSG:32650，不处理超出其适用区域的数据。

## 大文件可用命令导入

网页上传受Streamlit默认文件大小限制；大文件在本机使用命令，不必上传到网页。以下图层名为示意，先用pyogrio.list_layers核对文件中的真实名称：

```powershell
& '.\venv\Scripts\python.exe' -c "import pyogrio; print(pyogrio.list_layers(r'D:\数据\beijing.gpkg'))"
& '.\venv\Scripts\python.exe' '.\04_Code\gis_local.py' --roads 'D:\数据\beijing.gpkg' --roads-layer '道路图层名' --buildings 'D:\数据\beijing.gpkg' --buildings-layer '建筑物图层名' --source-url '数据提供方原始链接' --coverage '数据文件实际覆盖范围'
```

也可传入两份GeoJSON而省略两个layer参数。不要将教学示例数据或局部样本标成北京市全域。

## 数据下载来源与本次状态

- 全市范围优先考虑Geofabrik北京区域：https://download.geofabrik.de/asia/china/beijing.html ，提供PBF、Shapefile和GeoPackage；导入程序直接支持解压后的GeoPackage或Shapefile路径（网页入口不接收Shapefile配套文件）。许可及边界应以提供方说明为准。
- BBBike：https://download.bbbike.org/osm/bbbike/Beijing/ ，其Beijing.poly实际为116.08–116.77E、39.68–40.18N矩形，并非北京市完整行政区，且不覆盖旧昌盛路样本所在区域。不能仅凭文件名Beijing称为全市数据。
- 2026-11-10本机对Geofabrik下载遇到TLS连接失败/连接超时；BBBike包头可访问，但完整下载未完成。没有完成任何新北京数据包的正式导入，也未自动把旧样本或合成数据填入本地库。
- 请从可用网络下载上述来源的文件，或使用已有经授权的北京数据，导入后再开展真实北京市道路筛选。不得关闭TLS验证来掩盖下载失败。

## 计算与结果口径

- 同名但不连通的路段分成候选，选择一个候选计算，不自动合并不同地点的同名道路。平行车道也可能成为不同候选。可查看形状、长度和坐标确认。
- 先按道路缓冲距离加100米的包围框，通过GeoPackage空间索引读取候选建筑物，再交由原GIS引擎计算精确相交关系。边界接触与部分相交计入。
- “范围外”和占比的分母为本次读取的建筑物样本，不是全北京市建筑物总数；不同路段样本的占比不直接作为同一总体比较。
- 无建筑物返回时提示数据覆盖可能不足，不伪造零建筑物分析成功。
- 保存道路与建筑物输入快照、数据集版本、来源、覆盖说明、原包与标准化库摘要、查询范围和计算结果。历史复现沿用快照，不读取当前库或联网。
- 完成导入后搜索和计算完全本地；可选在线底图仍需要网络，默认可不使用。

## 验收

当前已用隔离测试数据验证：导入与持久化、名称检索（含引号）、同名路段分离、空间范围读取、筛选与历史复现全程禁止联网、失败导入保留旧库、缺失范围不伪造结果。真实北京市数据包验收仍待文件到位。

项目原始验收样本及线上合成Demo未替换。此入口是本机应用，不是已发布的公网服务。

新增3项本地库测试已通过；最终全套回归结果记录于本次工作区 outputs/local_library_regression.log，未把测试夹具标注为真实北京数据。
