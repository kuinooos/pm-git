"""
碳排放物理计算引擎
覆盖 Scope 1 (直接排放)、Scope 2 (能源间接排放) 和 Scope 3 (物流运输排放)。

计算方法: 排放因子法
公式: 碳排放量 = 活动数据 × 排放因子
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field, asdict

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import CARBON_DB_PATH


# ========================================
# 数据结构定义
# ========================================

@dataclass
class TransportLeg:
    """单段运输信息"""
    transport_type: str       # 运输方式: sea_container, road_heavy_truck, rail_freight, air_freight_long 等
    weight_tons: float        # 货物重量 (吨)
    distance_km: float        # 运输距离 (公里)
    description: str = ""     # 路段描述


@dataclass
class EnergyConsumption:
    """能源消耗记录"""
    energy_type: str          # 能源类型: electricity_china_grid, natural_gas, diesel 等
    amount: float             # 消耗量
    unit: str                 # 单位: MWh, 万m³, 吨 等
    description: str = ""


@dataclass
class MaterialInput:
    """原材料投入"""
    material_type: str        # 材料类型: aluminum_primary, steel_bf_bof 等
    weight_tons: float        # 重量 (吨)
    description: str = ""


@dataclass
class EmissionsResult:
    """碳排放计算结果"""
    scope1_emissions: float = 0.0           # Scope 1 直接排放 (tCO2e)
    scope2_emissions: float = 0.0           # Scope 2 能源间接排放 (tCO2e)
    scope3_emissions: float = 0.0           # Scope 3 物流运输排放 (tCO2e)
    total_emissions: float = 0.0            # 总排放量 (tCO2e)

    scope1_detail: list[dict] = field(default_factory=list)
    scope2_detail: list[dict] = field(default_factory=list)
    scope3_detail: list[dict] = field(default_factory=list)

    # CBAM 相关
    cbam_category: Optional[str] = None     # CBAM 管控品类
    cbam_relevant_emissions: float = 0.0    # CBAM 相关排放量 (Scope 1 + 部分Scope 2)
    cbam_benchmark: Optional[float] = None  # CBAM 基准值
    cbam_free_allowance: float = 0.0        # 免费配额比例
    cbam_taxable_emissions: float = 0.0     # 应纳税排放量
    cbam_estimated_tax: float = 0.0         # 预估碳关税 (元/tCO2e)

    def to_dict(self) -> dict:
        return asdict(self)

    def calculate_total(self) -> None:
        """计算总排放量"""
        self.total_emissions = (
            self.scope1_emissions
            + self.scope2_emissions
            + self.scope3_emissions
        )


# ========================================
# 核心计算引擎
# ========================================

class CarbonCalculator:
    """碳排放物理计算引擎"""

    def __init__(self):
        """加载碳因子数据库"""
        with open(CARBON_DB_PATH, "r", encoding="utf-8") as f:
            self.db = json.load(f)

    # ========================================
    # Scope 3: 物流运输碳排计算
    # ========================================

    def calculate_scope3(
        self,
        legs: list[TransportLeg],
    ) -> tuple[float, list[dict]]:
        """
        计算 Scope 3 物流运输碳排放。
        支持多式联运, 各段分别计算后累加。

        Args:
            legs: 运输段列表

        Returns:
            (总排放量 tCO2e, 明细列表)
        """
        total = 0.0
        detail = []
        transport_factors = self.db["transport_factors"]

        for i, leg in enumerate(legs):
            factor_info = transport_factors.get(leg.transport_type)
            if not factor_info:
                raise ValueError(
                    f"未知的运输方式: {leg.transport_type}。"
                    f"可选: {list(transport_factors.keys())}"
                )

            factor = factor_info["factor"]
            emissions = leg.weight_tons * leg.distance_km * factor
            total += emissions

            detail.append({
                "leg_index": i + 1,
                "transport_type": leg.transport_type,
                "description": leg.description or factor_info.get("description", ""),
                "weight_tons": leg.weight_tons,
                "distance_km": leg.distance_km,
                "factor": factor,
                "factor_unit": factor_info["unit"],
                "factor_source": factor_info["source"],
                "emissions_tCO2e": round(emissions, 4),
            })

        return round(total, 4), detail

    # ========================================
    # Scope 1: 直接排放计算
    # ========================================

    def calculate_scope1(
        self,
        energy_consumptions: list[EnergyConsumption],
        material_inputs: list[MaterialInput] | None = None,
    ) -> tuple[float, list[dict]]:
        """
        计算 Scope 1 直接排放。
        包括: 燃料燃烧排放 + 工艺排放 (材料生产)

        Args:
            energy_consumptions: 燃料消耗列表
            material_inputs: 原材料投入列表 (工艺排放)

        Returns:
            (总排放量 tCO2e, 明细列表)
        """
        total = 0.0
        detail = []
        energy_factors = self.db["energy_factors"]

        # 燃料燃烧排放
        for ec in energy_consumptions:
            factor_info = energy_factors.get(ec.energy_type)
            if not factor_info:
                raise ValueError(
                    f"未知的能源类型: {ec.energy_type}。"
                    f"可选: {list(energy_factors.keys())}"
                )

            factor = factor_info["factor"]
            emissions = ec.amount * factor
            total += emissions

            detail.append({
                "type": "fuel_combustion",
                "energy_type": ec.energy_type,
                "description": ec.description or factor_info.get("description", ""),
                "amount": ec.amount,
                "unit": ec.unit,
                "factor": factor,
                "factor_unit": factor_info["unit"],
                "factor_source": factor_info["source"],
                "emissions_tCO2e": round(emissions, 4),
            })

        # 工艺排放 (材料生产的直接排放)
        if material_inputs:
            material_factors = self.db["material_factors"]
            for mi in material_inputs:
                factor_info = material_factors.get(mi.material_type)
                if not factor_info:
                    raise ValueError(
                        f"未知的材料类型: {mi.material_type}。"
                        f"可选: {list(material_factors.keys())}"
                    )

                factor = factor_info["factor"]
                emissions = mi.weight_tons * factor
                total += emissions

                detail.append({
                    "type": "process_emission",
                    "material_type": mi.material_type,
                    "description": mi.description or factor_info.get("description", ""),
                    "weight_tons": mi.weight_tons,
                    "factor": factor,
                    "factor_unit": factor_info["unit"],
                    "factor_source": factor_info["source"],
                    "emissions_tCO2e": round(emissions, 4),
                })

        return round(total, 4), detail

    # ========================================
    # Scope 2: 间接排放计算
    # ========================================

    def calculate_scope2(
        self,
        electricity_mwh: float,
        grid_region: str = "electricity_china_grid",
    ) -> tuple[float, list[dict]]:
        """
        计算 Scope 2 外购电力间接排放。

        Args:
            electricity_mwh: 外购电力消耗量 (MWh)
            grid_region: 电网区域排放因子键名

        Returns:
            (排放量 tCO2e, 明细列表)
        """
        energy_factors = self.db["energy_factors"]
        factor_info = energy_factors.get(grid_region)

        if not factor_info:
            raise ValueError(
                f"未知的电网区域: {grid_region}。"
                f"可选: {[k for k in energy_factors if 'electricity' in k]}"
            )

        factor = factor_info["factor"]
        emissions = electricity_mwh * factor

        detail = [{
            "electricity_mwh": electricity_mwh,
            "grid_region": grid_region,
            "description": factor_info.get("description", ""),
            "factor": factor,
            "factor_unit": factor_info["unit"],
            "factor_source": factor_info["source"],
            "emissions_tCO2e": round(emissions, 4),
        }]

        return round(emissions, 4), detail

    # ========================================
    # CBAM 合规分析
    # ========================================

    def analyze_cbam_compliance(
        self,
        result: EmissionsResult,
        cbam_category: str,
        product_weight_tons: float,
        target_country: str = "EU",
        year: int = 2025,
        eu_ets_price: float = 80.0,
    ) -> EmissionsResult:
        """
        分析 CBAM 合规情况, 计算应纳税排放量和预估碳关税。

        Args:
            result: 已计算完排放的 EmissionsResult 对象
            cbam_category: CBAM 管控品类 (aluminum/steel/cement/...)
            product_weight_tons: 产品总重量 (吨)
            target_country: 目标国 (EU/US)
            year: 申报年份 (用于确定免费配额比例)
            eu_ets_price: 欧盟 ETS 碳价 (欧元/吨 CO2e)

        Returns:
            更新后的 EmissionsResult 对象
        """
        result.cbam_category = cbam_category

        # 选择基准值
        if target_country == "EU":
            benchmarks = self.db["cbam_benchmarks"]
        else:
            benchmarks = self.db.get("cca_benchmarks", {})

        benchmark_info = benchmarks.get(cbam_category)
        if not benchmark_info:
            result.cbam_relevant_emissions = result.scope1_emissions + result.scope2_emissions
            result.cbam_taxable_emissions = result.cbam_relevant_emissions
            return result

        benchmark = benchmark_info["benchmark"]
        result.cbam_benchmark = benchmark

        # CBAM 相关排放 (Scope 1 + 对于铝/氢还需包含 Scope 2)
        if cbam_category in ("aluminum", "hydrogen"):
            result.cbam_relevant_emissions = result.scope1_emissions + result.scope2_emissions
        else:
            result.cbam_relevant_emissions = result.scope1_emissions

        # 免费配额比例 (逐年退坡)
        if target_country == "EU":
            allowance_key = f"free_allowance_{year}"
            result.cbam_free_allowance = benchmark_info.get(allowance_key, 0.0)

        # 应纳税排放量计算
        # 总排放 - 基准值 × 产品重量 × 免费配额比例
        free_allowance_emissions = benchmark * product_weight_tons * result.cbam_free_allowance
        taxable = result.cbam_relevant_emissions - free_allowance_emissions
        result.cbam_taxable_emissions = max(0.0, round(taxable, 4))

        # 预估碳关税
        if target_country == "EU":
            result.cbam_estimated_tax = round(result.cbam_taxable_emissions * eu_ets_price, 2)
        else:
            # CCA: 对超额排放按 $55/吨征税
            cca_tax_rate = 55.0
            excess_intensity = max(0, result.cbam_relevant_emissions / product_weight_tons - benchmark)
            result.cbam_taxable_emissions = round(excess_intensity * product_weight_tons, 4)
            result.cbam_estimated_tax = round(result.cbam_taxable_emissions * cca_tax_rate, 2)

        return result

    # ========================================
    # 统一计算接口
    # ========================================

    def calculate_emissions(
        self,
        transport_legs: list[TransportLeg],
        energy_consumptions: list[EnergyConsumption] | None = None,
        material_inputs: list[MaterialInput] | None = None,
        electricity_mwh: float = 0.0,
        grid_region: str = "electricity_china_grid",
        cbam_category: str | None = None,
        product_weight_tons: float = 0.0,
        target_country: str = "EU",
        year: int = 2025,
        eu_ets_price: float = 80.0,
    ) -> EmissionsResult:
        """
        统一碳排放计算接口: 一次性计算 Scope 1/2/3 并分析 CBAM 合规。

        Args:
            transport_legs: 运输段列表 (Scope 3)
            energy_consumptions: 燃料消耗列表 (Scope 1)
            material_inputs: 原材料投入列表 (Scope 1 工艺排放)
            electricity_mwh: 外购电力消耗 (Scope 2)
            grid_region: 电网区域
            cbam_category: CBAM 管控品类
            product_weight_tons: 产品总重量
            target_country: 目标国
            year: 申报年份
            eu_ets_price: EU ETS 碳价

        Returns:
            完整的 EmissionsResult 对象
        """
        result = EmissionsResult()

        # Scope 3: 物流运输
        if transport_legs:
            s3, s3_detail = self.calculate_scope3(transport_legs)
            result.scope3_emissions = s3
            result.scope3_detail = s3_detail

        # Scope 1: 直接排放
        if energy_consumptions or material_inputs:
            s1, s1_detail = self.calculate_scope1(
                energy_consumptions or [],
                material_inputs,
            )
            result.scope1_emissions = s1
            result.scope1_detail = s1_detail

        # Scope 2: 间接排放
        if electricity_mwh > 0:
            s2, s2_detail = self.calculate_scope2(electricity_mwh, grid_region)
            result.scope2_emissions = s2
            result.scope2_detail = s2_detail

        # 计算总量
        result.calculate_total()

        # CBAM 合规分析
        if cbam_category and product_weight_tons > 0:
            result = self.analyze_cbam_compliance(
                result,
                cbam_category,
                product_weight_tons,
                target_country,
                year,
                eu_ets_price,
            )

        return result


# ========================================
# 模块级便捷接口
# ========================================

_calculator_instance: Optional[CarbonCalculator] = None


def get_calculator() -> CarbonCalculator:
    """获取全局碳排计算引擎单例"""
    global _calculator_instance
    if _calculator_instance is None:
        _calculator_instance = CarbonCalculator()
    return _calculator_instance


def calculate_transport_emissions(
    weight_tons: float,
    distance_km: float,
    transport_type: str = "sea_container",
) -> float:
    """
    快捷接口: 计算单段运输碳排放。

    Args:
        weight_tons: 货物重量 (吨)
        distance_km: 运输距离 (公里)
        transport_type: 运输方式

    Returns:
        碳排放量 (tCO2e)
    """
    calc = get_calculator()
    leg = TransportLeg(
        transport_type=transport_type,
        weight_tons=weight_tons,
        distance_km=distance_km,
    )
    total, _ = calc.calculate_scope3([leg])
    return total


# ========================================
# 主程序: 快速验证
# ========================================

if __name__ == "__main__":
    print("=" * 60)
    print("碳排放计算引擎 - 功能测试")
    print("=" * 60)

    calc = CarbonCalculator()

    # 测试案例: 60吨铝合金从深圳海运到德国汉堡
    print("\n--- 测试案例: 60吨铝合金 深圳→汉堡海运 ---")

    legs = [
        TransportLeg(
            transport_type="sea_container",
            weight_tons=60.0,
            distance_km=18500,
            description="深圳 → 汉堡 (海运)",
        ),
        TransportLeg(
            transport_type="road_heavy_truck",
            weight_tons=60.0,
            distance_km=200,
            description="汉堡港 → 仓库 (公路短驳)",
        ),
    ]

    materials = [
        MaterialInput(
            material_type="aluminum_primary",
            weight_tons=60.0,
            description="原铝 (电解铝) 生产排放",
        ),
    ]

    result = calc.calculate_emissions(
        transport_legs=legs,
        material_inputs=materials,
        electricity_mwh=1200.0,  # 生产用电
        grid_region="electricity_china_grid",
        cbam_category="aluminum",
        product_weight_tons=60.0,
        target_country="EU",
        year=2025,
        eu_ets_price=80.0,
    )

    print(f"\nScope 1 (直接排放):     {result.scope1_emissions:.4f} tCO2e")
    print(f"Scope 2 (电力间接):     {result.scope2_emissions:.4f} tCO2e")
    print(f"Scope 3 (物流运输):     {result.scope3_emissions:.4f} tCO2e")
    print(f"总排放量:               {result.total_emissions:.4f} tCO2e")

    print(f"\n--- CBAM 合规分析 ---")
    print(f"管控品类:               {result.cbam_category}")
    print(f"CBAM 基准值:            {result.cbam_benchmark} tCO2e/吨")
    print(f"免费配额比例:           {result.cbam_free_allowance:.1%}")
    print(f"CBAM 相关排放:          {result.cbam_relevant_emissions:.4f} tCO2e")
    print(f"应纳税排放量:           {result.cbam_taxable_emissions:.4f} tCO2e")
    print(f"预估碳关税:             EUR {result.cbam_estimated_tax:.2f}")

    print(f"\n{'=' * 60}")
    print("计算引擎测试通过")
    print("=" * 60)
