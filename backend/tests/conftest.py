"""
共享的 pytest fixtures。
"""

import pytest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.calculator import CarbonCalculator, TransportLeg, MaterialInput


@pytest.fixture
def calculator():
    """提供一个全新的 CarbonCalculator 实例。"""
    return CarbonCalculator()


@pytest.fixture
def sample_transport_leg():
    """一个标准的运输段测试数据。"""
    return TransportLeg(
        transport_type="sea_container",
        weight_tons=60.0,
        distance_km=18500,
        description="深圳 → 汉堡",
    )


@pytest.fixture
def sample_material_input():
    """一个标准的材料输入测试数据。"""
    return MaterialInput(
        material_type="aluminum_primary",
        weight_tons=60.0,
    )


@pytest.fixture
def auth_token():
    """生成一个有效的 JWT 用于测试受保护端点。"""
    from src.infrastructure.auth import create_access_token
    return create_access_token({"sub": "testuser"})


@pytest.fixture
def auth_headers(auth_token):
    """请求头，包含 Bearer 认证令牌。"""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def api_client():
    """
    从 FastAPI 应用创建一个 TestClient。
    覆盖 settings 中的 JWT_SECRET_KEY，使用已知测试值。
    """
    from config import settings
    original_secret = settings.JWT_SECRET_KEY
    settings.JWT_SECRET_KEY = "test-secret-key-for-pytest"

    from src.api.app import app
    from fastapi.testclient import TestClient

    client = TestClient(app)

    yield client

    settings.JWT_SECRET_KEY = original_secret
