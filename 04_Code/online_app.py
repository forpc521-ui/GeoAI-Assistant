"""Standalone entrypoint for hosting the real online-data workflow."""
import streamlit as st
from gis_online_ui import render_online_analysis
from gis_history_ui import render_history

st.set_page_config(page_title='GeoAI · 北京在线道路分析', layout='wide')
st.title('GeoAI · 北京在线道路分析')
st.caption('道路搜索 → 候选确认 → 在线建筑轮廓 → 空间计算 → 导出与输入快照复现。无需上传地理数据。')
page = st.sidebar.radio('功能', ['在线分析', '任务记录'])
if page == '在线分析':
    render_online_analysis()
else:
    render_history()
