"""
领域层 - 碳排放计算、RAG 检索、报告渲染等核心业务逻辑
"""

from src.domain.calculator import (
    CarbonCalculator,
    TransportLeg,
    EnergyConsumption,
    MaterialInput,
    EmissionsResult,
    get_calculator,
    calculate_transport_emissions,
)

from src.domain.rag import (
    CarbonPolicyRAG,
    get_rag_engine,
    rag_search,
)

from src.domain.report_renderer import (
    ReportRenderer,
    get_renderer,
    render_report,
)
