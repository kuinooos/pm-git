"""
RAG 路由 - 政策文档上传、知识库检索
"""

import sys
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends

from src.api.schemas import (
    RagUploadResponse, RagSearchRequest, RagSearchResponse,
)
from src.domain.rag import get_rag_engine
from src.infrastructure.auth import get_current_user
from config.settings import RAW_DOCUMENTS_DIR

router = APIRouter(prefix="/api/v1/rag", tags=["RAG 知识库"])


@router.post("/upload", response_model=RagUploadResponse)
async def upload_policy_document(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """
    上传政策 PDF/TXT 文档到知识库。
    Requires auth: Bearer Token
    """
    try:
        file_path = RAW_DOCUMENTS_DIR / file.filename
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        engine = get_rag_engine()
        count = engine.ingest_documents([str(file_path)], force_rebuild=False)

        return RagUploadResponse(
            status="success",
            document_count=count,
            message=f"文档 '{file.filename}' 已成功导入知识库 ({count} 个文档块)。",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文档导入失败: {str(e)}")


@router.post("/search", response_model=RagSearchResponse)
async def search_policy(request: RagSearchRequest):
    """
    检索碳合规政策知识库。
    无需认证。
    """
    try:
        engine = get_rag_engine()
        context = engine.search_as_context(request.query, top_k=request.top_k)

        doc_count = context.count("---") + 1 if context != "未检索到相关政策信息。" else 0

        return RagSearchResponse(
            query=request.query,
            context=context,
            document_count=doc_count,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检索失败: {str(e)}")
