"""
数据访问层 - Milvus 向量数据库、碳因子 JSON、HS Code 查询
"""

from src.data.database import (
    get_milvus_client,
    init_collection,
    reset_milvus_db,
    load_carbon_db,
    load_hs_code_db,
    lookup_hs_code,
)
