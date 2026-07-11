"""
碳合规政策 RAG 检索引擎
基于 LangChain + Milvus Lite + BM25 + BGE-Reranker 构建混合检索管线。

功能:
1. 文档加载: 支持 PDF 和 TXT 格式的政策文档
2. 文档切分: RecursiveCharacterTextSplitter
3. 向量化: HuggingFaceEmbeddings (BGE series)
4. 向量检索: Milvus Lite 语义检索
5. BM25 检索: 关键词检索
6. 混合融合: RRF (Reciprocal Rank Fusion) 融合两路检索结果
7. Rerank: BGE-Reranker 精筛排序
"""

import os
import sys
import json
import warnings
import logging
from pathlib import Path
from typing import Optional

# 抑制不必要的警告
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"
warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader, PyPDFLoader
from langchain_huggingface import HuggingFaceEmbeddings

# BM25 检索器
from langchain_community.retrievers import BM25Retriever

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import (
    EMBEDDING_MODEL,
    EMBEDDING_DIM,
    COLLECTION_NAME,
    MILVUS_URI,
    MILVUS_METRIC_TYPE,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    RETRIEVAL_TOP_K,
    RERANK_TOP_K,
    RAW_DOCUMENTS_DIR,
)
from src.data.database import get_milvus_client, init_collection


