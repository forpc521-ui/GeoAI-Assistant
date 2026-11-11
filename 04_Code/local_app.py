import streamlit as st
from gis_local_ui import render_local_analysis
from gis_history_ui import render_history

st.set_page_config(page_title='GeoAI · 海淀区自然语言与建筑物筛选',layout='wide')
from gis_ui_runtime import protect_page_translation
protect_page_translation()
st.title('GeoAI · 海淀区自然语言与建筑物筛选')
page=st.sidebar.radio('功能',['本地筛选','任务记录'])
if page=='本地筛选':render_local_analysis()
else:render_history()
