"""
Chainlit 主入口 - 全球碳关税合规审计多智能体系统
基于 LangGraph 看板+监督者 复合编排架构驱动。

启动方式:
    chainlit run frontend/app.py -w
"""

import os
import sys
import json
import uuid
import asyncio
from pathlib import Path

# 将 backend/ 加入 sys.path
BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

import chainlit as cl
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from langgraph.types import Command

from config.settings import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TEMPERATURE
from src.domain.workflows.graph import create_audit_graph
from src.domain.rag import get_rag_engine
from src.domain.report_renderer import render_report


# ========================================
# LLM 辅助: 闲聊回复 & 路由解析
# ========================================

CHAT_RESPONSE_PROMPT = """你是一个专业的全球碳关税合规审计助手。请友好回答用户的问题。

系统能力:
- 欧盟 CBAM 和美国 CCA 碳关税合规审计
- 碳排放计算 (Scope 1/2/3)
- CBAM/CCA 政策法规检索与解读
- 6 个智能 Agent 协同工作（Router 路由 → Supervisor 监督 → 4 个专家 Agent）
- 支持 BOM/TMS 数据导入和审计报告 PDF 导出

用户输入: {user_input}

请简短友好地回复，介绍你能帮用户做什么。"""


PARSE_PROMPT = """你是一个跨境贸易数据解析专家。请从用户的自然语言描述中提取碳审计所需的结构化数据。

用户输入:
{user_input}

请严格按照以下 JSON 格式输出 (不要输出其他任何内容):
```json
{{
    "product_name": "产品名称",
    "hs_code": "HS海关编码(6位数字, 如不确定请根据产品推断)",
    "weight_kg": 0,
    "material": "材料(如 铝/钢/水泥/化肥/氢气)",
    "origin_port": "出发港口",
    "destination_port": "目的港口",
    "transport_mode": "sea/rail/road/air",
    "target_country": "EU 或 US",
    "remark": "其他备注信息"
}}
```

注意:
1. 重量统一换算为千克 (kg)
2. 如果用户未明确目标国家, 默认为 EU
3. 如果用户未明确运输方式, 根据航线推断 (跨国海运默认 sea)
"""


async def generation_chat_response(user_text: str) -> str:
    """Router 判定为 chat 时，生成友好的闲聊回复"""
    llm = ChatOpenAI(
        model=LLM_MODEL,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        temperature=0.7,
        max_tokens=512,
    )
    prompt = ChatPromptTemplate.from_template(CHAT_RESPONSE_PROMPT)
    chain = prompt | llm | StrOutputParser()
    return await asyncio.to_thread(chain.invoke, {"user_input": user_text})


async def route_user_intent(user_text: str) -> dict:
    """
    调用 Router LLM 判断用户意图。
    返回: {"intent": "chat|policy_query|carbon_audit", "reason": "..."}
    """
    from src.domain.agents.router import ROUTER_PROMPT

    llm = ChatOpenAI(
        model=LLM_MODEL,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        temperature=0,
        max_tokens=256,
    )
    prompt = ChatPromptTemplate.from_template(ROUTER_PROMPT)
    chain = prompt | llm | StrOutputParser()

    response = await asyncio.to_thread(chain.invoke, {"user_input": user_text})

    json_str = response.strip()
    if "```json" in json_str:
        json_str = json_str.split("```json")[1].split("```")[0].strip()
    elif "```" in json_str:
        json_str = json_str.split("```")[1].split("```")[0].strip()

    return json.loads(json_str)


async def parse_user_input(user_text: str) -> dict:
    """使用 LLM 将自然语言解析为结构化 BOM 数据"""
    llm = ChatOpenAI(
        model=LLM_MODEL,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        temperature=0,
        max_tokens=512,
    )
    prompt = ChatPromptTemplate.from_template(PARSE_PROMPT)
    chain = prompt | llm | StrOutputParser()

    response = await asyncio.to_thread(chain.invoke, {"user_input": user_text})

    json_str = response.strip()
    if "```json" in json_str:
        json_str = json_str.split("```json")[1].split("```")[0].strip()
    elif "```" in json_str:
        json_str = json_str.split("```")[1].split("```")[0].strip()

    return json.loads(json_str)


# ========================================
# 格式化辅助函数
# ========================================

