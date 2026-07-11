"""
监督者 Agent (Supervisor Node)
看板模式的控制循环核心。扫描看板状态，动态决定：
- 下一步该派哪个 Agent 上场
- 缺什么数据就补什么
- 所有产出就绪后吹哨收工

这是看板复合编排的第二环——"敏捷教练"在旁监督自发协作的团队。
"""

import json
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

from config.settings import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TEMPERATURE


SUPERVISOR_PROMPT = """你是碳审计多智能体系统的监督者（Supervisor）。你的职责是扫描看板（Blackboard）状态，决定工作流的下一步。

## 看板当前状态

**已完成步骤**:
- 数据萃取: {data_cleansing_done}
- 政策匹配: {policy_matcher_done}
- 排放计算: {calculator_done}
- 合规分析: {compliance_audit_done}
- 报告生成: {report_writer_done}

**当前数据质量**:
- 产品名: {product_name}
- HS Code: {hs_code}
- 材料类型: {material_type}
- 产品重量(吨): {product_weight_tons}
- CBAM 品类: {cbam_category}
- 总排放: {total_emissions}
- 风险等级: {risk_level}

**已有错误**: {errors}

**重试次数**: {retry_count} / 3

## 可用专家 Agent

| Agent | 职责 | 前置条件 |
|-------|------|----------|
| data_cleansing | 从原始数据提取结构化产品信息 | 有 raw_payload |
| policy_matcher | RAG 检索政策 + HS Code 判定 | 有 hs_code 或 材料类型 |
| calculator | 计算 Scope 1/2/3 碳排放 | 有产品重量 + 运输数据 |
| compliance_audit | 对标基准值做合规风险分析 | 有排放计算结果 |
| report_writer | 生成最终审计报告 | 以上全部完成 + 人工审批通过 |

## 决策规则

1. 如果 data_cleansing 未完成 → next: data_cleansing
2. 如果 policy_matcher 未完成且 hs_code/材料类型已提取 → next: policy_matcher
3. 如果 calculator 未完成且产品重量已提取 → next: calculator
4. 如果 compliance_audit 未完成且排放已计算 → next: compliance_audit
5. 如果以上全部完成且 report_writer 未完成 → next: report_writer
6. 如果 report_writer 已完成 → done
7. 如果某 Agent 连续失败且重试次数 >= 3 → error
8. 如果 raw_payload 为空或 product_name/hs_code 都为空 → 先让 data_cleansing 尝试，但标注数据不足风险

## 决策输出

请仅返回 JSON:
```json
{{"decision": "next|done|error", "agent": "data_cleansing|policy_matcher|calculator|compliance_audit|report_writer", "reason": "简述决策依据", "data_quality_warning": "如数据质量有问题，在此说明"}}
```"""


def _safe(field: str | None | float) -> str:
    """格式化看板字段显示"""
    if field is None:
        return "未设定"
    if isinstance(field, float) and field == 0.0:
        return "0（可能数据缺失）"
    return str(field)


