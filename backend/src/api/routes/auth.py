"""
认证路由 - 登录获取 JWT Token
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import APIRouter, HTTPException

from src.api.schemas import (
    TokenRequest,
    TokenResponse,
)
from src.infrastructure.auth import (
    authenticate_user,
    create_access_token,
)
from config.settings import JWT_EXPIRE_MINUTES

router = APIRouter(prefix="/api/v1/auth", tags=["认证"])


@router.post("/token", response_model=TokenResponse, summary="登录获取 Token")
async def login(request: TokenRequest):
    """
    使用用户名/密码登录，返回 JWT access token。
    
    """
    if not authenticate_user(request.username, request.password):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password.",
        )

    token = create_access_token({"sub": request.username})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=JWT_EXPIRE_MINUTES,
    )