def format_review_summary(state: dict) -> str:
    """格式化人工审查摘要"""
    emissions = state.get("emissions_result", {})
    lines = [
        "## ⏸️ 看板状态: 所有专家 Agent 已完成 — 等待人工审查\n",
        f"**产品名称**: {state.get('product_name', '未知')}",
        f"**HS Code**: {state.get('hs_code', '未知')}",
        f"**CBAM/CCA 管控品类**: {state.get('cbam_category') or '非管控品类'}",
        f"**目标出口国**: {state.get('target_country', 'EU')}",
        f"**产品重量**: {state.get('product_weight_tons', 0)} 吨\n",
        "### 碳排放核算结果",
        f"- Scope 1 (直接排放): **{emissions.get('scope1_emissions', 0):.4f} tCO2e**",
        f"- Scope 2 (电力间接): **{emissions.get('scope2_emissions', 0):.4f} tCO2e**",
        f"- Scope 3 (物流运输): **{emissions.get('scope3_emissions', 0):.4f} tCO2e**",
        f"- **总碳排放量: {state.get('total_emissions', 0):.4f} tCO2e**\n",
        "### CBAM 合规分析",
        f"- 管控品类基准值: {state.get('benchmark_value') or '无'} tCO2e/吨",
        f"- 免费配额比例: {state.get('free_allowance_rate', 0):.1%}" if state.get('free_allowance_rate') else "- 免费配额比例: 无",
        f"- 应纳税排放量: **{emissions.get('cbam_taxable_emissions', 0):.4f} tCO2e**",
        f"- 预估碳关税: **EUR {emissions.get('cbam_estimated_tax', 0):.2f}**",
        f"- 风险等级: **{state.get('risk_level', '未评估')}**\n",
        "### 监督者 (Supervisor) 决策",
        f"_{state.get('supervisor_reason', '无')}_\n",
    ]

    warnings = state.get("data_quality_warnings", [])
    if warnings:
        lines.append("### ⚠️ 数据质量提示")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.extend([
        "### 合规风险分析预览",
        f"{(state.get('compliance_risk') or '')[:300]}...\n",
        "---\n",
        "请审查以上数据。点击 **✅ 通过审查** 继续生成报告, 或点击 **❌ 驳回** 终止流程。",
    ])
    return "\n".join(lines)


def format_workflow_progress(state: dict) -> str:
    """格式化工作流进度摘要"""
    lines = [
        f"### 📊 看板工作流执行完成\n",
        f"**产品**: {state.get('product_name', '未知')}",
        f"**HS Code**: {state.get('hs_code', '未知')}",
        f"**CBAM 品类**: {state.get('cbam_category') or '非管控'}",
        f"**总碳排放**: {state.get('total_emissions', 0):.4f} tCO2e",
        f"**风险等级**: {state.get('risk_level', '未评估')}",
    ]
    return "\n".join(lines)


# ========================================
# Chainlit 事件处理
# ========================================