class CarbonPolicyRAG:
    """碳合规政策 RAG 检索引擎"""

    def __init__(self, collection_name: str = COLLECTION_NAME):
        """
        初始化 RAG 引擎。

        Args:
            collection_name: Milvus 集合名称
        """
        self.collection_name = collection_name
        self._embeddings: Optional[HuggingFaceEmbeddings] = None
        self._reranker = None
        self._bm25_docs: list[Document] = []
        self._bm25_retriever: Optional[BM25Retriever] = None
        self._milvus_client = None

    # ========================================
    # 延迟初始化 (Lazy Init)
    # ========================================

    @property
    def embeddings(self) -> HuggingFaceEmbeddings:
        """延迟加载 Embedding 模型"""
        if self._embeddings is None:
            print(f"[RAG] 正在加载 Embedding 模型: {EMBEDDING_MODEL} ...")
            self._embeddings = HuggingFaceEmbeddings(
                model_name=EMBEDDING_MODEL,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True},
            )
            print("[RAG] Embedding 模型加载完成。")
        return self._embeddings

    @property
    def reranker(self):
        """延迟加载 Reranker 模型"""
        if self._reranker is None:
            try:
                from sentence_transformers import CrossEncoder
                from config.settings import RERANKER_MODEL
                print(f"[RAG] 正在加载 Reranker 模型: {RERANKER_MODEL} ...")
                self._reranker = CrossEncoder(RERANKER_MODEL)
                print("[RAG] Reranker 模型加载完成。")
            except ImportError:
                print("[RAG] sentence-transformers 未安装, 跳过 Reranker。")
                self._reranker = False  # 标记为不可用
            except Exception as e:
                print(f"[RAG] Reranker 加载失败: {e}, 跳过重排序。")
                self._reranker = False
        return self._reranker

    @property
    def milvus_client(self):
        """延迟获取 Milvus 客户端，检查并加载集合"""
        if self._milvus_client is None:
            self._milvus_client = get_milvus_client()
            # 确保集合已加载（Milvus 返回 None 或抛出异常时自动加载）
            try:
                self._milvus_client.load_collection(self.collection_name)
            except Exception:
                pass
        return self._milvus_client

    # ========================================
    # 文档加载与切分
    # ========================================

    def load_documents(self, file_paths: list[str]) -> list[Document]:
        """
        加载政策文档 (支持 PDF 和 TXT)。

        Args:
            file_paths: 文件路径列表

        Returns:
            加载后的 Document 列表
        """
        all_docs = []
        for fp in file_paths:
            fp = str(fp)
            if not os.path.exists(fp):
                print(f"[RAG] 文件不存在, 跳过: {fp}")
                continue

            ext = Path(fp).suffix.lower()
            if ext == ".pdf":
                loader = PyPDFLoader(fp)
            elif ext in (".txt", ".md"):
                loader = TextLoader(fp, encoding="utf-8-sig")
            else:
                print(f"[RAG] 不支持的文件格式: {ext}, 跳过: {fp}")
                continue

            docs = loader.load()
            # 添加来源元数据
            for doc in docs:
                doc.metadata["source_file"] = Path(fp).name
            all_docs.extend(docs)
            print(f"[RAG] 已加载: {Path(fp).name} ({len(docs)} 页/段)")

        return all_docs

    def split_documents(self, documents: list[Document]) -> list[Document]:
        """
        将文档切分为较小的语义块。

        Args:
            documents: 原始文档列表

        Returns:
            切分后的文档块列表
        """
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=["\n\n", "\n", "。", "，", "；", " ", ""],
        )
        chunks = splitter.split_documents(documents)
        print(f"[RAG] 文档切分完成: {len(documents)} 个文档 → {len(chunks)} 个块")
        return chunks

    # ========================================
    # 向量入库
    # ========================================

    def ingest_documents(self, file_paths: list[str], force_rebuild: bool = False) -> int:
        """
        完整管线: 加载 → 切分 → 向量化 → 存入 Milvus。
        同时将文档存入 BM25 索引。

        Args:
            file_paths: 要导入的文件路径列表
            force_rebuild: 是否强制重建集合 (删除旧数据)

        Returns:
            导入的文档块数量
        """
        # 1. 加载文档
        docs = self.load_documents(file_paths)
        if not docs:
            print("[RAG] 没有可导入的文档。")
            return 0

        # 2. 切分
        chunks = self.split_documents(docs)

        # 3. 初始化/重建 Milvus 集合
        init_collection(
            self.milvus_client,
            collection_name=self.collection_name,
            dim=EMBEDDING_DIM,
            drop_if_exists=force_rebuild,
        )

        # 4. 向量化并存入 Milvus
        texts = [chunk.page_content for chunk in chunks]
        print(f"[RAG] 正在生成 {len(texts)} 条向量 ...")
        vectors = self.embeddings.embed_documents(texts)

        data = [
            {
                "id": i,
                "vector": vectors[i],
                "text": texts[i],
                "source": chunks[i].metadata.get("source_file", "unknown"),
            }
            for i in range(len(texts))
        ]
        self.milvus_client.insert(
            collection_name=self.collection_name,
            data=data,
        )
        print(f"[RAG] 已写入 {len(data)} 条向量到 Milvus 集合 '{self.collection_name}'")

        # 5. 同时构建 BM25 索引
        self._bm25_docs = chunks
        self._bm25_retriever = BM25Retriever.from_documents(chunks)
        self._bm25_retriever.k = RETRIEVAL_TOP_K
        print(f"[RAG] BM25 索引已构建 ({len(chunks)} 条文档)")

        return len(chunks)

    def load_existing_for_bm25(self, file_paths: list[str]) -> None:
        """
        从文件加载文档到 BM25 索引 (不重新向量化)。
        用于服务启动时快速恢复 BM25 检索能力。

        Args:
            file_paths: 政策文档文件路径列表
        """
        docs = self.load_documents(file_paths)
        if docs:
            chunks = self.split_documents(docs)
            self._bm25_docs = chunks
            self._bm25_retriever = BM25Retriever.from_documents(chunks)
            self._bm25_retriever.k = RETRIEVAL_TOP_K
            print(f"[RAG] BM25 索引已从文件恢复 ({len(chunks)} 条文档)")

    # ========================================
    # 检索
    # ========================================

    def vector_search(self, query: str, top_k: int = RETRIEVAL_TOP_K) -> list[Document]:
        """
        向量语义检索。

        Args:
            query: 查询文本
            top_k: 返回数量

        Returns:
            检索到的 Document 列表
        """
        query_vec = self.embeddings.embed_query(query)
        try:
            results = self.milvus_client.search(
                collection_name=self.collection_name,
                data=[query_vec],
                limit=top_k,
                output_fields=["text", "source"],
            )
        except Exception as e:
            # 集合可能处于释放状态，尝试加载后重试
            if "released" in str(e).lower() or "load" in str(e).lower():
                self.milvus_client.load_collection(self.collection_name)
                results = self.milvus_client.search(
                    collection_name=self.collection_name,
                    data=[query_vec],
                    limit=top_k,
                    output_fields=["text", "source"],
                )
            else:
                raise

        docs = []
        if results and results[0]:
            for hit in results[0]:
                docs.append(Document(
                    page_content=hit["entity"]["text"],
                    metadata={"source": hit["entity"].get("source", "unknown"), "score": hit["distance"]},
                ))
        return docs

    def bm25_search(self, query: str, top_k: int = RETRIEVAL_TOP_K) -> list[Document]:
        """
        BM25 关键词检索。

        Args:
            query: 查询文本
            top_k: 返回数量

        Returns:
            检索到的 Document 列表
        """
        if self._bm25_retriever is None:
            return []
        self._bm25_retriever.k = top_k
        return self._bm25_retriever.invoke(query)

    def hybrid_search(self, query: str, top_k: int = RETRIEVAL_TOP_K) -> list[Document]:
        """
        混合检索: 向量检索 + BM25 检索, 使用 RRF 融合。

        Args:
            query: 查询文本
            top_k: 每路检索的召回数

        Returns:
            融合去重后的 Document 列表
        """
        # 1. 向量检索
        vec_docs = self.vector_search(query, top_k=top_k)

        # 2. BM25 检索
        bm25_docs = self.bm25_search(query, top_k=top_k)

        # 3. RRF 融合 (Reciprocal Rank Fusion)
        rrf_k = 60  # RRF 常数, 缓解高排名文档得分过高
        rrf_scores: dict[str, float] = {}
        doc_map: dict[str, Document] = {}

        for rank, doc in enumerate(vec_docs):
            key = doc.page_content[:100]  # 用前100字作为去重键
            rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (rrf_k + rank + 1)
            if key not in doc_map:
                doc_map[key] = doc

        for rank, doc in enumerate(bm25_docs):
            key = doc.page_content[:100]
            rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (rrf_k + rank + 1)
            if key not in doc_map:
                doc_map[key] = doc

        # 按 RRF 分数排序
        sorted_keys = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k], reverse=True)
        result = []
        for key in sorted_keys[:top_k * 2]:  # 保留 2×top_k 供 Rerank
            doc = doc_map[key]
            doc.metadata["rrf_score"] = rrf_scores[key]
            result.append(doc)

        return result

    def search(self, query: str, top_k: int = RERANK_TOP_K) -> list[Document]:
        """
        完整检索管线: 混合检索 → Rerank 精筛。

        Args:
            query: 查询文本
            top_k: 最终返回数量

        Returns:
            精筛排序后的 Document 列表
        """
        # 1. 混合检索 (召回更多候选)
        candidates = self.hybrid_search(query, top_k=RETRIEVAL_TOP_K)

        if not candidates:
            return []

        # 2. Rerank 精筛
        reranker = self.reranker
        if reranker is False or reranker is None:
            # Reranker 不可用, 直接返回混合检索结果
            print("[RAG] Reranker 不可用, 返回混合检索结果。")
            return candidates[:top_k]

        # 使用 CrossEncoder 对候选结果打分重排
        pairs = [[query, doc.page_content] for doc in candidates]
        scores = reranker.predict(pairs)

        # 按分数排序
        scored_docs = list(zip(candidates, scores))
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        result = []
        for doc, score in scored_docs[:top_k]:
            doc.metadata["rerank_score"] = float(score)
            result.append(doc)

        return result

    def search_as_context(self, query: str, top_k: int = RERANK_TOP_K) -> str:
        """
        检索并格式化为上下文文本, 供 LLM Prompt 使用。

        Args:
            query: 查询文本
            top_k: 返回数量

        Returns:
            格式化的上下文字符串
        """
        docs = self.search(query, top_k=top_k)
        if not docs:
            return "未检索到相关政策信息。"

        context_parts = []
        for i, doc in enumerate(docs, 1):
            source = doc.metadata.get("source", "未知来源")
            score = doc.metadata.get("rerank_score", doc.metadata.get("rrf_score", 0))
            context_parts.append(
                f"[{i}] (来源: {source}, 相关度: {score:.4f})\n{doc.page_content}"
            )
        return "\n\n---\n\n".join(context_parts)


