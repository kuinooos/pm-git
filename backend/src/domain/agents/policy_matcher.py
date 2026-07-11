"""
政策判定 Agent (Policy Matcher Node)
调用 RAG 引擎检索 CBAM/CCA 政策, 并通过 HS Code 对照表判定管控品类。
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.database import lookup_hs_code
from src.domain.rag import get_rag_engine
from src.infrastructure.cache import cached_rag_search, set_rag_cache


def policy_matcher_node(state: dict) -> dict:
    """
    政策判定节点: RAG 检索政策 + HS Code 管控品类判定。

    Args:
        state: 工作流状态, 包含 hs_code, product_name, target_country, material_type

    Returns:
        更新后的状态字段
    """
    print("[Node: rag_policy] 开始政策判定...")

    hs_code = state.get("hs_code", "")
    product_name = state.get("product_name", "")
    target_country = state.get("target_country", "EU")
    material_type = state.get("material_type", "unknown")

    # 1. HS Code 管控品类查询
    hs_info = lookup_hs_code(hs_code) if hs_code else None

    cbam_category = None
    if hs_info:
        if target_country == "EU" and hs_info.get("cbam_subject"):
            cbam_category = hs_info.get("cbam_category")
        elif target_country == "US" and hs_info.get("cca_subject"):
            cbam_category = hs_info.get("cca_category")

    # 如果 HS Code 未匹配, 通过材料类型推断
    if not cbam_category and material_type != "unknown":
        material_to_cbam = {
            "aluminum_primary": "aluminum",
            "aluminum_secondary": "aluminum",
            "steel_bf_bof": "steel",
            "steel_eaf": "steel",
            "cement_clinker": "cement",
            "cement_portland": "cement",
            "fertilizer_ammonia": "fertilizer",
            "hydrogen_grey": "hydrogen",
            "hydrogen_green": "hydrogen",
        }
        cbam_category = material_to_cbam.get(material_type)

    print(f"[Node: rag_policy] HS Code: {hs_code}, CBAM品类: {cbam_category}")

    # 2. RAG 检索相关政策 (优先从缓存获取)
    policy_context = ""
    try:
        engine = get_rag_engine()
        # 构建检索查询
        query_parts = []
        if target_country == "EU":
            query_parts.append("CBAM")
        else:
            query_parts.append("CCA")
        if cbam_category:
            category_cn = {
                "aluminum": "铝制品", "steel": "钢铁", "cement": "水泥",
                "fertilizer": "化肥", "hydrogen": "氢气", "electricity": "电力",
            }
            query_parts.append(category_cn.get(cbam_category, cbam_category))
        query_parts.append("碳关税")
        query_parts.append("排放基准")
        query = " ".join(query_parts)

        # 先查缓存
        policy_context = cached_rag_search(query, top_k=5) or ""
        if policy_context:
            print(f"[Node: rag_policy] RAG 缓存命中")
        else:
            policy_context = engine.search_as_context(query, top_k=5)
            # 写入缓存
            set_rag_cache(query, 5, policy_context)
        print(f"[Node: rag_policy] RAG 检索完成, 上下文长度: {len(policy_context)}")
    except Exception as e:
        print(f"[Node: rag_policy] RAG 检索异常 (降级为空): {e}")
        policy_context = "政策检索引擎暂不可用, 请手动查阅 CBAM/CCA 法规。"

    # 3. 获取基准值和免费配额比例
    from src.data.database import load_carbon_db
    carbon_db = load_carbon_db()
    benchmark_value = None
    free_allowance_rate = None

    if cbam_category:
        benchmarks_key = "cbam_benchmarks" if target_country == "EU" else "cca_benchmarks"
        benchmarks = carbon_db.get(benchmarks_key, {})
        cat_info = benchmarks.get(cbam_category)
        if cat_info:
            benchmark_value = cat_info.get("benchmark")
            free_allowance_rate = cat_info.get("free_allowance_2025", 0.95)

    return {
        "policy_info": policy_context,
        "cbam_category": cbam_category,
        "benchmark_value": benchmark_value,
        "free_allowance_rate": free_allowance_rate,
        "current_node": "rag_policy",
    }
