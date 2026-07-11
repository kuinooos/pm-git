# 全球碳关税（CBAM/CCA）合规审计多智能体系统

> 基于 **LangGraph + LangChain RAG + FastAPI + Chainlit** 构建的工业级碳合规审计多智能体系统。
> 采用 **Router 路由 + Blackboard 看板 + Supervisor 监督者** 复合多智能体编排架构。

## 🌟 项目简介

本系统针对出海制造企业、跨境物流企业和跨国供应链咨询机构，提供端到端的碳关税合规审计服务。系统能够自动完成从数据采集、政策匹配、碳排放计算到风险分析和报告生成的全流程审计工作，并在关键节点支持人工审查确认（Human-in-the-Loop）。

### 核心能力

| 能力 | 说明 |
|------|------|
| 🧭 **智能意图路由** | Router Agent 自动识别闲聊/政策查询/碳审计，非审计请求不启动工作流 |
| 🔍 **多源数据接入** | 支持 BOM（物料清单）、TMS（运输管理系统）、海运提单数据导入 |
| 📜 **智能 HS Code 判定** | RAG 混合检索 CBAM/CCA 法规库，自动判定管控品类 |
| 🧮 **分阶段多体协同审计** | Router → Supervisor 协调 5 个专家 Agent，动态调度非固定流水线 |
| ⏸️ **人工审查确认** | LangGraph HITL 机制，在生成报告前暂停等待人工审批 |
| 📝 **审计报告自动化** | 生成符合 ISO 14064 / CBAM 申报标准的 Markdown + PDF 报告 |

### 架构特色

| 特色 | 说明 |
|------|------|
| 🏗️ **复合多智能体编排** | Router（路由分诊）+ Blackboard（看板共享）+ Supervisor（监督者仲裁）三层复合 |
| 🔄 **动态监督者循环** | Supervisor 扫描看板状态，按需调度 Agent，非固定流水线 |
| 🔌 **优雅降级** | Redis 不可用时自动降级（缓存跳过、Celery 禁用），核心功能不受影响 |
| 🐳 **容器化就绪** | Docker Compose 一键部署，app/Redis/Celery/Chainlit 四种 profile |

## 🏗️ 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│            用户端 / 外部系统对接                               │
│       (Chainlit UI / 企业 ERP / TMS 系统)                     │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                   API 与业务网关层 (FastAPI)                   │
│  ┌────────────────────┐ ┌───────────────────┐ ┌────────────┐ │
│  │  Audit Controller  │ │   RAG Admin API   │ │Auth (JWT)  │ │
│  └────────────────────┘ └───────────────────┘ └────────────┘ │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│               多智能体工作流引擎 (LangGraph)                   │
│                                                              │
│  ┌──────────────────┐                                        │
│  │  🧭 Router Agent  │ ← 路由分诊（闲聊/查询/审计）           │
│  └────────┬─────────┘                                        │
│           │ carbon_audit                                     │
│           ▼                                                  │
│  ┌──────────────────┐                                        │
│  │ 👁️ Supervisor     │ ← 监督者：扫描看板，动态调度            │
│  └────────┬─────────┘                                        │
│           │                                                  │
│  ┌────────┼──────────────────────────┐                       │
│  ▼        ▼        ▼        ▼        ▼                       │
│ Data    Policy   Calc   Compliance Report                    │
│ Clean   Matcher  Emit   Audit      Writer                   │
│  │        │        │        │        │                       │
│  └────────┴────────┴────────┴────────┘                       │
│           │                                                  │
│           ▼                                                  │
│  ┌──────────────────┐                                        │
│  │ 👤 Human Review   │ ← 人工审查 (HITL)                      │
│  └──────────────────┘                                        │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                  知识库与基础设施层                            │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────┐ │
│  │ Milvus Lite      │ │ Carbon Factor DB │ │ Redis/SQLite │ │
│  │ (向量数据库)      │ │ (碳排放因子)      │ │ (缓存+持久化) │ │
│  └──────────────────┘ └──────────────────┘ └──────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

## 📁 项目结构

```
Project Root/
├── frontend/                          # Chainlit 对话 UI（前端）
│   ├── app.py                         # 主入口（Router + 工作流 + 审批回调）
│   ├── chainlit.md                    # 欢迎页
│   └── .chainlit/config.toml          # UI 配置
│
├── backend/                           # FastAPI + LangGraph 后端
│   ├── main.py                        # ⭐ 启动入口
│   ├── config/settings.py             # 全局配置
│   ├── src/
│   │   ├── api/                       # 接入层 (FastAPI)
│   │   │   ├── app.py                 # 应用工厂
│   │   │   ├── schemas.py             # Pydantic 模型
│   │   │   └── routes/                # 路由层
│   │   │       ├── auth.py            # /auth/token
│   │   │       ├── audit.py           # /audit/*
│   │   │       └── rag.py             # /rag/*
│   │   ├── domain/                    # 领域层（碳审计核心）
│   │   │   ├── calculator.py          # 碳排放计算引擎
│   │   │   ├── rag.py                 # RAG 混合检索引擎
│   │   │   ├── report_renderer.py     # Markdown → PDF
│   │   │   ├── agents/                # 智能体节点
│   │   │   │   ├── router.py          # 路由 Agent
│   │   │   │   ├── supervisor.py      # 监督者 Agent
│   │   │   │   ├── data_cleansing.py  # 信息萃取
│   │   │   │   ├── policy_matcher.py  # 政策判定
│   │   │   │   ├── calculator.py      # 排放计算
│   │   │   │   ├── compliance_audit.py # 合规风控
│   │   │   │   └── report_writer.py   # 报告生成
│   │   │   └── workflows/             # 工作流编排
│   │   │       ├── state.py           # AuditState（看板状态）
│   │   │       └── graph.py           # StateGraph（看板+监督者）
│   │   ├── data/                      # 数据访问层
│   │   │   └── database.py            # Milvus + JSON 管理
│   │   └── infrastructure/            # 基础设施层
│   │       ├── cache.py               # Redis 缓存 + 速率限制
│   │       ├── auth.py                # JWT 认证
│   │       ├── celery_app.py          # Celery 实例
│   │       └── celery_tasks.py        # 异步任务
│   ├── tests/                         # 测试
│   │   ├── test_calculator.py
│   │   ├── test_auth.py
│   │   └── test_cache.py
│   ├── data/                          # 数据文件
│   │   ├── carbon_db.json             # 碳排放因子数据库
│   │   ├── hs_code_mapping.json       # HS Code 映射表
│   │   ├── raw_documents/             # RAG 知识库文档
│   │   └── reports/                   # 审计报告输出
│   ├── requirements.txt
│   ├── .env.example
│   ├── Dockerfile
│   └── docker-compose.yml
│
├── docs/                              # 项目文档
│   ├── 需求文档.md
│   ├── 项目实现计划.md
│   ├── 启动与运维指南.md
│   ├── 技术说明文档.md
│   └── 测试手册.md
│
├── README.md
└── .gitignore
```

