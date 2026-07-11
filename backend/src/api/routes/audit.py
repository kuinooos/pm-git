"""
审计路由 - 发起审计、查询状态、人工审批
"""

import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import APIRouter, HTTPException, Depends
from langgraph.types import Command

from src.api.schemas import (
    AuditStartRequest, AuditStartResponse,
    AuditStatusResponse,
    AuditApproveRequest, AuditApproveResponse,
)
from src.domain.workflows.graph import create_audit_graph, get_audit_status
from src.infrastructure.auth import get_current_user

router = APIRouter(prefix="/api/v1/audit", tags=["审计"])


@router.post("/start", response_model=AuditStartResponse)
async def start_audit(
    request: AuditStartRequest,
    user: dict = Depends(get_current_user),
):
    """
    发起碳审计任务。
    接收 BOM/TMS 数据, 初始化 LangGraph 工作流并运行到人工审计节点前。
    返回 thread_id 供后续状态查询和审批使用。

    Requires auth: Bearer Token
    """
    try:
        # --- Celery 异步模式 ---
        if request.async_mode:
            from src.infrastructure.celery_tasks import run_audit_async
            task = run_audit_async.delay(
                raw_payload=request.bom_data,
                target_country=request.target_country,
                hs_code_hint=request.hs_code_hint,
            )
            return AuditStartResponse(
                task_id=task.id,
                status="pending",
                message=f"审计任务已提交 (Celery task_id={task.id})，请轮询状态查询结果。",
            )

        # --- 同步模式 (默认) ---
        raw_payload = request.bom_data.copy()
        if request.tms_data:
            raw_payload["tms_data"] = request.tms_data
        if request.hs_code_hint:
            raw_payload["hs_code_hint"] = request.hs_code_hint

        graph = create_audit_graph(use_persistence=True)
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        result = graph.invoke(
            {
                "raw_payload": raw_payload,
                "target_country": request.target_country,
                "approved": False,
                "pending_review": False,
                "retry_count": 0,
                "nodes_executed": [],
                "agent_errors": {},
                "data_quality_warnings": [],
            },
            config=config,
        )

        snapshot = graph.get_state(config)
        is_interrupted = len(snapshot.next) > 0

        if is_interrupted:
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

            return AuditStartResponse(
                thread_id=thread_id,
                status="pending_review",
                current_node=result.get("current_node", "human_review"),
                review_data=review_data,
                message="审计任务已运行至人工审查节点, 等待审批。",
            )
        else:
            return AuditStartResponse(
                thread_id=thread_id,
                status="completed",
                current_node=result.get("current_node", ""),
                message="审计任务已完成。",
            )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"审计任务启动失败: {str(e)}")


@router.get("/status/{thread_id}", response_model=AuditStatusResponse)
async def get_status(
    thread_id: str,
    user: dict = Depends(get_current_user),
):
    """
    获取审计任务的当前状态。
    Requires auth: Bearer Token
    """
    try:
        status = get_audit_status(thread_id)
        return AuditStatusResponse(
            thread_id=thread_id,
            current_node=status.get("current_node"),
            next_node=status.get("next_node"),
            pending_review=status.get("pending_review", False),
            state=status.get("state", {}),
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"未找到任务或查询失败: {str(e)}")


@router.post("/approve", response_model=AuditApproveResponse)
async def approve_audit(
    request: AuditApproveRequest,
    user: dict = Depends(get_current_user),
):
    """
    人工审批: 确认或驳回审计结果。
    approved=True → 工作流恢复, 生成最终报告。
    approved=False → 工作流终止。
    Requires auth: Bearer Token
    """
    try:
        graph = create_audit_graph(use_persistence=True)
        config = {"configurable": {"thread_id": request.thread_id}}

        resume_data = {
            "approved": request.approved,
            "feedback": request.feedback or "",
        }
        if request.modified_emissions is not None:
            resume_data["modified_emissions"] = request.modified_emissions

        result = graph.invoke(
            Command(resume=resume_data),
            config=config,
        )

        if request.approved and result.get("audit_report_md"):
            return AuditApproveResponse(
                thread_id=request.thread_id,
                status="completed",
                audit_report_md=result["audit_report_md"],
                message="审计任务已完成, 报告已生成。",
            )
        elif not request.approved:
            return AuditApproveResponse(
                thread_id=request.thread_id,
                status="rejected",
                message="审计任务已被驳回。",
            )
        else:
            return AuditApproveResponse(
                thread_id=request.thread_id,
                status="error",
                message="审计任务恢复后未生成报告。",
            )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"审批操作失败: {str(e)}")
