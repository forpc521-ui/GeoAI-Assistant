"""Local prepared dataset selection and road-buffer building filtering."""
import json
import logging
import tempfile
import streamlit as st
from gis_local import active_dataset, road_candidates, prepare_analysis, import_dataset
from gis_natural import BufferTask, parse_task
from gis_local_parser import parse_local_query
from gis_history import save_run, load_record, load_layers
from gis_result_view import render_analysis_result


@st.cache_data(max_entries=32,show_spinner=False)
def candidates_cached(directory,dataset_id,name):
    return road_candidates(directory,name)


def render_local_analysis():
    st.subheader('海淀区自然语言分析与建筑物筛选')
    st.caption('使用一次导入的真实数据包。搜索、计算和历史复现不调用在线地理数据接口。')
    with st.expander('首次导入或更新本地数据包'):
        st.caption('只需导入一次，之后保存在本机。支持GeoJSON或GeoPackage；道路应有name字段。GeoPackage需填写对应图层名称。请使用覆盖同一区域、来源明确的配套数据。')
        uploaded_roads=st.file_uploader('导入道路文件',type=['geojson','json','gpkg'],key='library_roads',max_upload_size=512)
        uploaded_buildings=st.file_uploader('导入建筑物文件',type=['geojson','json','gpkg'],key='library_buildings',max_upload_size=512)
        roads_layer=st.text_input('道路图层名称（GeoJSON留空）',key='library_roads_layer')
        buildings_layer=st.text_input('建筑物图层名称（GeoJSON留空）',key='library_buildings_layer')
        source_url=st.text_input('来源链接或提供方说明',key='library_source')
        coverage=st.text_input('实际覆盖范围（未核实全市时请写明局部范围）',key='library_coverage')
        if st.button('校验并导入本地数据包',key='library_import'):
            if not uploaded_roads or not uploaded_buildings or not source_url.strip() or not coverage.strip():
                st.warning('请提供两份配套文件、来源和实际覆盖范围。')
            else:
                try:
                    from pathlib import Path
                    with st.spinner('正在校验并建立本地空间索引…'), tempfile.TemporaryDirectory(prefix='geoai-import-') as staging:
                        roads_path=Path(staging)/('roads'+Path(uploaded_roads.name).suffix)
                        buildings_path=Path(staging)/('buildings'+Path(uploaded_buildings.name).suffix)
                        roads_path.write_bytes(uploaded_roads.getvalue());buildings_path.write_bytes(uploaded_buildings.getvalue())
                        import_dataset(roads_path,buildings_path,roads_layer=roads_layer.strip() or None,
                            buildings_layer=buildings_layer.strip() or None,source_url=source_url.strip(),coverage=coverage.strip())
                    st.session_state.pop('local_result_id',None)
                    st.success('已导入本地数据包，后续筛选无需联网或重新上传。')
                except Exception:
                    logging.exception('Local import failed')
                    st.error('导入失败：请检查坐标系、图层名称、name字段和几何类型。原数据包保持不变。')
    try:
        directory,metadata=active_dataset()
        names=json.loads((directory/'road_names.json').read_text(encoding='utf-8'))
    except (OSError,ValueError,KeyError):
        st.info('尚未导入海淀区数据包。请按05_Demo/LocalData.md导入配套道路与建筑物文件；不会自动使用昌盛路或合成样本替代。')
        return
    st.info('数据覆盖：'+metadata['coverage'])
    st.caption(f"已导入{metadata['roads']['kept_features']}个已命名道路要素，{len(names)}个道路名称，{metadata['buildings']['kept_features']}个建筑物。")
    if metadata['license_url']:
        st.markdown(f"数据署名：[{metadata['attribution']}]({metadata['license_url']})")
    with st.expander('本地数据版本与来源'):
        st.json(metadata)
    example = next((road for road in ['中关村大街','中关村南大街','学院路'] if road in names),names[0])
    st.markdown('**自然语言入口**：输入道路和距离，解析后确认路段，再执行筛选。也可直接在下方搜索道路。')
    st.caption('可选本地规则或DeepSeek理解指令；模型仅接收指令与其中提及的道路名称，不发送建筑物几何。距离、数量和相交结果仍由本地GIS计算。')
    with st.form('local_natural_form'):
        query=st.text_input('海淀区空间分析指令',placeholder=f'分析{example}周边500米范围内的建筑物',key='haidian_query')
        parse_mode=st.selectbox('海淀区指令解析方式',['本地规则（无需API）','DeepSeek（API指令解析）'],key='haidian_parse_mode')
        parse=st.form_submit_button('解析指令并定位道路',type='primary')
    if parse:
        st.session_state.pop('local_result_id',None)
        st.session_state.pop('local_parsed_request',None)
        try:
            with st.spinner('正在解析指令…'):
                task=parse_local_query(query,names,parse_mode)
            if task.distance_m < 0.01:
                raise ValueError('当前页面支持的最小距离为0.01米。')
            st.session_state.local_road_name=task.road_name
            st.session_state.local_radius=float(task.distance_m)
            st.session_state.local_parsed_request={'road':task.road_name,'radius':task.distance_m,
                'query':query,'mode':parse_mode,'dataset_id':metadata['dataset_id']}
            st.success(f'解析成功：{task.road_name}，{task.distance_m:g}米。请确认下面的候选路段后执行筛选。')
        except ValueError as exc:
            st.warning('该道路不在当前海淀区数据包的已命名道路中，请在下方搜索并确认名称。' if str(exc).startswith('道路不存在') else str(exc))
    if st.session_state.get('local_dataset_id') != metadata['dataset_id']:
        # Clear stale widget selections when replacing an imported library.
        if st.session_state.get('local_road_name') not in names:
            st.session_state.pop('local_road_name',None)
        st.session_state.pop('local_result_id',None)
        st.session_state.local_dataset_id=metadata['dataset_id']
    name=st.selectbox('输入或选择道路名称',names,index=None,placeholder='输入道路名称进行查找',key='local_road_name')
    if name is not None:
        candidates=candidates_cached(str(directory),metadata['dataset_id'],name)
        if not candidates:
            st.warning('本地数据中没有找到该道路。')
            return
        candidate=st.selectbox('确认连通路段（不连通的同名道路不合并）',range(len(candidates)),
            format_func=lambda i:f"候选{i+1} · {len(candidates[i])}段 · {candidates[i].to_crs(32650).length.sum()/1000:.2f}公里 · {candidates[i].total_bounds[0]:.4f},{candidates[i].total_bounds[1]:.4f}",key='local_segment')
        roads=candidates[candidate]
        import pydeck as pdk
        center=roads.geometry.union_all().centroid
        st.pydeck_chart(pdk.Deck(map_style=None,initial_view_state=pdk.ViewState(longitude=center.x,latitude=center.y,zoom=13),
            layers=[pdk.Layer('GeoJsonLayer',data=roads.__geo_interface__,get_line_color=[30,100,210],line_width_min_pixels=3)]),alt='所选道路路段位置与形状，无在线底图')
        st.session_state.setdefault('local_radius',500.0)
        radius=st.number_input('建筑物筛选距离（米）',min_value=0.01,max_value=5000.0,value=None,key='local_radius')
        st.caption('同名但不连通的路段分别分析；平行车道也可能分为不同候选。地图和坐标可辅助确认。')
        if st.button('执行本地建筑物筛选',type='primary',key='local_execute'):
            st.session_state.pop('local_result_id',None)
            try:
                with st.spinner('正在读取附近建筑物、计算并保存快照…'):
                    with tempfile.TemporaryDirectory(prefix='geoai-local-') as staging:
                        source=prepare_analysis(directory,roads,radius,staging)
                        parsed=st.session_state.get('local_parsed_request',{})
                        matches=(parsed.get('road')==name and parsed.get('radius')==float(radius)
                                 and parsed.get('dataset_id')==metadata['dataset_id'])
                        query_text=parsed['query'] if matches else f'本地筛选{name}候选{candidate+1}周边{radius}米建筑物'
                        parser=parsed['mode'] if matches else '本地数据包道路选择'
                        record=save_run(BufferTask(name,float(radius)),query_text,parser,data_dir=staging,dataset_metadata=source)
                    st.session_state.local_result_id=record['task_id']
            except ValueError as exc:
                st.warning(str(exc))
            except Exception:
                logging.exception('Local dataset analysis failed')
                st.error('本地筛选未完成，请检查数据包和磁盘权限。')
    task_id=st.session_state.get('local_result_id')
    if task_id:
        try:
            record=load_record(task_id)
            st.caption('以下为已保存任务，更换道路不会自动重算；参数见结果标题。任务编号：'+task_id)
            st.warning(record['dataset_source']['coverage'])
            render_analysis_result(load_layers(task_id),BufferTask(**record['task']),prefix='local')
        except Exception:
            logging.exception('Local result loading failed')
            st.error('保存的筛选结果无法读取，请到任务记录检查。')