## 🚀 快速开始

### 1. 环境准备

```bash
# 安装依赖
cd backend
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cd backend
cp .env.example .env
# 编辑 .env, 填入你的 API Key
# LONGCAT_API_KEY=your_api_key_here
```

### 3. 初始化 RAG 知识库

```bash
cd backend
python -m src.domain.rag
```

### 4. 启动方式

#### 方式一：Chainlit 交互界面（推荐，从项目根目录运行）

```bash
chainlit run frontend/app.py -w
```

访问 http://localhost:8000 即可使用。

#### 方式二：FastAPI REST API

```bash
cd backend
uvicorn src.api.app:app --host 0.0.0.0 --port 8008 --reload
# 或
python main.py
```

访问 http://localhost:8008/docs 查看 API 文档。

### 5. 使用示例

在 Chainlit 界面输入：

> 我们有 60 吨铝合金型材, HS Code 7604, 要从深圳海运到德国汉堡, 生产用电 1200 MWh。请做 EU CBAM 合规审计。

系统将自动执行：
1. 🧭 **Router 路由** → 识别为"碳审计"意图
2. 🔍 **信息萃取** → 提取产品、重量、路线等结构化数据
3. 📜 **政策判定** → RAG 检索 CBAM 铝制品政策，判定管控品类
4. 🧮 **排放计算** → 计算 Scope 1/2/3 碳排放
5. ⚖️ **合规风控** → 对标基准值，分析风险
6. ⏸️ **暂停等待人工审查** → 您确认后继续
7. 📝 **报告生成** → 生成审计报告并导出 PDF

> 💡 **非审计请求处理**：
> - 输入"你好" → Router 识别为闲聊，直接回复，不启动工作流
> - 输入"CBAM 铝制品关税是什么" → Router 识别为政策查询，单步 RAG 返回

## 🔧 API 接口

| 端点 | 方法 | 认证 | 说明 |
|------|------|------|------|
| `/` | GET | - | 健康检查 |
| `/api/v1/health` | GET | - | 健康检查 |
| `/api/v1/auth/token` | POST | 用户名+密码 | 登录获取 JWT |
| `/api/v1/audit/start` | POST | Bearer Token | 发起审计任务 |
| `/api/v1/audit/status/{thread_id}` | GET | Bearer Token | 查询审计状态 |
| `/api/v1/audit/approve` | POST | Bearer Token | 人工审批 |
| `/api/v1/rag/upload` | POST | Bearer Token | 上传政策文档 |
| `/api/v1/rag/search` | POST | - | 检索政策知识库 |

### 默认账户

| 用户名 | 密码 | 角色 |
|--------|------|------|
| `admin` | `admin123` | 管理员 |
| `auditor` | `audit456` | 审计员 |

## 🛠️ 技术栈

| 技术 | 用途 |
|------|------|
| **LangGraph** ≥0.2.39 | 多智能体编排 (Router + Supervisor + HITL) |
| **LangChain** ≥0.3.0 | RAG 文档加载、切分、检索 |
| **Milvus Lite** ≥2.4.0 | 向量数据库（本地运行） |
| **BGE Embeddings** | 中英双语政策文档向量化 |
| **BGE-Reranker** | 检索结果重排序 |
| **FastAPI** ≥0.110.0 | 异步 REST API + JWT 认证 |
| **Chainlit** ≥2.11.0 | 对话式 AI 交互界面 |
| **Redis** 7.x | RAG 缓存 + Celery Broker + 速率限制 |
| **Celery** ≥5.3.0 | 异步审计任务队列 |
| **PyJWT** ≥2.8.0 | JWT Bearer Token 认证 |
| **fpdf2** | PDF 报告渲染 |
| **LongCat-2.0** | LLM 推理模型（OpenAI 兼容接口） |

## 📊 碳排放计算范围

| Scope | 说明 | 计算方法 |
|-------|------|----------|
| **Scope 1** | 直接排放（燃料燃烧 + 工艺排放） | 活动数据 × 排放因子 |
| **Scope 2** | 外购电力间接排放 | 用电量 × 电网排放因子 |
| **Scope 3** | 物流运输排放 | 重量 × 距离 × 运输排放因子 |

## 📜 License

MIT License
