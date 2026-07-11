"""
全球碳关税合规审计多智能体系统 - 主入口

启动方式:
    uvicorn main:app --host 0.0.0.0 --port 8008 --reload
    或
    python main.py
"""

import sys
from pathlib import Path

# 确保 backend/ 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve()))

from src.api.app import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8008,
        reload=True,
    )
