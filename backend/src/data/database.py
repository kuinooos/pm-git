"""
数据库初始化与连接管理模块
负责 Milvus Lite 向量数据库的连接、集合创建和管理。
"""

import os
import json
import shutil
import time
from pathlib import Path
from typing import Optional

from pymilvus import MilvusClient, DataType

# 导入配置
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from config.settings import (
    MILVUS_URI,
    COLLECTION_NAME,
    MILVUS_METRIC_TYPE,
    EMBEDDING_DIM,
    CARBON_DB_PATH,
    HS_CODE_DB_PATH,
)


def get_milvus_client(uri: Optional[str] = None) -> MilvusClient:
    """
    获取 Milvus Lite 客户端连接。
    使用本地 SQLite 文件作为 Milvus Lite 后端, 无需部署独立服务。

    Args:
        uri: Milvus 数据库文件路径, 默认使用配置中的路径

    Returns:
        MilvusClient 实例
    """
    uri = uri or MILVUS_URI
    client = MilvusClient(uri=uri)
    return client


def init_collection(
    client: MilvusClient,
    collection_name: str = COLLECTION_NAME,
    dim: int = EMBEDDING_DIM,
    drop_if_exists: bool = False,
) -> None:
    """
    初始化向量集合。
    如果集合已存在且 drop_if_exists=True, 则先删除再重建。

    Args:
        client: MilvusClient 实例
        collection_name: 集合名称
        dim: 向量维度
        drop_if_exists: 是否在已存在时删除重建
    """
    if client.has_collection(collection_name):
        if drop_if_exists:
            client.drop_collection(collection_name)
        else:
            return  # 集合已存在, 无需重建

    client.create_collection(
        collection_name=collection_name,
        dimension=dim,
        metric_type=MILVUS_METRIC_TYPE,
    )


def reset_milvus_db(uri: Optional[str] = None) -> None:
    """
    彻底重置 Milvus Lite 数据库文件。
    删除数据库文件并重建目录, 用于开发调试。

    Args:
        uri: Milvus 数据库文件路径
    """
    uri = uri or MILVUS_URI
    db_path = Path(uri)
    if db_path.exists():
        shutil.rmtree(db_path, ignore_errors=True)
        time.sleep(0.1)


def load_carbon_db() -> dict:
    """
    加载碳排放因子数据库。

    Returns:
        包含所有碳排放因子的字典
    """
    with open(CARBON_DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_hs_code_db() -> dict:
    """
    加载 HS Code 对照表。

    Returns:
        包含 HS Code 映射的字典
    """
    with open(HS_CODE_DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def lookup_hs_code(hs_code: str) -> Optional[dict]:
    """
    根据 HS Code 查询碳关税管控信息。

    Args:
        hs_code: 海关编码 (如 "7601", "7208")

    Returns:
        匹配的映射字典, 如未找到返回 None
    """
    db = load_hs_code_db()
    for item in db.get("mappings", []):
        if item["hs_code"] == hs_code:
            return item
        # 支持前缀匹配 (如 7601xx 匹配 7601)
        if hs_code.startswith(item["hs_code"]):
            return item
    return None


if __name__ == "__main__":
    # 快速验证数据库连接
    print("=== 数据库模块验证 ===")

    # 1. Milvus 连接测试
    client = get_milvus_client()
    print(f"✅ Milvus Lite 连接成功: {MILVUS_URI}")

    # 2. 碳因子数据库加载
    carbon_db = load_carbon_db()
    print(f"✅ 碳因子数据库加载成功: {len(carbon_db)} 个类别")
    print(f"   - 运输因子: {len(carbon_db['transport_factors'])} 项")
    print(f"   - 能源因子: {len(carbon_db['energy_factors'])} 项")
    print(f"   - 材料因子: {len(carbon_db['material_factors'])} 项")
    print(f"   - CBAM基准: {len(carbon_db['cbam_benchmarks'])} 项")

    # 3. HS Code 查询测试
    result = lookup_hs_code("7601")
    print(f"✅ HS Code 7601 查询: {result['hs_description']} → CBAM: {result['cbam_category']}")

    # 4. 集合初始化
    init_collection(client, drop_if_exists=True)
    print(f"✅ Milvus 集合 '{COLLECTION_NAME}' 初始化完成 (dim={EMBEDDING_DIM})")

    print("\n=== 数据库模块验证通过 ===")
