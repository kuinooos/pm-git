"""
碳排放计算引擎单元测试
验证 Scope 1/2/3 计算和 CBAM 合规分析的准确性。
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.calculator import (
    CarbonCalculator,
    TransportLeg,
    EnergyConsumption,
    MaterialInput,
)


def test_scope3_sea_transport():
    """测试海运碳排放计算"""
    calc = CarbonCalculator()
    legs = [
        TransportLeg(
            transport_type="sea_container",
            weight_tons=60.0,
            distance_km=18500,
            description="深圳 → 汉堡",
        ),
    ]
    total, detail = calc.calculate_scope3(legs)
    # 60 * 18500 * 0.000015 = 16.65
    assert abs(total - 16.65) < 0.01, f"Expected ~16.65, got {total}"
    assert len(detail) == 1
    print(f"[PASS] test_scope3_sea_transport passed: {total} tCO2e")


def test_scope3_multimodal():
    """测试多式联运碳排放计算"""
    calc = CarbonCalculator()
    legs = [
        TransportLeg("sea_container", 60.0, 18500, "海运"),
        TransportLeg("road_heavy_truck", 60.0, 200, "公路短驳"),
    ]
    total, detail = calc.calculate_scope3(legs)
    # 海运: 60 * 18500 * 0.000015 = 16.65
    # 公路: 60 * 200 * 0.000105 = 1.26
    # 总计: 17.91
    assert abs(total - 17.91) < 0.01, f"Expected ~17.91, got {total}"
    assert len(detail) == 2
    print(f"[PASS]test_scope3_multimodal passed: {total} tCO2e")


def test_scope1_material_emission():
    """测试材料生产排放计算"""
    calc = CarbonCalculator()
    materials = [
        MaterialInput("aluminum_primary", 60.0, "原铝生产"),
    ]
    total, detail = calc.calculate_scope1([], materials)
    # 60 * 16.5 = 990.0
    assert abs(total - 990.0) < 0.01, f"Expected ~990.0, got {total}"
    print(f"[PASS]test_scope1_material_emission passed: {total} tCO2e")


def test_scope2_electricity():
    """测试外购电力排放计算"""
    calc = CarbonCalculator()
    total, detail = calc.calculate_scope2(1200.0, "electricity_china_grid")
    # 1200 * 0.5810 = 697.2
    assert abs(total - 697.2) < 0.01, f"Expected ~697.2, got {total}"
    print(f"[PASS]test_scope2_electricity passed: {total} tCO2e")


def test_cbam_compliance():
    """测试 CBAM 合规分析"""
    calc = CarbonCalculator()

    # 先计算排放
    result = calc.calculate_emissions(
        transport_legs=[TransportLeg("sea_container", 60.0, 18500)],
        material_inputs=[MaterialInput("aluminum_primary", 60.0)],
        electricity_mwh=1200.0,
        grid_region="electricity_china_grid",
        cbam_category="aluminum",
        product_weight_tons=60.0,
        target_country="EU",
        year=2025,
    )

    # 验证 CBAM 分析
    assert result.cbam_category == "aluminum"
    assert result.cbam_benchmark == 15.2
    assert result.cbam_free_allowance == 0.95  # 2025年
    assert result.cbam_taxable_emissions > 0
    assert result.cbam_estimated_tax > 0

    print(f"[PASS]test_cbam_compliance passed:")
    print(f"   CBAM 排放: {result.cbam_relevant_emissions:.2f} tCO2e")
    print(f"   应纳税: {result.cbam_taxable_emissions:.2f} tCO2e")
    print(f"   预估关税: EUR{result.cbam_estimated_tax:.2f}")


def test_full_calculation():
    """测试完整碳排放计算"""
    calc = CarbonCalculator()

    result = calc.calculate_emissions(
        transport_legs=[
            TransportLeg("sea_container", 60.0, 18500, "海运"),
            TransportLeg("road_heavy_truck", 60.0, 200, "公路"),
        ],
        material_inputs=[MaterialInput("aluminum_primary", 60.0)],
        electricity_mwh=1200.0,
        grid_region="electricity_china_grid",
        cbam_category="aluminum",
        product_weight_tons=60.0,
        target_country="EU",
    )

    # 验证总量
    expected_total = result.scope1_emissions + result.scope2_emissions + result.scope3_emissions
    assert abs(result.total_emissions - expected_total) < 0.01

    print(f"[PASS]test_full_calculation passed:")
    print(f"   Scope 1: {result.scope1_emissions:.4f} tCO2e")
    print(f"   Scope 2: {result.scope2_emissions:.4f} tCO2e")
    print(f"   Scope 3: {result.scope3_emissions:.4f} tCO2e")
    print(f"   Total:   {result.total_emissions:.4f} tCO2e")


if __name__ == "__main__":
    print("=" * 60)
    print("碳排放计算引擎 - 单元测试")
    print("=" * 60)

    test_scope3_sea_transport()
    test_scope3_multimodal()
    test_scope1_material_emission()
    test_scope2_electricity()
    test_cbam_compliance()
    test_full_calculation()

    print(f"\n{'=' * 60}")
    print("[PASS]所有测试通过!")
    print("=" * 60)
