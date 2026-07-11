"""
全局配置管理模块
统一管理环境变量、模型参数、向量数据库配置等。
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

# ========================================
# 路径配置
# ========================================
# 项目根目录 (backend/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 数据目录
DATA_DIR = PROJECT_ROOT / "data"
RAW_DOCUMENTS_DIR = DATA_DIR / "raw_documents"

# Milvus Lite 数据库文件路径
MILVUS_DB_PATH = DATA_DIR / "milvus_lite.db"

# LangGraph 状态持久化 SQLite 路径
CHECKPOINT_DB_PATH = DATA_DIR / "checkpoints.db"

# 报告输出目录
REPORTS_DIR = DATA_DIR / "reports"

# 确保必要目录存在
for d in [DATA_DIR, RAW_DOCUMENTS_DIR, REPORTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ========================================
# 环境变量加载
# ========================================
load_dotenv(PROJECT_ROOT / ".env")

# ========================================
# LLM 模型配置
# ========================================
LLM_API_KEY = os.environ.get(
    "LONGCAT_API_KEY",
    "ak_2pg7XK6R507u2do5hA50O5QR6170L"
)
LLM_BASE_URL = os.environ.get(
    "LLM_BASE_URL",
    "https://api.longcat.chat/openai/v1"
)
LLM_MODEL = os.environ.get("LLM_MODEL", "LongCat-2.0")
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0"))

# ========================================
# Embedding 模型配置
# ========================================
# BGE-M3 支持中英双语，适合政策文档检索
# 如模型下载困难，可替换为 "BAAI/bge-small-zh-v1.5" (轻量版, 512维)
EMBEDDING_MODEL = os.environ.get(
    "EMBEDDING_MODEL",
    "BAAI/bge-small-zh-v1.5"
)
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "512"))

# Reranker 模型
RERANKER_MODEL = os.environ.get(
    "RERANKER_MODEL",
    "BAAI/bge-reranker-base"
)

# ========================================
# Milvus 向量数据库配置
# ========================================
MILVUS_URI = str(MILVUS_DB_PATH)
COLLECTION_NAME = "carbon_policy"
MILVUS_METRIC_TYPE = "COSINE"

# ========================================
# RAG 检索配置
# ========================================
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100
RETRIEVAL_TOP_K = 10  # 混合检索召回数
RERANK_TOP_K = 5      # Rerank 后保留数

# ========================================
# 碳因子数据库路径
# ========================================
CARBON_DB_PATH = DATA_DIR / "carbon_db.json"
HS_CODE_DB_PATH = DATA_DIR / "hs_code_mapping.json"

# ========================================
# Redis 缓存配置
# ========================================
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL_RAG = int(os.environ.get("CACHE_TTL_RAG", "3600"))
CACHE_TTL_EMISSION = int(os.environ.get("CACHE_TTL_EMISSION", "1800"))
REDIS_ENABLED = os.environ.get("REDIS_ENABLED", "true").lower() == "true"

# 速率限制
RATE_LIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "false").lower() == "true"
RATE_LIMIT_MAX_REQUESTS = int(os.environ.get("RATE_LIMIT_MAX_REQUESTS", "30"))
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))

# ========================================
# JWT 认证配置
# ========================================
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-secret-change-me")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "1440"))

# API 用户配置 (JSON 格式)
try:
    API_USERS = json.loads(os.environ.get("API_USERS", '{"admin": "admin123", "auditor": "audit456"}'))
except json.JSONDecodeError:
    API_USERS = {"admin": "admin123", "auditor": "audit456"}

# ========================================
# Celery 异步任务配置
# ========================================
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
