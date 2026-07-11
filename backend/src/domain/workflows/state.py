"""
审计工作流状态定义
定义 LangGraph StateGraph 中贯穿所有节点的状态结构体。

使用 total=False 允许部分字段缺失 (LangGraph 在各节点逐步填充状态)。

字段分组:
    路由 → 看板元信息 → 信息萃取 → 政策判定 → 物理计算 → 合规风控 → 人工审查 → 报告
"""

from typing import TypedDict, Dict, Any, Optional


class AuditState(TypedDict, total=False):
    """
    碳合规审计工作流状态 — 看板模式（Blackboard Pattern）。

    看板是所有 Agent 唯一的共享数据空间。
    Agent 只从看板读取、向看板写入，互不直接通信。
    """

    # ==================== 输入 ====================
    raw_payload: Dict[str, Any]            # 原始报关或物料数据 (BOM/TMS/提单)
    target_country: str                    # 目标出口国 (EU/US)

    # ==================== 路由层 ====================
    route_intent: str                      # Router 判定: "chat" | "policy_query" | "carbon_audit"
    route_reason: str                      # 路由判定理由
    route_response: str                    # 如果是 chat/policy_query，直接返回的文本

    # ==================== 信息萃取 Agent 产出 ====================
    clean_data: Dict[str, Any]             # 清洗后的标准结构
    hs_code: str                           # 判定得到的 HS Code
    product_name: str                      # 产品名称
    product_weight_tons: float             # 产品总重量 (吨)
    material_type: str                     # 材料类型 (如 aluminum_primary)
    origin_port: str                       # 源头港
    destination_port: str                  # 目的港
    transport_legs: list                   # 运输段列表
    electricity_mwh: float                 # 生产用电量 (MWh)
    fuel_consumptions: list                # 燃料消耗列表

    # ==================== 政策判定 Agent 产出 ====================
    policy_info: str                       # RAG 匹配出的税率与准则文本
    cbam_category: Optional[str]           # CBAM 管控品类 (aluminum/steel/cement/...)
    free_allowance_rate: Optional[float]   # 免费排放额度比例
    benchmark_value: Optional[float]       # 起征基准值

    # ==================== 物理计算 Agent 产出 ====================
    emissions_result: Dict[str, Any]       # Scope 1/2/3 分项计算结果
    total_emissions: float                 # 总碳排放量 (tCO2e)

    # ==================== 合规风控 Agent 产出 ====================
    compliance_risk: str                   # 合规风险分析文本
    risk_level: str                        # 风险等级 (low/medium/high)
    rectification_advice: str              # 整改建议

    # ==================== 人工审查 ====================
    approved: bool                         # 人工审核标志 (False=待审核, True=已通过)
    reviewer_feedback: Optional[str]       # 人工修改备注
    pending_review: bool                   # 是否正在挂起等待审核

    # ==================== 报告 ====================
    audit_report_md: str                   # 终版报告 Markdown 草案
    audit_report_pdf: Optional[str]        # PDF 文件路径

    # ==================== 看板元信息 (Supervisor 循环控制) ====================
    supervisor_decision: str               # "next" | "done" | "error" | "pending_review"
    supervisor_next_agent: str             # 下一个要调用的 Agent 名称
    supervisor_reason: str                 # 决策理由
    retry_count: int                       # 重试计数器
    data_quality_warnings: list            # 数据质量问题记录列表

    # ==================== 节点执行跟踪 ====================
    nodes_executed: list                   # 已执行节点列表 (避免重复执行)
    agent_errors: dict                     # 各 Agent 的错误记录 {"agent_name": "error_msg"}

    # ==================== 元信息 ====================
    thread_id: Optional[str]               # 会话线程 ID
    current_node: Optional[str]            # 当前节点名称 (用于状态查询)
    error: Optional[str]                   # 错误信息
