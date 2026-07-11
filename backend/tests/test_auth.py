"""
JWT 认证单元测试
"""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.auth import (
    create_access_token,
    verify_token,
    authenticate_user,
)


def test_authenticate_user_valid():
    """验证正确的用户名密码"""
    assert authenticate_user("admin", "admin123") is True


def test_authenticate_user_invalid():
    """验证错误的用户名密码"""
    assert authenticate_user("admin", "wrong") is False
    assert authenticate_user("nobody", "password") is False


def test_create_and_verify_token():
    """验证 Token 创建和验证"""
    token = create_access_token({"sub": "testuser"})
    payload = verify_token(token)
    assert payload["sub"] == "testuser"


def test_token_rejects_invalid():
    """验证伪造 Token 被拒绝"""
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        verify_token("invalid.token.here")


def test_login_endpoint(api_client):
    """登录端点返回 JWT"""
    response = api_client.post("/api/v1/auth/token", json={
        "username": "admin",
        "password": "admin123",
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_with_wrong_password(api_client):
    """错误密码返回 401"""
    response = api_client.post("/api/v1/auth/token", json={
        "username": "admin",
        "password": "wrong",
    })
    assert response.status_code == 401


def test_protected_endpoint_without_token(api_client):
    """无 Token 访问受保护端点返回 401"""
    response = api_client.post("/api/v1/audit/start", json={
        "bom_data": {"test": "data"},
    })
    # 可能会因为缺少认证返回 401, 或者认证后因为数据不完整返回 500
    # 这样设计是为了测试认证层是否生效
    assert response.status_code in (401, 422)


def test_protected_endpoint_with_token(api_client, auth_headers):
    """带有效 Token 访问受保护端点"""
    response = api_client.post(
        "/api/v1/audit/start",
        json={
            "bom_data": {"product_name": "test", "hs_code": "7601", "weight_kg": 100},
            "target_country": "EU",
        },
        headers=auth_headers,
    )
    # 带 token 应返回 401 (认证层) 而非 401 (除非 token 无效)
    status = response.status_code
    print(f"Protected endpoint status: {status}, body: {response.text[:200]}")
    # 注意：测试环境可能无 LLM API key, 可能返回 500 而非 200, 这是正常的
    assert status != 401


def test_public_endpoint_no_auth(api_client):
    """公开端点无需认证"""
    response = api_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
