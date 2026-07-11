"""
Infrastructure layer - JWT authentication
Token creation, verification and FastAPI dependency injection.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from fastapi import HTTPException, status, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config.settings import (
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
    JWT_EXPIRE_MINUTES,
    API_USERS,
)

# ========================================
# JWT Core
# ========================================

security_scheme = HTTPBearer(auto_error=False)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Generate a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=JWT_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> dict:
    """Verify JWT token and return payload. Raises 401 if invalid."""
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired.",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )


def authenticate_user(username: str, password: str) -> bool:
    """Verify credentials against configured users."""
    expected = API_USERS.get(username)
    return expected is not None and expected == password


# ========================================
# FastAPI Dependency
# ========================================

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> dict:
    """Extract and verify JWT Bearer token from Authorization header."""
    if credentials is None:
        # Try manual header extraction as fallback
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = verify_token(token)
            return {"username": payload.get("sub", "unknown"), "token_payload": payload}

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide Bearer Token in Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = verify_token(token)
    return {"username": payload.get("sub", "unknown"), "token_payload": payload}
