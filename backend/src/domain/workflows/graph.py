"""
LangGraph 多智能体工作流 — 看板 + 监督者 复合编排

架构模式:
    Router（路由分诊）→ Supervisor（监督者循环）→ 看板（共享状态）

    宏观: 路由 + 看板 + 监督者 三合一复合编排
    微观: 每个 Agent 内部单步执行（ReAct 改造留待下一期）

工作流拓扑:
    START → router ──→ [chat] END
                  ├──→ [policy_query] RAG直接检索 → END
                  └──→ [carbon_audit] supervisor ◄──┐
                                       │             │
                              ┌────────┼────────┐    │
                              ▼        ▼        ▼    │
                           data    policy  calculator │
                           _clean  _match   _emit    │
                              │        │        │    │
                              └────────┴────────┘    │
                                 compliance_audit ────┘
                                 report_writer

Human-in-the-Loop:
    - 所有 Agent 完成后，supervisor 判定 "pending_review"
    - human_review 使用 interrupt() 暂停
    - 用户审批后通过 Command(resume=...) 恢复
    - Supervisor 检测到 approved=True → 派 report_writer 上场
"""

import os
import sys
import uuid
from pathlib import Path
from typing import Optional, Literal

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt, Command

from config.settings import CHECKPOINT_DB_PATH
from src.domain.workflows.state import AuditState
from src.domain.agents.router import router_node
from src.domain.agents.supervisor import supervisor_node
from src.domain.agents.data_cleansing import data_cleansing_node
from src.domain.agents.policy_matcher import policy_matcher_node
from src.domain.agents.calculator import calculator_node
from src.domain.agents.compliance_audit import compliance_audit_node
from src.domain.agents.report_writer import report_writer_node


# ========================================
# 条件路由函数
# ========================================

def after_router(state: dict) -> str:
    """
    Router 之后的路径分流。
    chat / policy_query → 直接结束（前端处理回复）
    carbon_audit → 进入 supervisor 循环
    """
    intent = state.get("route_intent", "chat")
    if intent == "carbon_audit":
        return "supervisor"
    return END


def after_supervisor(state: dict) -> str:
    """
    Supervisor 决策后的路由。
    next → 跳到对应的 Agent
    done → 全部完成，结束
    error → 结束并报错
    pending_review → 进入人工审查
    """
    decision = state.get("supervisor_decision", "error")
    if decision == "next":
        next_agent = state.get("supervisor_next_agent", "")
        agent_route_map = {
            "data_cleansing": "data_cleansing",
            "policy_matcher": "policy_matcher",
            "calculator": "calculator",
            "compliance_audit": "compliance_audit",
            "report_writer": "report_writer",
        }
        return agent_route_map.get(next_agent, "data_cleansing")
    elif decision == "pending_review":
        return "human_review"
    else:
        # done 或 error → 结束
        return END


def after_agent(state: dict) -> str:
    """Agent 完成后回到 supervisor"""
    return "supervisor"


def after_review(state: dict) -> str:
    """
    人工审查后的路由。
    approved=True → 回到 supervisor（它会把 report_writer 推上场）
    approved=False → 结束
    """
    if state.get("approved"):
        return "supervisor"
    return END


# ========================================
# 人工审查节点 (HITL)
# ========================================

