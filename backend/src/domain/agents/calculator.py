"""
排放计算 Agent (Calculator Node)
调用碳排计算引擎, 计算 Scope 1/2/3 排放并分析 CBAM 合规性。
"""

import json
import os
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.calculator import (
    CarbonCalculator,
    TransportLeg,
    EnergyConsumption,
    MaterialInput,
)


def calculator_node(state: dict) -> dict:
    """
    排放计算节点: 计算 Scope 1/2/3 并分析 CBAM 合规。

    Args:
        state: 工作流状态

    Returns:
        更新后的状态字段
    """
    print("[Node: calculate_emissions] 开始碳排放计算...")

    calc = CarbonCalculator()

    # 从状态中提取计算所需参数
    transport_legs_raw = state.get("transport_legs", [])
    fuel_consumptions_raw = state.get("fuel_consumptions", [])
    electricity_mwh = state.get("electricity_mwh", 0.0)
    material_type = state.get("material_type", "unknown")
    product_weight_tons = state.get("product_weight_tons", 0.0)
    cbam_category = state.get("cbam_category")
    target_country = state.get("target_country", "EU")

    # 构建运输段对象
    transport_legs = [
        TransportLeg(
            transport_type=leg["transport_type"],
            weight_tons=leg["weight_tons"],
            distance_km=leg["distance_km"],
            description=leg.get("description", ""),
        )
        for leg in transport_legs_raw
    ]

    # 构建燃料消耗对象
    energy_consumptions = [
        EnergyConsumption(
            energy_type=ec["energy_type"],
            amount=ec["amount"],
            unit=ec.get("unit", ""),
            description=ec.get("description", ""),
        )
        for ec in fuel_consumptions_raw
    ]

    # 构建材料投入对象 (工艺排放)
    material_inputs = []
    if material_type and material_type != "unknown":
        material_inputs.append(MaterialInput(
            material_type=material_type,
            weight_tons=product_weight_tons,
            description="原材料生产排放",
        ))

    # 选择电网区域
    if target_country == "EU":
        grid_region = "electricity_eu_grid"
    elif target_country == "US":
        grid_region = "electricity_us_grid"
    else:
        grid_region = "electricity_china_grid"

    print(f"[Node: calculate_emissions] 运输段: {len(transport_legs)}, "
          f"燃料: {len(energy_consumptions)}, 材料: {len(material_inputs)}, "
          f"电力: {electricity_mwh} MWh")

    # 执行计算
    result = calc.calculate_emissions(
        transport_legs=transport_legs,
        energy_consumptions=energy_consumptions,
        material_inputs=material_inputs,
        electricity_mwh=electricity_mwh,
        grid_region=grid_region,
        cbam_category=cbam_category,
        product_weight_tons=product_weight_tons,
        target_country=target_country,
        year=2025,
        eu_ets_price=80.0,
    )

    result_dict = result.to_dict()

    print(f"[Node: calculate_emissions] 计算完成:")
    print(f"  Scope 1: {result.scope1_emissions:.4f} tCO2e")
    print(f"  Scope 2: {result.scope2_emissions:.4f} tCO2e")
    print(f"  Scope 3: {result.scope3_emissions:.4f} tCO2e")
    print(f"  总排放: {result.total_emissions:.4f} tCO2e")
    if result.cbam_taxable_emissions > 0:
        print(f"  CBAM 应纳税排放: {result.cbam_taxable_emissions:.4f} tCO2e")
        print(f"  预估碳关税: EUR {result.cbam_estimated_tax:.2f}")

    return {
        "emissions_result": result_dict,
        "total_emissions": result.total_emissions,
        "current_node": "calculate_emissions",
    }
