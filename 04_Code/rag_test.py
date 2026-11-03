
from pathlib import Path
import json

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


# 1. 获取项目根目录
ROOT = Path(__file__).resolve().parent.parent
VECTOR_DIR = ROOT / "03_Data" / "vector_database"

# 2. 加载FAISS向量数据库
index = faiss.read_index(
    str(VECTOR_DIR / "gis.index")
)

# 3. 加载文档元数据
with open(
    VECTOR_DIR / "metadata.json",
    "r",
    encoding="utf-8"
) as f:
    documents = json.load(f)

if index.ntotal != len(documents):
    raise ValueError("向量数量与元数据数量不一致")

print("FAISS向量数据库加载成功！")
print(f"知识片段数量：{index.ntotal}")

# 4. 加载与建库时相同的Embedding模型
model = SentenceTransformer(
    "BAAI/bge-small-zh-v1.5"
)

# 5. 准备三个测试问题
questions = [
    "GIS缓冲区分析是什么？有哪些应用场景？",
    "铁路工程选线需要考虑哪些控制因素？",
    "InSAR沉降监测需要准备哪些数据？"
]

# 6. 逐个测试知识检索
for question in questions:

    print("\n" + "=" * 50)
    print("用户问题：", question)

    # 将用户问题转换为向量
    query_vector = model.encode(
        [question],
        normalize_embeddings=True
    )

    query_vector = np.asarray(
        query_vector,
        dtype="float32"
    )

    # 从FAISS中检索最相关的3个知识片段
    scores, indices = index.search(
        query_vector,
        min(3, index.ntotal)
    )

    for rank, (score, idx) in enumerate(
        zip(scores[0], indices[0]), start=1
    ):

        if idx < 0:
            continue

        doc = documents[int(idx)]

        print(f"\n检索结果 {rank}")
        print("来源文件：", doc["source"])
        print("相似度：", round(float(score), 4))
        print("知识内容：")
        print(doc["content"][:300])

print("\n全部检索测试完成！")
