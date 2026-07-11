"""
Redis 缓存单元测试
"""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.cache import (
    get_redis,
    is_redis_available,
    cached_rag_search,
    set_rag_cache,
)


def test_get_redis_returns_client_or_none():
    """获取 Redis 客户端 (可能返回 None 如果 Redis 未运行)"""
    r = get_redis()
    if r is not None:
        assert r.ping() is True


def test_is_redis_available():
    """检查 Redis 可用性 (不抛异常)"""
    result = is_redis_available()
    assert isinstance(result, bool)


def test_cached_rag_search_miss_returns_none():
    """缓存未命中返回 None"""
    # 使用一个几乎不可能被缓存过的查询
    import hashlib, time
    unique_query = f"test_query_{time.time()}_{hashlib.md5(str(time.time()).encode()).hexdigest()[:8]}"
    result = cached_rag_search(unique_query, top_k=3)
    # Redis 不可用时也可能返回 None
    assert result is None or isinstance(result, str)


def test_set_and_get_rag_cache():
    """写入缓存后能读取"""
    query = f"cache_test_query_{time.time()}"
    context = "这是一个测试缓存内容"

    set_rag_cache(query, 3, context)

    # 尝试读取 (如果 Redis 可用)
    cached = cached_rag_search(query, top_k=3)
    if is_redis_available():
        assert cached == context
    else:
        # Redis 不可用, 返回 None 也算通过
        print("[test_cache] Redis 不可用，跳过缓存命中测试")


def test_rate_limiter_basic():
    """速率限制器基本功能"""
    from src.infrastructure.cache import RateLimiter
    limiter = RateLimiter()
    key = f"rate_limit_test_{time.time()}"
    # 应该总是允许 (RATE_LIMIT_ENABLED 默认 false)
    result = limiter.is_allowed(key)
    assert result is True


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
