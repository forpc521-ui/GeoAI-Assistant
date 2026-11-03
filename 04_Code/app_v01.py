import streamlit as st
from openai import OpenAI
from dotenv import load_dotenv
import os


# 加载环境变量
load_dotenv()


# 初始化DeepSeek
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)


# 页面标题
st.title("GeoAI Assistant")

st.write(
    "基于大语言模型的GIS空间分析助手"
)


# 用户输入
question = st.text_input(
    "请输入你的GIS问题："
)


if st.button("提交"):

    if question:

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content":
                    "你是一名GIS专业助手，"
                    "回答GIS空间分析相关问题。"
                },
                {
                    "role": "user",
                    "content": question
                }
            ]
        )


        answer = response.choices[0].message.content


        st.subheader("AI回答")

        st.write(answer)
