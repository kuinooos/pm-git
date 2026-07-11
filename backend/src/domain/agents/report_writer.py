"""
报告生成 Agent (Report Writer Node)
整合所有审计步骤和人工反馈, 撰写正式的碳合规审计报告 (Markdown 格式)。
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TEMPERATURE


REPORT_TEMPLATE = """# 全球碳关税合规审计报告

**报告编号**: CBAM-AUDIT-{report_id}
**出具日期**: {report_date}
**审计标准**: ISO 14064 / EU CBAM Regulation 2023/956

---

## 一、审计概述

| 项目 | 内容 |
|------|------|
| 产品名称 | {product_name} |
| HS Code | {hs_code} |
| CBAM/CCA 管控品类 | {cbam_category} |
| 目标出口国 | {target_country} |
| 产品重量 | {product_weight} 吨 |
| 风险等级 | **{risk_level}** |

---

## 二、碳排放核算结果

### 2.1 Scope 1 - 直接排放
{scope1_detail}

**Scope 1 小计: {scope1_total} tCO2e**

### 2.2 Scope 2 - 能源间接排放
{scope2_detail}

**Scope 2 小计: {scope2_total} tCO2e**

### 2.3 Scope 3 - 物流运输排放
{scope3_detail}

**Scope 3 小计: {scope3_total} tCO2e**

### 2.4 排放总量
**总碳排放量: {total_emissions} tCO2e**

---

## 三、CBAM/CCA 合规分析

| 项目 | 数值 |
|------|------|
| 管控品类基准值 | {benchmark} tCO2e/吨 |
| 免费配额比例 | {free_allowance} |
| CBAM 相关排放量 | {cbam_emissions} tCO2e |
| 应纳税排放量 | {taxable_emissions} tCO2e |
| 预估碳关税 | EUR {estimated_tax} |

{compliance_risk}

---

## 四、整改建议

{rectification_advice}

---

## 五、人工审查记录

{review_record}

---

## 六、政策依据

{policy_info}

---

## 七、免责声明

本报告由 AI 多智能体系统自动生成, 仅供初步合规参考。正式申报前请由持证第三方核查机构进行验证。

**报告生成时间**: {report_datetime}
**系统版本**: Carbon Compliance Agent v1.0
"""


def report_writer_node(state: dict) -> dict:
    """
    报告生成节点: 整合所有审计步骤, 生成终版 Markdown 报告。

    Args:
        state: 工作流状态

    Returns:
        更新后的状态字段
    """
    print("[Node: generate_report] 开始生成审计报告...")

    now = datetime.now()
    report_id = now.strftime("%Y%m%d%H%M%S")
    report_date = now.strftime("%Y-%m-%d")
    report_datetime = now.strftime("%Y-%m-%d %H:%M:%S")

    emissions = state.get("emissions_result", {})

    # 格式化 Scope 1 明细
    scope1_detail = "无数据"
    if emissions.get("scope1_detail"):
        scope1_lines = []
        for item in emissions["scope1_detail"]:
            scope1_lines.append(
                f"- {item.get('description', item.get('energy_type', item.get('material_type', '')))}: "
                f"{item.get('amount', item.get('weight_tons', 0))} {item.get('unit', '吨')} × "
                f"{item.get('factor', 0)} {item.get('factor_unit', '')} = "
                f"**{item.get('emissions_tCO2e', 0)} tCO2e** "
                f"(来源: {item.get('factor_source', '')})"
            )
        scope1_detail = "\n".join(scope1_lines)

    # 格式化 Scope 2 明细
    scope2_detail = "无数据"
    if emissions.get("scope2_detail"):
        scope2_lines = []
        for item in emissions["scope2_detail"]:
            scope2_lines.append(
                f"- {item.get('description', '')}: "
                f"{item.get('electricity_mwh', 0)} MWh × "
                f"{item.get('factor', 0)} {item.get('factor_unit', '')} = "
                f"**{item.get('emissions_tCO2e', 0)} tCO2e** "
                f"(来源: {item.get('factor_source', '')})"
            )
        scope2_detail = "\n".join(scope2_lines)

    # 格式化 Scope 3 明细
    scope3_detail = "无数据"
    if emissions.get("scope3_detail"):
        scope3_lines = []
        for item in emissions["scope3_detail"]:
            scope3_lines.append(
                f"- 路段 {item.get('leg_index', '')} ({item.get('description', '')}): "
                f"{item.get('weight_tons', 0)} 吨 × {item.get('distance_km', 0)} km × "
                f"{item.get('factor', 0)} {item.get('factor_unit', '')} = "
                f"**{item.get('emissions_tCO2e', 0)} tCO2e** "
                f"(来源: {item.get('factor_source', '')})"
            )
        scope3_detail = "\n".join(scope3_lines)

    # 人工审查记录
    reviewer = state.get("reviewer_feedback", "")
    review_record = ""
    if state.get("approved"):
        review_record = f"✅ 已通过人工审查\n\n审查备注: {reviewer or '无修改'}"
    else:
        review_record = "⚠️ 尚未通过人工审查"

    # 填充模板
    report_md = REPORT_TEMPLATE.format(
        report_id=report_id,
        report_date=report_date,
        report_datetime=report_datetime,
        product_name=state.get("product_name", "未知"),
        hs_code=state.get("hs_code", "未知"),
        cbam_category=state.get("cbam_category") or "非管控品类",
        target_country=state.get("target_country", "EU"),
        product_weight=state.get("product_weight_tons", 0),
        risk_level=state.get("risk_level", "未评估"),
        scope1_detail=scope1_detail,
        scope1_total=emissions.get("scope1_emissions", 0),
        scope2_detail=scope2_detail,
        scope2_total=emissions.get("scope2_emissions", 0),
        scope3_detail=scope3_detail,
        scope3_total=emissions.get("scope3_emissions", 0),
        total_emissions=state.get("total_emissions", 0),
        benchmark=state.get("benchmark_value") or "无基准值",
        free_allowance=f"{state.get('free_allowance_rate', 0):.1%}" if state.get("free_allowance_rate") else "无",
        cbam_emissions=emissions.get("cbam_relevant_emissions", 0),
        taxable_emissions=emissions.get("cbam_taxable_emissions", 0),
        estimated_tax=emissions.get("cbam_estimated_tax", 0),
        compliance_risk=state.get("compliance_risk", "无风险分析"),
        rectification_advice=state.get("rectification_advice", "无整改建议"),
        review_record=review_record,
        policy_info=state.get("policy_info", "无政策信息")[:2000],
    )

    print(f"[Node: generate_report] 报告生成完成, 长度: {len(report_md)} 字符")

    return {
        "audit_report_md": report_md,
        "current_node": "generate_report",
    }
