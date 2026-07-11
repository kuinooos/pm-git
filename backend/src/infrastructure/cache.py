"""
基础设施层 - Redis 缓存、速率限制
提供缓存装饰器和 Redis 连接管理，Redis 不可用时优雅降级。
"""

import hashlib
import json
import functools
from typing import Any, Callable, Optional

import redis

from config.settings import (
    REDIS_URL,
    REDIS_ENABLED,
    CACHE_TTL_RAG,
    CACHE_TTL_EMISSION,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_MAX_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
)

# ========================================
# Redis 连接 (惰性 + 优雅降级)
# ========================================

_redis_client: Optional[redis.Redis] = None
_redis_checked: bool = False
_redis_available: bool = False


def get_redis() -> Optional[redis.Redis]:
    """
    获取 Redis 客户端连接。
    Redis 不可用时返回 None，业务代码应据此优雅降级。

    Returns:
        Redis 客户端实例，或 None (不可用时)
    """
    global _redis_client, _redis_checked, _redis_available

    if _redis_checked:
        return _redis_client if _redis_available else None

    if not REDIS_ENABLED:
        _redis_checked = True
        _redis_available = False
        return None

    try:
        _redis_client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=3, decode_responses=True)
        _redis_client.ping()
        _redis_available = True
        _redis_checked = True
        print(f"[Redis] 连接成功: {REDIS_URL}")
    except Exception as e:
        print(f"[Redis] 连接失败 ({e}), 缓存功能将降级禁用。")
        _redis_checked = True
        _redis_available = False
        _redis_client = None

    return _redis_client if _redis_available else None


def is_redis_available() -> bool:
    """检查 Redis 是否可用"""
    get_redis()
    return _redis_available


# ========================================
# 缓存装饰器
# ========================================


def cached(ttl: int = 3600, prefix: str = "cache"):
    """
    通用缓存装饰器。
    基于函数名 + 参数哈希生成缓存键，支持 Redis 不可用时优雅降级。

    Usage:
        @cached(ttl=3600, prefix="rag")
        def search(query, top_k):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            r = get_redis()
            if r is None:
                return func(*args, **kwargs)

            # 生成缓存键
            key_parts = [prefix, func.__name__]
            if args:
                key_parts.append(hashlib.md5(
                    json.dumps(args, sort_keys=True, default=str).encode()
                ).hexdigest()[:16])
            if kwargs:
                key_parts.append(hashlib.md5(
                    json.dumps(kwargs, sort_keys=True, default=str).encode()
                ).hexdigest()[:16])
            cache_key = ":".join(key_parts)

            # 尝试读取缓存
            try:
                cached_val = r.get(cache_key)
                if cached_val is not None:
                    return json.loads(cached_val)
            except Exception:
                pass

            # 执行函数并缓存
            result = func(*args, **kwargs)
            try:
                r.setex(cache_key, ttl, json.dumps(result, default=str))
            except Exception:
                pass

            return result

        return wrapper

    return decorator


# ========================================
# RAG 缓存专用函数
# ========================================


def cached_rag_search(query: str, top_k: int = 5) -> Optional[str]:
    """
    尝试从缓存获取 RAG 检索结果。
    缓存未命中返回 None，调用方应正常执行检索。

    Args:
        query: 检索查询
        top_k: 返回结果数

    Returns:
        缓存的上下文文本，或 None
    """
    r = get_redis()
    if r is None:
        return None

    try:
        cache_key = f"rag:search:{hashlib.md5(query.encode()).hexdigest()[:16]}:{top_k}"
        cached_val = r.get(cache_key)
        if cached_val:
            return str(cached_val)
    except Exception:
        pass

    return None


def set_rag_cache(query: str, top_k: int, context: str) -> None:
    """
    将 RAG 检索结果写入缓存。

    Args:
        query: 检索查询
        top_k: 返回结果数
        context: 检索到的上下文文本
    """
    r = get_redis()
    if r is None:
        return

    try:
        cache_key = f"rag:search:{hashlib.md5(query.encode()).hexdigest()[:16]}:{top_k}"
        r.setex(cache_key, CACHE_TTL_RAG, context[:10000])  # 限制缓存大小
    except Exception:
        pass


# ========================================
# 速率限制器
# ========================================


class RateLimiter:
    """
    基于 Redis 滑动窗口的速率限制器。

    Usage:
        limiter = RateLimiter()
        if not limiter.is_allowed("user_ip"):
            raise HTTPException(429, "请求过于频繁")
    """

    def __init__(self):
        self._redis = None

    @property
    def redis(self):
        if self._redis is None:
            self._redis = get_redis()
        return self._redis

    def is_allowed(self, key: str) -> bool:
        """
        检查指定 key 是否在限制窗口内。

        Args:
            key: 标识符 (如 IP 地址或用户 ID)

        Returns:
            True=允许, False=拒绝
        """
        if not RATE_LIMIT_ENABLED or self.redis is None:
            return True

        try:
            current = int(self.redis.get(key) or 0)
            if current >= RATE_LIMIT_MAX_REQUESTS:
                return False
            pipe = self.redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, RATE_LIMIT_WINDOW_SECONDS)
            pipe.execute()
            return True
        except Exception:
            return True  # Redis 异常时放行
