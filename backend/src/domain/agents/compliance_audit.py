"""
合规风控 Agent (Compliance Audit Node)
对比碳排放计算结果与政策基准值, 生成风险分析报告和整改建议。
"""

import json
import os
import sys
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TEMPERATURE


COMPLIANCE_AUDIT_PROMPT = """你是一位资深的碳合规审计专家。请根据以下审计数据, 生成合规风险分析和整改建议。

## 审计数据

产品名称: {product_name}
HS Code: {hs_code}
CBAM/CCA 管控品类: {cbam_category}
目标出口国: {target_country}

### 碳排放计算结果
- Scope 1 (直接排放): {scope1} tCO2e
- Scope 2 (电力间接): {scope2} tCO2e
- Scope 3 (物流运输): {scope3} tCO2e
- 总排放量: {total} tCO2e

### CBAM/CCA 合规分析
- 管控品类基准值: {benchmark} tCO2e/吨
- 免费配额比例: {free_allowance}
- CBAM 相关排放: {cbam_emissions} tCO2e
- 应纳税排放量: {taxable_emissions} tCO2e
- 预估碳关税: EUR {estimated_tax}

### 产品重量
{product_weight} 吨

### 政策依据
{policy_info}

---

请输出以下内容 (使用 Markdown 格式):

1. **风险等级判定** (low/medium/high):
   - low: 应纳税排放量为 0 或极低, 无合规风险
   - medium: 存在应纳税排放, 但低于行业平均水平
   - high: 应纳税排放量较高, 面临显著碳关税成本

2. **合规风险分析** (200-300字, 分析排放超标的原因和潜在影响)

3. **整改建议** (3-5条具体可操作的减排建议, 包括技术改造、能源优化、供应链调整等)

请严格按以下格式输出:
风险等级: [low/medium/high]

## 合规风险分析
[分析内容]

## 整改建议
1. [建议1]
2. [建议2]
3. [建议3]
"""


def compliance_audit_node(state: dict) -> dict:
    """
    合规风控节点: 对标基准值, 生成风险分析。

    Args:
        state: 工作流状态

    Returns:
        更新后的状态字段
    """
    print("[Node: compliance_audit] 开始合规风控分析...")

    emissions = state.get("emissions_result", {})

    # 准备 LLM 输入
    prompt_vars = {
        "product_name": state.get("product_name", "未知产品"),
        "hs_code": state.get("hs_code", "未知"),
        "cbam_category": state.get("cbam_category") or "非管控品类",
        "target_country": state.get("target_country", "EU"),
        "scope1": emissions.get("scope1_emissions", 0),
        "scope2": emissions.get("scope2_emissions", 0),
        "scope3": emissions.get("scope3_emissions", 0),
        "total": state.get("total_emissions", 0),
        "benchmark": state.get("benchmark_value") or "无基准值",
        "free_allowance": f"{state.get('free_allowance_rate', 0):.1%}" if state.get("free_allowance_rate") else "无",
        "cbam_emissions": emissions.get("cbam_relevant_emissions", 0),
        "taxable_emissions": emissions.get("cbam_taxable_emissions", 0),
        "estimated_tax": emissions.get("cbam_estimated_tax", 0),
        "product_weight": state.get("product_weight_tons", 0),
        "policy_info": state.get("policy_info", "无政策信息")[:1000],  # 截断避免超长
    }

    # 调用 LLM 生成风险分析
    llm = ChatOpenAI(
        model=LLM_MODEL,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        temperature=0.3,
        max_tokens=1024,
    )
    prompt = ChatPromptTemplate.from_template(COMPLIANCE_AUDIT_PROMPT)
    chain = prompt | llm | StrOutputParser()

    try:
        analysis = chain.invoke(prompt_vars)

        # 解析风险等级
        risk_level = "medium"  # 默认
        for line in analysis.split("\n"):
            if "风险等级" in line and ":" in line:
                level_part = line.split(":")[-1].strip().lower()
                if "high" in level_part:
                    risk_level = "high"
                elif "low" in level_part:
                    risk_level = "low"
                else:
                    risk_level = "medium"
                break

        # 分离整改建议
        compliance_risk = analysis
        rectification_advice = ""
        if "## 整改建议" in analysis:
            parts = analysis.split("## 整改建议")
            compliance_risk = parts[0].strip()
            rectification_advice = "## 整改建议" + parts[1].strip() if len(parts) > 1 else ""

        print(f"[Node: compliance_audit] 风险等级: {risk_level}")

        return {
            "compliance_risk": compliance_risk,
            "risk_level": risk_level,
            "rectification_advice": rectification_advice,
            "current_node": "compliance_audit",
        }

    except Exception as e:
        print(f"[Node: compliance_audit] LLM 调用失败: {e}")
        # 降级: 基于数值简单判定
        taxable = emissions.get("cbam_taxable_emissions", 0)
        if taxable == 0:
            risk_level = "low"
        elif taxable < 50:
            risk_level = "medium"
        else:
            risk_level = "high"

        return {
            "compliance_risk": f"合规分析降级模式: 应纳税排放 {taxable} tCO2e, 风险等级 {risk_level}",
            "risk_level": risk_level,
            "rectification_advice": "建议: 1. 优化能源结构 2. 采用低碳材料 3. 提升运输效率",
            "current_node": "compliance_audit",
        }