@cl.on_chat_start
async def on_chat_start():
    """会话初始化"""
    cl.user_session.set("thread_id", None)
    cl.user_session.set("graph", None)

    await cl.Message(
        content="🌿 **全球碳关税合规审计多智能体系统** 已启动。\n\n"
                "本系统基于 **看板 + 监督者** 复合编排架构运行:\n"
                "- 🧭 **Router Agent** — 智能识别您的意图（闲聊/政策查询/碳审计）\n"
                "- 👁️ **Supervisor Agent** — 监督者协调各专家团队\n"
                "- 🔍 **信息萃取 Agent** — 提取结构化报关数据\n"
                "- 📜 **政策判定 Agent** — RAG 检索 CBAM/CCA 政策\n"
                "- 🧮 **物理计算 Agent** — Scope 1/2/3 碳排放计算\n"
                "- ⚖️ **合规风控 Agent** — 对标基准值风险分析\n"
                "- 📝 **报告生成 Agent** — 生成审计报告 PDF\n\n"
                "系统会在完成计算后 **暂停等待人工审查**, 您确认后才会生成最终报告。\n\n"
                "---\n\n"
                "**你可以:**\n"
                "- 🗣️ 跟我聊聊，了解系统能力\n"
                "- 📚 查询 CBAM/CCA 政策（如“铝制品关税怎么算”）\n"
                "- 📊 提交产品数据开始碳审计\n\n"
                "**碳审计示例:**\n"
                "> 我们有 60 吨铝合金型材, HS Code 7604, 要从深圳海运到德国汉堡, "
                "生产用电 1200 MWh。请帮我做欧盟 CBAM 合规审计。"
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    """处理用户消息 — 路由 → 闲聊/政策查询/审计工作流"""
    thread_id = cl.user_session.get("thread_id")

    # 如果已有活跃工作流, 提示用户审批
    if thread_id:
        await cl.Message(
            content="ℹ️ 您的审计任务正在处理中。请使用上方的按钮进行审批操作。"
                    "如需发起新的审计任务, 请输入 **新任务**。"
        ).send()
        if "新任务" in message.content or "new" in message.content.lower():
            cl.user_session.set("thread_id", None)
            cl.user_session.set("graph", None)
            await cl.Message(content="✅ 已重置。请描述您的新审计需求。").send()
        return

    user_text = message.content

    try:
        # === Step 1: Router 意图识别 ===
        async with cl.Step(name="🧭 Router 意图识别", type="run") as step:
            step.input = user_text
            await step.update()

            route_result = await route_user_intent(user_text)
            intent = route_result.get("intent", "chat")
            reason = route_result.get("reason", "")

            step.output = f"意图: **{intent}**\n理由: {reason}"
            await step.update()

        # === 路径 A: 闲聊 ===
        if intent == "chat":
            async with cl.Step(name="💬 助手回复", type="run") as step:
                response = await generation_chat_response(user_text)
                step.output = response
                await step.update()
            await cl.Message(content=response).send()
            return

        # === 路径 B: 政策查询 ===
        if intent == "policy_query":
            async with cl.Step(name="📚 RAG 政策检索", type="run") as step:
                step.input = user_text
                await step.update()

                engine = get_rag_engine()
                context = engine.search_as_context(user_text, top_k=5)

                step.output = "已检索到相关政策信息"
                await step.update()

            await cl.Message(
                content=f"## 📚 碳关税政策检索结果\n\n{context[:3000]}"
            ).send()
            return

        # === 路径 C: 碳审计 (看板 + 监督者工作流) ===
        async with cl.Step(name="🔍 解析审计数据", type="run") as step:
            step.input = user_text
            await step.update()

            bom_data = await parse_user_input(user_text)
            step.output = f"```json\n{json.dumps(bom_data, ensure_ascii=False, indent=2)}\n```"
            await step.update()

        # 启动看板工作流
        async with cl.Step(name="⚙️ 看板+监督者 工作流", type="run") as step:
            step.input = "正在初始化看板 (Blackboard) + 监督者 (Supervisor) ..."
            await step.update()

            graph = create_audit_graph(use_persistence=True)
            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id}}
            cl.user_session.set("thread_id", thread_id)
            cl.user_session.set("graph", graph)
            cl.user_session.set("config", config)

            raw_payload = bom_data.copy()
            if "target_country" not in raw_payload:
                raw_payload["target_country"] = "EU"

            step.output = f"Thread ID: {thread_id}\n工作模式: 看板 + 监督者循环"
            await step.update()

            # 运行看板工作流
            result = await asyncio.to_thread(
                graph.invoke,
                {
                    "raw_payload": raw_payload,
                    "target_country": raw_payload.get("target_country", "EU"),
                    "approved": False,
                    "pending_review": False,
                    "retry_count": 0,
                    "nodes_executed": [],
                    "agent_errors": {},
                    "data_quality_warnings": [],
                },
                config,
            )

        # 展示各 Agent 执行结果
        async with cl.Step(name="🔍 信息萃取 Agent", type="run") as step:
            step.output = (
                f"产品: {result.get('product_name', '未知')}\n"
                f"HS Code: {result.get('hs_code', '未知')}\n"
                f"材料类型: {result.get('material_type', 'unknown')}\n"
                f"重量: {result.get('product_weight_tons', 0)} 吨\n"
                f"路线: {result.get('origin_port', '')} → {result.get('destination_port', '')}\n"
                f"运输段数: {len(result.get('transport_legs', []))}\n"
                f"电力消耗: {result.get('electricity_mwh', 0)} MWh"
            )
            await step.update()

        async with cl.Step(name="📜 政策判定 Agent (RAG)", type="run") as step:
            step.output = (
                f"CBAM 管控品类: {result.get('cbam_category') or '非管控品类'}\n"
                f"基准值: {result.get('benchmark_value') or '无'}\n"
                f"免费配额: {result.get('free_allowance_rate', 0):.1%}" if result.get('free_allowance_rate') else ""
            )
            await step.update()

        async with cl.Step(name="🧮 排放计算 Agent", type="run") as step:
            emissions = result.get("emissions_result", {})
            step.output = (
                f"Scope 1: {emissions.get('scope1_emissions', 0):.4f} tCO2e\n"
                f"Scope 2: {emissions.get('scope2_emissions', 0):.4f} tCO2e\n"
                f"Scope 3: {emissions.get('scope3_emissions', 0):.4f} tCO2e\n"
                f"总计: {result.get('total_emissions', 0):.4f} tCO2e\n"
                f"应纳税排放: {emissions.get('cbam_taxable_emissions', 0):.4f} tCO2e\n"
                f"预估碳关税: EUR {emissions.get('cbam_estimated_tax', 0):.2f}"
            )
            await step.update()

        async with cl.Step(name="⚖️ 合规风控 Agent", type="run") as step:
            step.output = (
                f"风险等级: {result.get('risk_level', '未评估')}\n\n"
                f"{(result.get('compliance_risk') or '无分析')[:500]}"
            )
            await step.update()

        # 检查是否在 human_review 暂停
        snapshot = graph.get_state(config)
        is_interrupted = len(snapshot.next) > 0

        if is_interrupted:
            review_text = format_review_summary(result)
            msg = cl.Message(content=review_text, actions=[
                cl.Action(
                    name="approve",
                    payload={"action": "approve", "thread_id": thread_id},
                    label="✅ 通过审查",
                    style="primary",
                ),
                cl.Action(
                    name="reject",
                    payload={"action": "reject", "thread_id": thread_id},
                    label="❌ 驳回",
                    style="danger",
                ),
            ])
            await msg.send()
        else:
            await cl.Message(content=format_workflow_progress(result)).send()
            if result.get("audit_report_md"):
                await show_report(result["audit_report_md"])

    except json.JSONDecodeError as e:
        await cl.Message(
            content=f"❌ 数据解析失败: {e}\n请尝试用更清晰的格式描述您的需求。"
        ).send()
    except Exception as e:
        import traceback
        traceback.print_exc()
        await cl.Message(
            content=f"❌ 工作流执行出错: {str(e)}\n\n请重试或检查系统配置。"
        ).send()


