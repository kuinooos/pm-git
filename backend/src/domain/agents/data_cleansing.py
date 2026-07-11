"""
信息萃取 Agent (Data Cleansing Node)
利用 LLM 从非结构化输入数据中结构化提取关键信息: 产品类型、重量、运输路径等。
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TEMPERATURE


def get_llm() -> ChatOpenAI:
    """获取 LLM 实例"""
    return ChatOpenAI(
        model=LLM_MODEL,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        temperature=LLM_TEMPERATURE,
        max_tokens=2048,
    )


DATA_CLEANSING_PROMPT = """你是一个专业的跨境贸易数据萃取专家。请从以下原始报关/物料数据中提取关键结构化信息。

原始数据:
{raw_payload}

请严格按照以下 JSON 格式输出 (不要输出其他任何内容):
```json
{{
    "product_name": "产品名称",
    "hs_code": "HS海关编码(6位数字, 如不确定请根据产品类型推断最可能的编码)",
    "product_weight_tons": 0.0,
    "material_type": "材料类型(如 aluminum_primary/steel_bf_bof/cement_clinker/fertilizer_ammonia/hydrogen_grey, 如不确定填 unknown)",
    "origin_port": "出发港口",
    "destination_port": "目的港口",
    "transport_mode": "主要运输方式(sea_container/rail_freight/road_heavy_truck/air_freight_long)",
    "estimated_distance_km": 0,
    "electricity_mwh": 0.0,
    "fuel_type": "主要燃料类型(如 natural_gas/diesel/coal_steam/coke, 无则填 none)",
    "fuel_amount": 0.0,
    "fuel_unit": "燃料单位(如 吨/万m³)",
    "target_country": "目标出口国(EU/US)"
}}
```

注意事项:
1. 如果原始数据中缺少某个字段, 请根据产品类型和贸易常识进行合理推断
2. HS Code 必须是6位数字编码
3. 重量统一换算为吨 (tons)
4. material_type 必须从以下选项中选择: aluminum_primary, aluminum_secondary, steel_bf_bof, steel_eaf, cement_clinker, cement_portland, fertilizer_ammonia, hydrogen_grey, hydrogen_green, unknown
"""


def data_cleansing_node(state: dict) -> dict:
    """
    信息萃取节点: 从原始数据中提取结构化信息。

    Args:
        state: 工作流状态, 包含 raw_payload

    Returns:
        更新后的状态字段
    """
    print("[Node: data_cleansing] 开始信息萃取...")

    raw_payload = state.get("raw_payload", {})
    raw_str = json.dumps(raw_payload, ensure_ascii=False, indent=2)

    # 调用 LLM 提取结构化数据
    llm = get_llm()
    prompt = ChatPromptTemplate.from_template(DATA_CLEANSING_PROMPT)
    chain = prompt | llm | StrOutputParser()

    try:
        response = chain.invoke({"raw_payload": raw_str})

        # 提取 JSON (处理可能的 markdown 代码块包裹)
        json_str = response.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        clean_data = json.loads(json_str)
        print(f"[Node: data_cleansing] 萃取完成: 产品={clean_data.get('product_name')}, "
              f"HS={clean_data.get('hs_code')}, 重量={clean_data.get('product_weight_tons')}吨")

        # 构建运输段信息
        transport_legs = []
        transport_mode = clean_data.get("transport_mode", "sea_container")
        distance = clean_data.get("estimated_distance_km", 0)
        weight = clean_data.get("product_weight_tons", 0)

        if distance and weight:
            # 主运输段
            transport_legs.append({
                "transport_type": transport_mode,
                "weight_tons": weight,
                "distance_km": distance,
                "description": f"{clean_data.get('origin_port', '')} → {clean_data.get('destination_port', '')}",
            })
            # 尾程公路短驳 (固定 200km)
            transport_legs.append({
                "transport_type": "road_heavy_truck",
                "weight_tons": weight,
                "distance_km": 200,
                "description": "目的港 → 仓库 (公路短驳)",
            })

        # 构建燃料消耗列表
        fuel_consumptions = []
        fuel_type = clean_data.get("fuel_type", "none")
        fuel_amount = clean_data.get("fuel_amount", 0)
        fuel_unit = clean_data.get("fuel_unit", "")
        if fuel_type and fuel_type != "none" and fuel_amount:
            fuel_consumptions.append({
                "energy_type": fuel_type,
                "amount": fuel_amount,
                "unit": fuel_unit,
                "description": "生产过程燃料消耗",
            })

        return {
            "clean_data": clean_data,
            "hs_code": clean_data.get("hs_code", ""),
            "product_name": clean_data.get("product_name", ""),
            "product_weight_tons": clean_data.get("product_weight_tons", 0.0),
            "material_type": clean_data.get("material_type", "unknown"),
            "origin_port": clean_data.get("origin_port", ""),
            "destination_port": clean_data.get("destination_port", ""),
            "target_country": clean_data.get("target_country", state.get("target_country", "EU")),
            "transport_legs": transport_legs,
            "electricity_mwh": clean_data.get("electricity_mwh", 0.0),
            "fuel_consumptions": fuel_consumptions,
            "current_node": "data_cleansing",
        }

    except json.JSONDecodeError as e:
        print(f"[Node: data_cleansing] JSON 解析失败: {e}")
        print(f"[Node: data_cleansing] LLM 原始输出: {response[:200]}")
        return {
            "clean_data": {},
            "current_node": "data_cleansing",
            "error": f"数据萃取 JSON 解析失败: {e}",
        }
    except Exception as e:
        print(f"[Node: data_cleansing] 错误: {e}")
        return {
            "clean_data": {},
            "current_node": "data_cleansing",
            "error": str(e),
        }
