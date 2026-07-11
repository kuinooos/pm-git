"""
路由 Agent (Router Node)
分析用户输入意图，将请求分流到：闲聊 / 政策查询 / 碳审计。

这是看板复合编排的"前台分诊"层——Router + 看板 + 监督者 三合一的第一环。
"""

import json
import sys
from pathlib import Path
from typing import Literal

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

from config.settings import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TEMPERATURE


IntentType = Literal["chat", "policy_query", "carbon_audit"]

ROUTER_PROMPT = """你是碳合规审计系统的智能路由助手。分析用户输入，判断用户的真实意图。

## 意图分类

1. **chat** — 闲聊、问候、询问系统能力、帮助说明
   - 例如: "你好"、"你会做什么"、"能帮我做什么"、"介绍一下"

2. **policy_query** — 查询碳关税政策法规、CBAM/CCA 条款
   - 例如: "CBAM 对铝制品有什么要求"、"美国 CCA 和欧盟 CBAM 有什么区别"、"碳排放基准值是多少"

3. **carbon_audit** — 需要执行完整的碳排放计算和合规审计
   - 例如: "帮我算一下这批铝合金的碳排放"、"60吨钢材出口欧盟要做CBAM审计"、"HS Code 7604的产品碳关税"

## 判定规则

- 用户只是打招呼、问系统能力 → chat
- 用户在问政策是什么、条款怎么解读 → policy_query
- 用户在给具体数据（重量/HS Code/港口/出口国），要做计算审计 → carbon_audit
- 如果用户直接给出了产品+重量+HS Code等完整信息 → 一定走 carbon_audit
- 如果用户只问了政策问题 → policy_query
- 只有纯粹的问候/能力询问才走 chat

## 用户输入
{user_input}

## 请仅返回 JSON（不要输出其他任何内容）
```json
{{"intent": "chat|policy_query|carbon_audit", "reason": "简短判定理由"}}
```"""


def router_node(state: dict) -> dict:
    """
    路由节点: 判断用户意图，分流到不同处理路径。

    输入 state 字段:
        - raw_payload: 可能包含 'user_message' (Chainlit) 或完整 BOM 数据 (API)
        - target_country: 目标国

    输出:
        - route_intent: "chat" | "policy_query" | "carbon_audit"
        - route_reason: 判定理由
        - route_response: 如果是 chat，直接返回的回复文本
    """
    print("[Node: router] 开始意图路由分析...")

    raw = state.get("raw_payload", {})

    # 提取用户消息文本
    user_text = raw.get("user_message", "")
    if not user_text:
        # 可能是 API 直接提交的 BOM 数据
        if raw.get("product_name") and raw.get("hs_code"):
            print("[Node: router] 检测到完整 BOM 数据, 直接路由到 carbon_audit")
            return {
                "route_intent": "carbon_audit",
                "route_reason": "检测到完整 BOM 数据（含产品名和 HS Code）",
                "current_node": "router",
            }
        user_text = json.dumps(raw, ensure_ascii=False)

    # LLM 判断意图
    llm = ChatOpenAI(
        model=LLM_MODEL,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        temperature=0,
        max_tokens=256,
    )
    prompt = ChatPromptTemplate.from_template(ROUTER_PROMPT)
    chain = prompt | llm | StrOutputParser()

    try:
        response = chain.invoke({"user_input": user_text})

        json_str = response.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        result = json.loads(json_str)
        intent = result.get("intent", "chat")
        reason = result.get("reason", "")

    except Exception as e:
        print(f"[Node: router] LLM 路由判断失败, 降级为 chat: {e}")
        intent = "chat"
        reason = f"路由解析失败, 降级处理: {e}"

    print(f"[Node: router] 意图: {intent}, 理由: {reason}")

    return {
        "route_intent": intent,
        "route_reason": reason,
        "current_node": "router",
    }
