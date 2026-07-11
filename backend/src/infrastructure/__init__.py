"""
基础设施层 - 缓存、认证、异步任务等横切关注点。
"""

from src.infrastructure.cache import (
    get_redis,
    is_redis_available,
    cached,
    cached_rag_search,
    set_rag_cache,
    RateLimiter,
)

from src.infrastructure.auth import (
    create_access_token,
    verify_token,
    authenticate_user,
    get_current_user,
    security_scheme,
)

from src.infrastructure.celery_app import celery_app
from src.infrastructure.celery_tasks import (
    run_audit_async,
    resume_audit_async,
    get_task_result,
)
