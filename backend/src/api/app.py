"""
FastAPI 应用工厂
创建应用实例、注册中间件和路由。
"""

import sys
from pathlib import Path

# 添加 backend/ 到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.schemas import HealthResponse
from config.settings import CELERY_BROKER_URL


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用"""
    app = FastAPI(
        title="全球碳关税合规审计多智能体系统",
        description="""
## Carbon Compliance Audit Multi-Agent System API

基于 LangGraph + LangChain RAG + FastAPI 构建的碳关税 (CBAM/CCA) 合规审计系统。

### 核心功能
- **多源数据接入**: 支持 BOM/TMS 数据导入
- **智能 HS Code 判定**: RAG 检索 + 政策匹配
- **分阶段多体协同审计**: 5 个 Agent 节点协同工作
- **人工审查确认**: Human-in-the-Loop 暂停/恢复机制
- **合规报告生成**: Markdown/PDF 自动化渲染

### 工作流
```
START → 信息萃取 → 政策判定 → 排放计算 → 合规风控 → 人工审查 → 报告生成 → END
```
        """,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    from src.api.routes.audit import router as audit_router
    from src.api.routes.rag import router as rag_router
    from src.api.routes.auth import router as auth_router

    app.include_router(auth_router)
    app.include_router(audit_router)
    app.include_router(rag_router)

    # 健康检查
    @app.get("/", response_model=HealthResponse)
    async def root():
        return HealthResponse()

    @app.get("/api/v1/health", response_model=HealthResponse)
    async def health():
        return HealthResponse()

    @app.on_event("startup")
    async def startup_event():
        print("=" * 60)
        print("  Carbon Compliance Audit Agent - API starting")
        print("=" * 60)
        print(f"  Docs: http://localhost:8008/docs")
        print(f"  ReDoc: http://localhost:8008/redoc")

        try:
            from src.infrastructure.cache import is_redis_available
            redis_status = "[UP] Redis" if is_redis_available() else "[DOWN] Redis"
            print(f"  {redis_status}")
        except Exception as e:
            print(f"  [DOWN] Redis (error): {e}")
        print(f"  Celery broker: {CELERY_BROKER_URL}")
        print("=" * 60)

    return app


# 模块级 app 实例（uvicorn 入口）
app = create_app()