def human_review_node(state: dict) -> dict:
    """人工审查节点 — 看板所有计算完成后暂停等待审批"""
    emissions = state.get("emissions_result", {})

    review_summary = {
        "message": "⏸️ 看板工作流已暂停 — 所有专家 Agent 已完成工作，等待人工审查",
        "review_items": {
            "产品名称": state.get("product_name", "未知"),
            "HS Code": state.get("hs_code", "未知"),
            "CBAM/CCA 管控品类": state.get("cbam_category") or "非管控品类",
            "目标出口国": state.get("target_country", "EU"),
            "产品重量 (吨)": state.get("product_weight_tons", 0),
            "总碳排放量 (tCO2e)": state.get("total_emissions", 0),
            "  - Scope 1 直接排放": emissions.get("scope1_emissions", 0),
            "  - Scope 2 电力间接": emissions.get("scope2_emissions", 0),
            "  - Scope 3 物流运输": emissions.get("scope3_emissions", 0),
            "CBAM 基准值": state.get("benchmark_value"),
            "免费配额比例": state.get("free_allowance_rate"),
            "应纳税排放量 (tCO2e)": emissions.get("cbam_taxable_emissions", 0),
            "预估碳关税 (EUR)": emissions.get("cbam_estimated_tax", 0),
            "风险等级": state.get("risk_level", "未评估"),
        },
        "compliance_risk_preview": (state.get("compliance_risk") or "")[:500],
        "supervisor_reason": state.get("supervisor_reason", ""),
        "data_quality_warnings": state.get("data_quality_warnings", []),
        "instructions": (
            "请审查以上碳排放计算结果和合规风险分析。\n"
            "如确认无误, 请通过 Command(resume={'approved': True, 'feedback': '审查通过'}) 恢复执行。\n"
            "如需修改, 请通过 Command(resume={'approved': False, 'feedback': '修改说明'}) 终止流程。"
        ),
    }

    human_input = interrupt(review_summary)

    approved = human_input.get("approved", False)
    feedback = human_input.get("feedback", "")

    print(f"[Node: human_review] 人工审查结果: approved={approved}, feedback={feedback}")

    return {
        "approved": approved,
        "reviewer_feedback": feedback,
        "pending_review": False,
        "current_node": "human_review",
    }


# ========================================
# 构建看板+监督者 StateGraph
# ========================================

def build_graph(checkpointer=None) -> StateGraph:
    """
    构建碳合规审计 LangGraph 工作流 — 看板 + 监督者 复合编排。

    Args:
        checkpointer: LangGraph 检查点保存器 (SqliteSaver/PostgresSaver)

    Returns:
        编译后的 LangGraph 可执行图
    """
    workflow = StateGraph(AuditState)

    # === 添加节点 ===
    workflow.add_node("router", router_node)
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("data_cleansing", data_cleansing_node)
    workflow.add_node("policy_matcher", policy_matcher_node)
    workflow.add_node("calculator", calculator_node)
    workflow.add_node("compliance_audit", compliance_audit_node)
    workflow.add_node("human_review", human_review_node)
    workflow.add_node("report_writer", report_writer_node)

    # === 拓扑: START → router ===
    workflow.add_edge(START, "router")

    # === router 条件边 ===
    workflow.add_conditional_edges(
        "router",
        after_router,
        {
            "supervisor": "supervisor",
            END: END,
        },
    )

    # === supervisor 条件边 ===
    workflow.add_conditional_edges(
        "supervisor",
        after_supervisor,
        {
            "data_cleansing": "data_cleansing",
            "policy_matcher": "policy_matcher",
            "calculator": "calculator",
            "compliance_audit": "compliance_audit",
            "report_writer": "report_writer",
            "human_review": "human_review",
            END: END,
        },
    )

    # === 每个 Agent 完成后 → 回到 supervisor ===
    for agent in ["data_cleansing", "policy_matcher", "calculator", "compliance_audit", "report_writer"]:
        workflow.add_edge(agent, "supervisor")

    # === human_review 条件边 ===
    workflow.add_conditional_edges(
        "human_review",
        after_review,
        {
            "supervisor": "supervisor",
            END: END,
        },
    )

    # === 编译 ===
    if checkpointer:
        graph = workflow.compile(checkpointer=checkpointer)
    else:
        graph = workflow.compile()

    return graph


# ========================================
# 辅助函数 (保持 API 兼容)
# ========================================

def get_sqlite_saver(db_path: Optional[str] = None) -> SqliteSaver:
    """获取 SQLite 检查点保存器"""
    import sqlite3
    db_path = db_path or str(CHECKPOINT_DB_PATH)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    return SqliteSaver(conn)