def supervisor_node(state: dict) -> dict:
    """
    监督者节点: 扫描看板、决定下一步。

    输入: 完整的 AuditState
    输出:
        - supervisor_decision: "next" | "done" | "error"
        - supervisor_next_agent: 下一个要调用的 Agent 名
        - supervisor_reason: 决策理由
        - retry_count: 递增
    """
    print("[Node: supervisor] 扫描看板...")

    # 检查各 Agent 是否已完成
    has_clean = bool(state.get("clean_data", {}).get("product_name"))
    has_policy = bool(state.get("policy_info"))
    has_emissions = state.get("total_emissions", 0) > 0 or bool(
        state.get("emissions_result", {})
    )
    has_compliance = bool(state.get("compliance_risk"))
    has_report = bool(state.get("audit_report_md"))
    has_error = state.get("error", "")
    retry_count = state.get("retry_count", 0)

    # 必要时跳过 LLM，规则直接判定（节省 Token）
    # 规则1: 报告已生成 → 直接 done
    if has_report:
        print("[Node: supervisor] 报告已生成, 判定 done")
        return {
            "supervisor_decision": "done",
            "supervisor_next_agent": "",
            "supervisor_reason": "所有环节已完成，报告已生成。",
            "current_node": "supervisor",
        }

    # 规则2: 重试超限
    if retry_count >= 3:
        print("[Node: supervisor] 重试次数超限, 判定 error")
        return {
            "supervisor_decision": "error",
            "supervisor_next_agent": "",
            "supervisor_reason": f"重试次数已达上限 ({retry_count}/3)，终止工作流。",
            "current_node": "supervisor",
        }

    # 规则3: 按依赖顺序快速判定
    if not has_clean:
        next_agent = "data_cleansing"
        reason = "数据萃取未完成，需要提取产品信息。"
    elif not has_policy:
        next_agent = "policy_matcher"
        reason = "政策匹配未完成，需要查询 CBAM/CCA 政策。"
    elif not has_emissions:
        next_agent = "calculator"
        reason = "排放计算未完成，需要计算 Scope 1/2/3。"
    elif not has_compliance:
        next_agent = "compliance_audit"
        reason = "合规分析未完成，需要对标基准值。"
    elif not has_report:
        # 报告生成需要人工审批通过
        if state.get("approved"):
            next_agent = "report_writer"
            reason = "人工审批已通过，可生成最终报告。"
        else:
            # 数据都齐了但还没审批 → 不指派，等待人工审查
            print("[Node: supervisor] 所有 Agent 完成，等待人工审查")
            return {
                "supervisor_decision": "pending_review",
                "supervisor_next_agent": "",
                "supervisor_reason": "所有计算和分析已完成，等待人工审查。",
                "current_node": "supervisor",
            }
    else:
        next_agent = "report_writer"
        reason = "最终步骤: 生成审计报告。"

    print(f"[Node: supervisor] 决策: next={next_agent}, 理由: {reason}")

    # 如果当前有错误但从上次重试后，用 LLM 深度判断是否需要调整策略
    if has_error:
        # 有错误但规则判定继续 → LLM 复核是否有数据质量问题
        llm = ChatOpenAI(
            model=LLM_MODEL,
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            temperature=0,
            max_tokens=512,
        )
        prompt = ChatPromptTemplate.from_template(SUPERVISOR_PROMPT)
        chain = prompt | llm | StrOutputParser()

        prompt_vars = {
            "data_cleansing_done": "✅" if has_clean else "⬜",
            "policy_matcher_done": "✅" if has_policy else "⬜",
            "calculator_done": "✅" if has_emissions else "⬜",
            "compliance_audit_done": "✅" if has_compliance else "⬜",
            "report_writer_done": "✅" if has_report else "⬜",
            "product_name": _safe(state.get("product_name")),
            "hs_code": _safe(state.get("hs_code")),
            "material_type": _safe(state.get("material_type")),
            "product_weight_tons": _safe(state.get("product_weight_tons")),
            "cbam_category": _safe(state.get("cbam_category")),
            "total_emissions": _safe(state.get("total_emissions")),
            "risk_level": _safe(state.get("risk_level")),
            "errors": has_error,
            "retry_count": retry_count,
        }

        try:
            response = chain.invoke(prompt_vars)
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()
            llm_result = json.loads(json_str)
            # LLM 复核结果优先
            next_agent = llm_result.get("agent", next_agent)
            reason = llm_result.get("reason", reason)
        except Exception as e:
            print(f"[Node: supervisor] LLM 复核失败，使用规则判定: {e}")

    return {
        "supervisor_decision": "next",
        "supervisor_next_agent": next_agent,
        "supervisor_reason": reason,
        "retry_count": retry_count + 1 if has_error else retry_count,
        "current_node": "supervisor",
    }
