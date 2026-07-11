"""
基础设施层 - Celery 异步任务定义
将 LangGraph 审计工作流包装为 Celery 异步任务。
"""

from typing import Any

from src.infrastructure.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def run_audit_async(
    self,
    raw_payload: dict,
    target_country: str = "EU",
    hs_code_hint: str | None = None,
) -> dict[str, Any]:
    """
    异步执行碳审计工作流。

    该任务包装了 LangGraph 的 graph.invoke() 调用，
    工作流会运行到 human_review 节点并暂停。

    Args:
        raw_payload: 原始报关/物料数据
        target_country: 目标出口国 (EU/US)
        hs_code_hint: HS Code 提示 (可选)

    Returns:
        包含 thread_id 和暂停时状态的字典
    """
    import uuid
    from src.domain.workflows.graph import create_audit_graph

    try:
        graph = create_audit_graph(use_persistence=True)
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        if hs_code_hint:
            raw_payload["hs_code_hint"] = hs_code_hint

        result = graph.invoke(
            {
                "raw_payload": raw_payload,
                "target_country": target_country,
                "approved": False,
                "pending_review": False,
            },
            config=config,
        )

        emissions = result.get("emissions_result", {})
        review_data = {
            "product_name": result.get("product_name", ""),
            "hs_code": result.get("hs_code", ""),
            "cbam_category": result.get("cbam_category"),
            "total_emissions": result.get("total_emissions", 0),
            "scope1_emissions": emissions.get("scope1_emissions", 0),
            "scope2_emissions": emissions.get("scope2_emissions", 0),
            "scope3_emissions": emissions.get("scope3_emissions", 0),
            "risk_level": result.get("risk_level", ""),
            "cbam_taxable_emissions": emissions.get("cbam_taxable_emissions", 0),
            "cbam_estimated_tax": emissions.get("cbam_estimated_tax", 0),
            "compliance_risk": (result.get("compliance_risk") or "")[:500],
        }

        return {
            "thread_id": thread_id,
            "status": "pending_review",
            "current_node": result.get("current_node", "human_review"),
            "review_data": review_data,
        }

    except Exception as exc:
        self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def resume_audit_async(
    self,
    thread_id: str,
    approved: bool,
    feedback: str = "",
) -> dict[str, Any]:
    """
    异步恢复已暂停的审计工作流。

    Args:
        thread_id: 会话线程 ID
        approved: 是否通过审查
        feedback: 审查备注

    Returns:
        最终状态 (包含审计报告)
    """
    from langgraph.types import Command
    from src.domain.workflows.graph import create_audit_graph

    try:
        graph = create_audit_graph(use_persistence=True)
        config = {"configurable": {"thread_id": thread_id}}

        result = graph.invoke(
            Command(resume={"approved": approved, "feedback": feedback}),
            config=config,
        )

        return {
            "thread_id": thread_id,
            "status": "completed" if approved else "rejected",
            "audit_report_md": result.get("audit_report_md") if approved else None,
        }

    except Exception as exc:
        self.retry(exc=exc)


def get_task_result(task_id: str) -> dict | None:
    """
    查询 Celery 异步任务结果。

    Args:
        task_id: Celery task ID

    Returns:
        任务结果字典，或 None (未完成/不存在)
    """
    from celery.result import AsyncResult
    result = AsyncResult(task_id, app=celery_app)
    if result.ready():
        return result.result if result.successful() else {"status": "error", "detail": str(result.info)}
    return {"status": result.state, "task_id": task_id}