def create_audit_graph(use_persistence: bool = True) -> StateGraph:
    """创建审计工作流图"""
    if use_persistence:
        return build_graph(checkpointer=get_sqlite_saver())
    return build_graph(checkpointer=None)


def start_audit(raw_payload: dict, target_country: str = "EU") -> tuple[str, dict]:
    """发起碳审计任务"""
    graph = create_audit_graph(use_persistence=True)
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print(f"[Workflow] 发起审计任务, thread_id={thread_id}")

    result = graph.invoke(
        {
            "raw_payload": raw_payload,
            "target_country": target_country,
            "approved": False,
            "pending_review": False,
            "retry_count": 0,
            "nodes_executed": [],
            "agent_errors": {},
            "data_quality_warnings": [],
        },
        config=config,
    )

    print(f"[Workflow] 当前节点: {result.get('current_node')}, "
          f"路由意图: {result.get('route_intent')}, "
          f"监督者决策: {result.get('supervisor_decision')}")
    return thread_id, result


def resume_audit(thread_id: str, approved: bool, feedback: str = "") -> dict:
    """恢复已暂停的审计任务"""
    graph = create_audit_graph(use_persistence=True)
    config = {"configurable": {"thread_id": thread_id}}

    print(f"[Workflow] 恢复审计任务, thread_id={thread_id}, approved={approved}")

    result = graph.invoke(
        Command(resume={"approved": approved, "feedback": feedback}),
        config=config,
    )

    if result.get("audit_report_md"):
        print(f"[Workflow] 审计报告已生成, 长度: {len(result['audit_report_md'])} 字符")
    else:
        print(f"[Workflow] 审计任务已结束 (未通过审查)")

    return result


def get_audit_status(thread_id: str) -> dict:
    """查询审计任务状态"""
    graph = create_audit_graph(use_persistence=True)
    config = {"configurable": {"thread_id": thread_id}}

    snapshot = graph.get_state(config)
    return {
        "thread_id": thread_id,
        "next_node": snapshot.next,
        "current_node": snapshot.values.get("current_node"),
        "pending_review": snapshot.values.get("pending_review", False),
        "route_intent": snapshot.values.get("route_intent"),
        "supervisor_decision": snapshot.values.get("supervisor_decision"),
        "retry_count": snapshot.values.get("retry_count"),
        "state": snapshot.values,
    }


# ========================================
# 主程序: 快速验证
# ========================================

if __name__ == "__main__":
    print("=" * 60)
    print("LangGraph 工作流 - 看板+监督者 连通性测试")
    print("=" * 60)

    graph = build_graph(checkpointer=None)

    # 测试1: 闲聊 → Router 拦截
    print("\n--- 测试1: 闲聊路由 ---")
    result = graph.invoke({
        "raw_payload": {"user_message": "你好，你会做什么？"},
        "target_country": "EU",
        "approved": False,
        "retry_count": 0,
    })
    print(f"意图: {result.get('route_intent')}, 理由: {result.get('route_reason')}")

    # 测试2: 碳审计 → 进入 supervisor 循环
    print("\n--- 测试2: 碳审计路由 ---")
    result = graph.invoke({
        "raw_payload": {
            "product_name": "铝合金型材",
            "hs_code": "7604",
            "weight_kg": 60000,
            "origin_port": "深圳",
            "destination_port": "汉堡",
            "transport_mode": "sea",
        },
        "target_country": "EU",
        "approved": False,
        "retry_count": 0,
    })
    print(f"意图: {result.get('route_intent')}")
    print(f"当前节点: {result.get('current_node')}")
    print(f"产品: {result.get('product_name')}")
    print(f"总排放: {result.get('total_emissions')}")
    print(f"风险等级: {result.get('risk_level')}")
    print(f"监督者决策: {result.get('supervisor_decision')}")

    print(f"\n{'=' * 60}")
    print("看板+监督者 工作流测试完成")
    print("=" * 60)
