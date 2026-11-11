"""Online acquisition UI, independent of the original frozen sample workflow."""
import logging
import tempfile
import streamlit as st
from gis_online import search_roads, fetch_inputs, roads_frame, OnlineDataError, request_osm, ENDPOINT
from gis_natural import BufferTask
from gis_history import save_run, load_record, load_layers
from gis_result_view import render_analysis_result


def render_online_analysis():
    st.subheader('北京在线道路建筑物分析')
    st.caption('无需上传地理文件或配置模型密钥。按完整道路名称搜索；同名不连通路段分别列为候选。公共接口可能不可用，无法保证北京所有道路和建筑物均有数据。')
    st.markdown('数据来源：[© OpenStreetMap contributors](https://www.openstreetmap.org/copyright) · Overpass API · 查询结果缓存1小时')
    with st.expander('在线数据连接设置（搜索超时时先检查这里）'):
        endpoints = list(dict.fromkeys([ENDPOINT, 'https://overpass.private.coffee/api/interpreter']))
        endpoint = st.selectbox('Overpass 数据服务', endpoints, key='online_endpoint')
        connection = st.radio('连接方式', ['使用系统代理设置', '仅本次请求直连（不使用系统代理）'], key='online_connection')
        proxy_mode = 'direct' if connection.startswith('仅本次') else 'system'
        st.caption('备用服务也可能不可用。选择直连只影响本项目的数据请求；不更改系统代理，不关闭HTTPS验证。')
        if st.button('快速检测当前服务（约10秒）', key='online_probe'):
            try:
                import time
                started = time.monotonic()
                request_osm('[out:json][timeout:5];node(1);out ids;', endpoint=endpoint,
                            proxy_mode=proxy_mode, timeout=10, use_cache=False)
                st.success(f'微型请求成功，耗时{time.monotonic()-started:.1f}秒。说明当前服务可连接，但不保证完整道路查询一定成功。')
            except OnlineDataError as exc:
                st.warning('连接检测失败：' + str(exc))
    def requester(query):
        return request_osm(query, endpoint=endpoint, proxy_mode=proxy_mode)
    with st.form('online_search_form'):
        name = st.text_input('北京道路完整名称', value='昌盛路', max_chars=60)
        search = st.form_submit_button('搜索北京道路')
    if search:
        st.session_state.pop('online_candidates', None)
        st.session_state.pop('online_result_id', None)
        try:
            with st.spinner('正在查询北京道路…'):
                candidates, source = search_roads(name, requester=requester)
            st.session_state.online_candidates = (candidates, source)
        except OnlineDataError as exc:
            st.warning(str(exc))
        except Exception:
            logging.exception('Online road search failed')
            st.error('道路搜索未完成，请稍后重试。')
    data = st.session_state.get('online_candidates')
    if not data:
        return
    candidates, source = data
    if not candidates:
        st.info('未找到匹配的北京道路。请使用完整名称；这不代表道路不存在，也不会自动替换成昌盛路。')
        return
    selected = st.selectbox('确认候选路段（共享节点连通分组，不代表整条道路）', range(len(candidates)),
        format_func=lambda i: f"候选{i+1} · {candidates[i]['name']} · {candidates[i]['length_m']/1000:.2f}公里 · OSM {candidates[i]['way_ids'][0]} · {candidates[i]['bbox'][0]:.4f},{candidates[i]['bbox'][1]:.4f}")
    candidate = candidates[selected]
    frame = roads_frame(candidate['elements'], candidate['name'])
    import pydeck as pdk
    center = frame.geometry.union_all().centroid
    st.pydeck_chart(pdk.Deck(map_style=None,
        initial_view_state=pdk.ViewState(longitude=center.x, latitude=center.y, zoom=14),
        layers=[pdk.Layer('GeoJsonLayer', data=frame.__geo_interface__, get_line_color=[30,100,210], get_line_width=5, line_width_min_pixels=3)]),
        alt='所选候选路段的道路形状，无底图')
    st.caption('道路包围范围（西、南、东、北）：' + ', '.join(f'{x:.5f}' for x in candidate['bbox']))
    radius = st.number_input('在线缓冲距离（米）', min_value=1, max_value=1000, value=300, key='online_radius')
    st.warning('仅统计OSM实际返回的有效建筑轮廓；缺失或零返回不能解释为没有建筑物。同名平行道路可能分为不同候选，请逐一确认。范围外数量、占比只描述本次查询样本，不能跨查询区域直接比较。')
    if st.button('确认路段并在线获取建筑物、执行分析', type='primary'):
        st.session_state.pop('online_result_id', None)
        try:
            with st.spinner('正在获取建筑物并计算、保存输入快照…'):
                with tempfile.TemporaryDirectory(prefix='geoai-online-') as directory:
                    metadata = fetch_inputs(candidate, radius, directory, requester=requester, road_source=source)
                    record = save_run(BufferTask(candidate['name'], float(radius)),
                        f"在线分析北京市{candidate['name']}候选路段，缓冲{radius}米", '在线OSM路段选择',
                        data_dir=directory, source_metadata=metadata)
                st.session_state.online_result_id = record['task_id']
        except OnlineDataError as exc:
            st.warning(str(exc))
        except Exception:
            logging.exception('Online GIS analysis failed')
            st.error('本次在线分析未完成，请检查网络或数据服务；不会显示旧结果作为新结果。')
    task_id = st.session_state.get('online_result_id')
    if task_id:
        try:
            record = load_record(task_id)
            st.caption('以下为已保存的分析任务，参数见结果标题；更换候选不会自动重算。任务编号：' + task_id)
            metadata = record['online_source']
            st.info(metadata['coverage'])
            if metadata['skipped_invalid_buildings']:
                st.warning(f"本次有{metadata['skipped_invalid_buildings']}个建筑对象因几何不完整或无效被排除。")
            with st.expander('数据来源、获取时间与查询范围'):
                st.json(metadata)
            render_analysis_result(load_layers(task_id), BufferTask(**record['task']), prefix='online')
        except Exception:
            logging.exception('Online record rendering failed')
            st.error('无法读取已保存的在线分析任务，请到任务记录检查。')
