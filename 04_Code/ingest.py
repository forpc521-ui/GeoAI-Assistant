
from pathlib import Path
import json

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


# 1. 项目路径
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "03_Data"
DOCS_DIR = DATA_DIR / "knowledge_base"
VECTOR_DIR = DATA_DIR / "vector_database"

# 2. 中文向量模型
MODEL_NAME = "BAAI/bge-small-zh-v1.5"


# 3. 文本分块函数
def split_text(text, chunk_size=400, overlap=80):
    chunks = []
    step = chunk_size - overlap

    for start in range(0, len(text), step):
        chunk = text[start:start + chunk_size].strip()

        if chunk:
            chunks.append(chunk)

    return chunks


# 4. 加载Markdown文件
documents = []

for file_path in sorted(DOCS_DIR.glob("*.md")):

    # 忽略最开始创建的测试文件
    if file_path.name.lower() == "test.md":
        continue

    content = file_path.read_text(encoding="utf-8-sig")
    chunks = split_text(content)

    for i, chunk in enumerate(chunks):
        documents.append({
            "source": file_path.name,
            "chunk_id": i,
            "content": chunk
        })

    print(f"已读取：{file_path.name}，分块数：{len(chunks)}")


if not documents:
    raise ValueError("未找到可用的Markdown知识文档")


# 5. 加载Embedding模型
print("\n正在加载Embedding模型...")

model = SentenceTransformer(MODEL_NAME)

texts = [doc["content"] for doc in documents]

# 6. 文本向量化
print("正在生成文本向量...")

vectors = model.encode(
    texts,
    batch_size=16,
    normalize_embeddings=True,
    show_progress_bar=True
)

vectors = np.asarray(vectors, dtype="float32")


# 7. 创建FAISS索引
dimension = vectors.shape[1]

index = faiss.IndexFlatIP(dimension)
index.add(vectors)


# 8. 保存数据库
VECTOR_DIR.mkdir(parents=True, exist_ok=True)

faiss.write_index(
    index,
    str(VECTOR_DIR / "gis.index")
)

with open(
    VECTOR_DIR / "metadata.json",
    "w",
    encoding="utf-8"
) as f:
    json.dump(documents, f, ensure_ascii=False, indent=2)


print("\n知识库构建成功！")
print(f"文档分块总数：{len(documents)}")
print(f"向量维度：{dimension}")
print(f"保存位置：{VECTOR_DIR}")
