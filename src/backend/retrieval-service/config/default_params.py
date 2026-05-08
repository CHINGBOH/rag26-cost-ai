"""
默认参数注册 - 注册所有现有硬编码参数

在启动时调用 register_default_params() 来注册所有参数。
"""

from config.param_registry import ParamRegistry, ParamCategory


def register_default_params():
    """注册所有默认参数到参数注册表"""
    
    # ========================================================================
    # Followup 相关参数
    # ========================================================================
    
    # Phase 1 #116: Simplified followup coverage parameter names
    ParamRegistry.register(
        name="followup_coverage_high",
        value=0.65,
        rationale="A/B test 2024-Q1 showed 0.65 threshold achieved 75% answerability, "
                  "while 0.45 only achieved 45%. Raised from 0.45 to reduce unanswerable suggestions.",
        category=ParamCategory.FOLLOWUP,
        source="app/agent/graph.py _coverage_tier()",
        unit="score",
        min_value=0.5,
        max_value=0.9
    )
    
    ParamRegistry.register(
        name="followup_coverage_med",
        value=0.50,
        rationale="Medium tier raised from 0.45 to 0.50 to ensure minimum answerability. "
                  "Questions below 0.50 rarely have satisfactory answers.",
        category=ParamCategory.FOLLOWUP,
        source="app/agent/graph.py _coverage_tier()",
        unit="score",
        min_value=0.4,
        max_value=0.65
    )
    
    ParamRegistry.register(
        name="followup_coverage_threshold_high",
        value=0.65,
        rationale="A/B test 2024-Q1 showed 0.65 threshold achieved 75% answerability, "
                  "while 0.45 only achieved 45%. Raised from 0.45 to reduce unanswerable suggestions.",
        category=ParamCategory.FOLLOWUP,
        source="app/agent/graph.py:3799",
        unit="score",
        min_value=0.5,
        max_value=0.9
    )
    
    ParamRegistry.register(
        name="followup_coverage_threshold_med",
        value=0.50,
        rationale="Medium tier raised from 0.45 to 0.50 to ensure minimum answerability. "
                  "Questions below 0.50 rarely have satisfactory answers.",
        category=ParamCategory.FOLLOWUP,
        source="app/agent/graph.py:3801",
        unit="score",
        min_value=0.4,
        max_value=0.65
    )
    
    ParamRegistry.register(
        name="followup_min_high_tier_count",
        value=1,
        rationale="Changed from forcing 2 low-tier suggestions to requiring 1 high-tier minimum. "
                  "Prefer quality over quantity.",
        category=ParamCategory.FOLLOWUP,
        source="app/agent/graph.py:3897",
        unit="count",
        min_value=0,
        max_value=3
    )
    
    ParamRegistry.register(
        name="followup_max_suggestions",
        value=5,
        rationale="Standard UI constraint - more than 5 chips clutter the interface.",
        category=ParamCategory.FOLLOWUP,
        source="app/agent/graph.py:3806",
        unit="count",
        min_value=3,
        max_value=8
    )
    
    ParamRegistry.register(
        name="followup_graph_max_neighbors",
        value=8,
        rationale="Balance between diversity and noise. More than 8 neighbors rarely add value.",
        category=ParamCategory.FOLLOWUP,
        source="app/agent/graph.py:3839",
        unit="count",
        min_value=5,
        max_value=15
    )
    
    # ========================================================================
    # Learning 相关参数
    # ========================================================================
    
    ParamRegistry.register(
        name="learning_retest_interval_default",
        value=24,
        rationale="Daily retest interval for knowledge gap monitoring. "
                  "Shorter intervals waste resources, longer delays feedback too much.",
        category=ParamCategory.LEARNING,
        source="app/agent/learning_listener.py:89",
        unit="hours",
        min_value=6,
        max_value=72
    )
    
    ParamRegistry.register(
        name="learning_retest_backoff_multiplier",
        value=2.0,
        rationale="Exponential backoff for persistent gaps. "
                  "If gap still exists after retest, wait 2x longer next time.",
        category=ParamCategory.LEARNING,
        source="app/agent/learning_listener.py:92",
        unit="multiplier",
        min_value=1.5,
        max_value=3.0
    )
    
    ParamRegistry.register(
        name="learning_retest_max_interval",
        value=168,
        rationale="Max 7 days between retests. Prevents abandoning persistent gaps.",
        category=ParamCategory.LEARNING,
        source="app/agent/learning_listener.py:95",
        unit="hours",
        min_value=72,
        max_value=336
    )
    
    ParamRegistry.register(
        name="learning_timer_interval",
        value=5,
        rationale="Background learning timer checks every 5 minutes. "
                  "More frequent checks waste CPU, less frequent delays response.",
        category=ParamCategory.LEARNING,
        source="app/agent/learning_listener.py:52",
        unit="minutes",
        min_value=1,
        max_value=15
    )
    
    ParamRegistry.register(
        name="learning_gap_whitelist_enabled",
        value=False,
        rationale="Whitelist feature not yet implemented. Will filter low-coverage followups.",
        category=ParamCategory.LEARNING,
        source="app/agent/learning_listener.py:156",
        deprecated=False
    )
    
    # ========================================================================
    # Contract 相关参数
    # ========================================================================
    
    # Phase 1 #116: New contract parameter for graph.py
    ParamRegistry.register(
        name="contract_max_outer_iterations",
        value=3,
        rationale="Max outer iterations before forcing convergence. "
                  "3 iterations balance quality improvement vs latency.",
        category=ParamCategory.CONTRACT,
        source="app/agent/graph.py contract_verifier_node()",
        unit="count",
        min_value=1,
        max_value=10
    )
    
    ParamRegistry.register(
        name="contract_max_iterations",
        value=3,
        rationale="Hardcoded limit. Should be adaptive based on violation severity. "
                  "Current implementation stops at 3 even if contract still violated.",
        category=ParamCategory.CONTRACT,
        source="app/agent/contract.py:78",
        unit="count",
        min_value=1,
        max_value=10,
        deprecated=True,
        replacement="contract_adaptive_iterations"
    )
    
    ParamRegistry.register(
        name="contract_adaptive_iterations",
        value=True,
        rationale="Feature flag to enable adaptive iteration limit based on violation severity.",
        category=ParamCategory.CONTRACT,
        source="config/default_params.py:128"
    )
    
    # ========================================================================
    # Evaluation 相关参数
    # ========================================================================
    
    ParamRegistry.register(
        name="evaluation_chunk_bonus",
        value=0.15,
        rationale="Bonus score for having chunks. Should be removed - "
                  "chunks don't guarantee answer quality.",
        category=ParamCategory.EVALUATION,
        source="app/agent/evaluation.py:123",
        unit="score",
        min_value=0.0,
        max_value=0.3,
        deprecated=True
    )
    
    ParamRegistry.register(
        name="evaluation_confidence_weight",
        value=0.7,
        rationale="LLM self-assessment weight. Should be reduced - "
                  "LLMs over-estimate their confidence.",
        category=ParamCategory.EVALUATION,
        source="app/agent/evaluation.py:126",
        unit="weight",
        min_value=0.3,
        max_value=0.9
    )
    
    ParamRegistry.register(
        name="evaluation_external_weight",
        value=0.3,
        rationale="External signal weight (chunks, citations, tool calls). "
                  "Should be increased - more objective than LLM confidence.",
        category=ParamCategory.EVALUATION,
        source="app/agent/evaluation.py:127",
        unit="weight",
        min_value=0.1,
        max_value=0.7
    )
    
    # ========================================================================
    # Timeout 相关参数
    # ========================================================================
    
    ParamRegistry.register(
        name="llm_timeout_default",
        value=120,
        rationale="Standard LLM timeout. Most queries complete within 2 minutes.",
        category=ParamCategory.TIMEOUT,
        source="app/agent/llm.py:45",
        unit="seconds",
        min_value=30,
        max_value=300
    )
    
    ParamRegistry.register(
        name="llm_timeout_tool_execution",
        value=10,
        rationale="Tool execution timeout. Should be higher - "
                  "complex tool chains need more time.",
        category=ParamCategory.TIMEOUT,
        source="app/agent/tools.py:67",
        unit="seconds",
        min_value=5,
        max_value=60,
        deprecated=True,
        replacement="llm_timeout_tool_execution_extended"
    )
    
    ParamRegistry.register(
        name="llm_timeout_tool_execution_extended",
        value=30,
        rationale="Extended tool execution timeout for complex chains.",
        category=ParamCategory.TIMEOUT,
        source="config/default_params.py:203",
        unit="seconds",
        min_value=10,
        max_value=120
    )
    
    # ========================================================================
    # Retrieval 相关参数（通用检索配置）
    # ========================================================================
    
    ParamRegistry.register(
        name="retrieval_default_top_k",
        value=8,
        rationale="Default retrieval count for hybrid search. "
                  "8 provides good balance between recall and processing latency.",
        category=ParamCategory.RETRIEVAL,
        source="app/pipeline.py:92",
        unit="count",
        min_value=5,
        max_value=20
    )
    
    ParamRegistry.register(
        name="retrieval_vector_top_k",
        value=20,
        rationale="Vector search fetch count. Higher than final top_k to allow "
                  "reranking to filter and reorder. 20 is 2.5x final output.",
        category=ParamCategory.RETRIEVAL,
        source="app/api.py:135, app/rag_pipeline.py:42",
        unit="count",
        min_value=10,
        max_value=50
    )
    
    ParamRegistry.register(
        name="retrieval_keyword_top_k",
        value=12,
        rationale="BM25 keyword search fetch count. Lower than vector because "
                  "keyword tends to have more noise.",
        category=ParamCategory.RETRIEVAL,
        source="app/api.py:136, app/rag_pipeline.py:42",
        unit="count",
        min_value=8,
        max_value=30
    )
    
    ParamRegistry.register(
        name="retrieval_graph_top_k",
        value=8,
        rationale="Graph traversal fetch count. Graph results are high precision "
                  "but computationally expensive, so keep moderate.",
        category=ParamCategory.RETRIEVAL,
        source="app/api.py:137, app/rag_pipeline.py:42",
        unit="count",
        min_value=5,
        max_value=15
    )
    
    ParamRegistry.register(
        name="price_query_page_top_k",
        value=1,
        rationale="PDF page fallback for price queries. 1 page is sufficient for "
                  "exact price lookup.",
        category=ParamCategory.RETRIEVAL,
        source="app/agent/tools.py:4234",
        unit="count",
        min_value=1,
        max_value=3
    )
    
    ParamRegistry.register(
        name="price_query_text_top_k",
        value=5,
        rationale="Text chunk fallback for price queries. Need more chunks to "
                  "find scattered pricing info.",
        category=ParamCategory.RETRIEVAL,
        source="app/agent/tools.py:4236",
        unit="count",
        min_value=3,
        max_value=10
    )
    
    ParamRegistry.register(
        name="graph_cooccur_top_k",
        value=6,
        rationale="Entity co-occurrence graph neighbors. 6 provides enough context "
                  "without overwhelming followup suggestions.",
        category=ParamCategory.RETRIEVAL,
        source="app/agent/tools.py:6059",
        unit="count",
        min_value=4,
        max_value=10
    )
    
    # ========================================================================
    # Agent 相关参数
    # ========================================================================
    
    ParamRegistry.register(
        name="agent_max_tool_iterations",
        value=10,
        rationale="Prevent infinite tool call loops. Rarely need more than 10 iterations.",
        category=ParamCategory.AGENT,
        source="app/agent/runtime.py:234",
        unit="count",
        min_value=5,
        max_value=20
    )
    
    ParamRegistry.register(
        name="agent_tool_selection_temperature",
        value=0.0,
        rationale="Deterministic tool selection. Higher temperature adds randomness.",
        category=ParamCategory.AGENT,
        source="app/agent/tools.py:123",
        unit="temperature",
        min_value=0.0,
        max_value=1.0
    )
    
    # ========================================================================
    # Price Query 相关参数
    # ========================================================================
    
    ParamRegistry.register(
        name="price_query_max_age_days",
        value=30,
        rationale="Price data older than 30 days is considered stale. "
                  "Should match data refresh frequency.",
        category=ParamCategory.GENERAL,
        source="app/tools/price_query.py:89",
        unit="days",
        min_value=7,
        max_value=90
    )
    
    ParamRegistry.register(
        name="price_query_allow_future_dates",
        value=False,
        rationale="Reject queries for future dates - no way to know future prices.",
        category=ParamCategory.GENERAL,
        source="app/tools/price_query.py:92"
    )
    
    # ========================================================================
    # WebSocket 相关参数
    # ========================================================================
    
    ParamRegistry.register(
        name="websocket_heartbeat_interval",
        value=30,
        rationale="Send ping every 30s to detect dead connections.",
        category=ParamCategory.GENERAL,
        source="src/backend/go-services/internal/websocket/hub.go:56",
        unit="seconds",
        min_value=10,
        max_value=60
    )
    
    ParamRegistry.register(
        name="websocket_cleanup_stale_threshold",
        value=600,
        rationale="Remove subscriptions with no activity for 10 minutes.",
        category=ParamCategory.GENERAL,
        source="src/backend/go-services/internal/websocket/hub.go:89",
        unit="seconds",
        min_value=300,
        max_value=1800
    )


def register_all():
    """注册所有默认参数"""
    register_default_params()
    
    # 从 retrieval_presets 自动注册（已在该模块内自动调用）
    from config.retrieval_presets import register_retrieval_presets, register_retrieval_multipliers
    # 这些函数在 retrieval_presets.py 导入时已自动执行，这里无需重复调用
    
    # 审计注册表
    issues = ParamRegistry.audit()
    if any(issues.values()):
        print("[ParamRegistry] Audit found issues:")
        for category, items in issues.items():
            if items:
                print(f"  {category}: {len(items)} issues")
                for item in items[:3]:  # 只显示前3个
                    print(f"    - {item}")
