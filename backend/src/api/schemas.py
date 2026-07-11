"""
FastAPI 请求/响应模型定义
使用 Pydantic v2 定义所有 API 接口的数据模型。
"""

from pydantic import BaseModel, Field
from typing import Any, Optional


# ========================================
# 审计任务相关模型
# ========================================

class AuditStartRequest(BaseModel):
    """发起审计任务请求"""
    bom_data: dict = Field(..., description="物料清单 (BOM) 数据")
    tms_data: Optional[dict] = Field(None, description="运输管理 (TMS) 数据")
    target_country: str = Field("EU", description="目标出口国 (EU/US)")
    hs_code_hint: Optional[str] = Field(None, description="HS Code 提示 (可选)")
    async_mode: bool = Field(False, description="是否使用 Celery 异步模式 (默认同步)")

    class Config:
        json_schema_extra = {
            "example": {
                "bom_data": {
                    "product_name": "铝合金型材",
                    "hs_code": "7604",
                    "weight_kg": 60000,
                    "material": "铝",
                    "origin_port": "深圳",
                    "destination_port": "汉堡",
                    "transport_mode": "sea",
                },
                "target_country": "EU",
                "async_mode": False,
            }
        }


class AuditStartResponse(BaseModel):
    """发起审计任务响应"""
    thread_id: str = Field("", description="会话线程 ID")
    task_id: Optional[str] = Field(None, description="Celery 异步任务 ID (仅 async_mode=True)")
    status: str = Field(..., description="任务状态: pending_review | completed | error | pending")
    current_node: str = Field("", description="当前工作流节点")
    review_data: Optional[dict] = Field(None, description="待审查的数据 (当 status=pending_review 时)")
    message: str = Field("", description="状态消息")


class AuditStatusResponse(BaseModel):
    """审计任务状态查询响应"""
    thread_id: str
    current_node: Optional[str]
    next_node: Optional[list] = None
    pending_review: bool
    state: dict = Field(default_factory=dict, description="当前状态快照")


class AuditApproveRequest(BaseModel):
    """人工审批请求"""
    thread_id: str = Field(..., description="会话线程 ID")
    approved: bool = Field(..., description="是否通过审查")
    feedback: Optional[str] = Field("", description="审查备注/修改说明")
    modified_emissions: Optional[float] = Field(None, description="人工修正的排放值 (可选)")

    class Config:
        json_schema_extra = {
            "example": {
                "thread_id": "xxx-xxx-xxx",
                "approved": True,
                "feedback": "审查通过, 数据准确无误。",
            }
        }


class AuditApproveResponse(BaseModel):
    """人工审批响应"""
    thread_id: str
    status: str = Field(..., description="任务状态: completed | rejected | error")
    audit_report_md: Optional[str] = Field(None, description="审计报告 Markdown (当 status=completed 时)")
    message: str = Field("", description="状态消息")


# ========================================
# RAG 知识库管理相关模型
# ========================================

class RagUploadResponse(BaseModel):
    """RAG 文档上传响应"""
    status: str
    document_count: int = Field(0, description="导入的文档块数量")
    message: str = ""


class RagSearchRequest(BaseModel):
    """RAG 检索请求"""
    query: str = Field(..., description="检索查询")
    top_k: int = Field(5, description="返回结果数")


class RagSearchResponse(BaseModel):
    """RAG 检索响应"""
    query: str
    context: str = Field("", description="检索到的上下文文本")
    document_count: int = 0


# ========================================
# 通用响应模型
# ========================================

class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = "ok"
    service: str = "Carbon Compliance Audit Agent"
    version: str = "1.0.0"


# ========================================
# 认证相关模型
# ========================================

class TokenRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")

    class Config:
        json_schema_extra = {
            "example": {"username": "admin", "password": "admin123"}
        }


class TokenResponse(BaseModel):
    """登录响应"""
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field("bearer", description="Token 类型")
    expires_in: int = Field(1440, description="过期时间 (分钟)")