# ========================================
# 模块级便捷接口 (供 Agent 节点直接调用)
# ========================================

_rag_instance: Optional[CarbonPolicyRAG] = None


def get_rag_engine() -> CarbonPolicyRAG:
    """获取全局 RAG 引擎单例"""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = CarbonPolicyRAG()
        # 尝试从已有文档加载 BM25 索引
        doc_files = []
        for ext in ("*.txt", "*.md", "*.pdf"):
            doc_files.extend(str(f) for f in RAW_DOCUMENTS_DIR.glob(ext))
        if doc_files:
            _rag_instance.load_existing_for_bm25(doc_files)
    return _rag_instance


def rag_search(query: str, top_k: int = RERANK_TOP_K) -> str:
    """
    便捷检索接口: 输入查询, 返回格式化上下文文本。
    供 LangGraph Agent 节点直接调用。

    Args:
        query: 查询文本 (如 "CBAM 铝制品碳关税政策")
        top_k: 返回结果数

    Returns:
        格式化的政策上下文文本
    """
    engine = get_rag_engine()
    return engine.search_as_context(query, top_k=top_k)


# ========================================
# 主程序: 快速验证
# ========================================

if __name__ == "__main__":
    print("=" * 60)
    print("碳合规政策 RAG 引擎 - 初始化与测试")
    print("=" * 60)

    engine = CarbonPolicyRAG()

    # 1. 导入政策文档
    doc_dir = RAW_DOCUMENTS_DIR
    doc_files = []
    for ext in ("*.txt", "*.md", "*.pdf"):
        doc_files.extend(str(f) for f in doc_dir.glob(ext))

    if not doc_files:
        print("[RAG] 未找到政策文档, 请将文档放入 data/raw_documents/ 目录。")
    else:
        print(f"\n找到 {len(doc_files)} 个文档:")
        for f in doc_files:
            print(f"  - {Path(f).name}")

        # 导入文档 (强制重建)
        count = engine.ingest_documents(doc_files, force_rebuild=True)
        print(f"\n导入完成: {count} 个文档块")

        # 2. 测试检索
        test_queries = [
            "CBAM 铝制品的碳关税政策是什么?",
            "Scope 3 物流碳排放如何计算?",
            "美国 CCA 和欧盟 CBAM 有什么区别?",
        ]

        for q in test_queries:
            print(f"\n{'─' * 50}")
            print(f"查询: {q}")
            print("─" * 50)
            context = engine.search_as_context(q, top_k=3)
            print(context[:500] + "..." if len(context) > 500 else context)

    print(f"\n{'=' * 60}")
    print("RAG 引擎测试完成")
    print("=" * 60)