# ========================================
# 审批回调
# ========================================

@cl.action_callback("approve")
async def on_approve(action):
    """用户点击「通过审查」"""
    thread_id = action.payload.get("thread_id")
    config = {"configurable": {"thread_id": thread_id}}
    graph = cl.user_session.get("graph")

    if not graph:
        await cl.Message(content="❌ 未找到活跃的工作流会话。").send()
        return

    await cl.Message(content="✅ 审查已通过, 正在生成审计报告...").send()

    try:
        result = await asyncio.to_thread(
            graph.invoke,
            Command(resume={"approved": True, "feedback": "审查通过"}),
            config,
        )

        if result.get("audit_report_md"):
            await show_report(result["audit_report_md"])
        else:
            await cl.Message(content="⚠️ 报告生成失败, 请检查日志。").send()

    except Exception as e:
        import traceback
        traceback.print_exc()
        await cl.Message(content=f"❌ 恢复工作流失败: {str(e)}").send()


@cl.action_callback("reject")
async def on_reject(action):
    """用户点击「驳回」"""
    thread_id = action.payload.get("thread_id")
    config = {"configurable": {"thread_id": thread_id}}
    graph = cl.user_session.get("graph")

    if not graph:
        await cl.Message(content="❌ 未找到活跃的工作流会话。").send()
        return

    try:
        await asyncio.to_thread(
            graph.invoke,
            Command(resume={"approved": False, "feedback": "审查未通过"}),
            config,
        )

        await cl.Message(
            content="❌ 审计任务已驳回。工作流已终止。\n\n如需发起新的审计任务, 请直接描述您的需求。"
        ).send()

        cl.user_session.set("thread_id", None)
        cl.user_session.set("graph", None)

    except Exception as e:
        await cl.Message(content=f"❌ 操作失败: {str(e)}").send()


async def show_report(report_md: str):
    """展示审计报告并提供 PDF 下载"""
    await cl.Message(
        content=f"## 📝 碳合规审计报告已生成\n\n{report_md[:3000]}\n\n"
                f"*(报告全文已保存, 点击下方按钮下载 PDF 版本)*"
    ).send()

    try:
        pdf_path = await asyncio.to_thread(render_report, report_md)
        pdf_element = cl.File(
            name=os.path.basename(pdf_path),
            path=pdf_path,
            display="inline",
        )
        await cl.Message(
            content="📄 **PDF 报告下载**:",
            elements=[pdf_element],
        ).send()
    except Exception as e:
        await cl.Message(content=f"⚠️ PDF 生成失败: {e}\n\nMarkdown 报告已在上文展示。").send()
