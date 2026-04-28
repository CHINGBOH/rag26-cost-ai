from typing import Annotated
import operator
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage


class ContractResult(TypedDict):
    """Post-condition check for a single graph node."""
    node: str                           # e.g. 'query_analysis', 'navigator'
    passed: bool                        # True if all node post-conditions hold
    violations: list[tuple[str, str]]   # [(code, detail), ...]


class RoadmapItem(TypedDict):
    """Single chapter entry in the Navigator's roadmap."""
    chapter_id: str   # e.g. '10.2.6'
    path:       str   # e.g. '第二册电气设备安装工程/10.1/10.1.7'
    file_name:  str   # e.g. '第二册电气设备安装工程.pdf'
    title:      str   # e.g. '10.1.7 送配电装置系统调试'
    reason:     str   # why this chapter is relevant


class RAGAgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]  # Channel: append-only
    query: str
    query_type: str                     # 'price' | 'semantic' | 'calculation' | 'comparison' | 'trend_chart' | 'standard_ref'
    query_entities: dict                # analyzer-extracted entities such as year/month/material/spec
    sub_queries: list[str]              # 分解后的子查询列表
    plan: list[str]                     # planner_node 生成的步骤列表
    current_step: int                   # executor_node 当前执行到第几步
    thought_process: list[str]          # 每步执行后的自省摘要
    iterations: int
    max_iterations: int
    retrieved_chunks: list[dict]        # 工具返回后填充（已过滤）
    evaluation: dict | None             # 评估节点填充
    final_answer: str                   # 最终答案
    tool_call_cache: dict[str, str]     # {tool_name+args_hash: result} 去重缓存
    calculation_inputs: dict            # 从 chunks 中提取的数值 {name: value}
    category_hints: list[str]          # category_search 返回的章节定位字符串，跨步骤传递
    target_doc_id: str                  # resolved doc scope for forced rule-clause drilldown
    target_doc_filename: str            # resolved file_name scope for forced rule-clause drilldown
    target_section: str                 # resolved section id, e.g. 10.3.6
    target_page_start: int              # resolved page window start for scoped clause retrieval
    target_page_end: int                # resolved page window end for scoped clause retrieval
    force_clause_drilldown: bool        # when True, executor must call rule_clause_search next
    fallback_mode: bool                 # True = 已触发位置词降级，防止无限循环
    has_tool_calls: bool                # executor_node 标记是否有待执行的 tool_calls
    llm_config: dict                    # LLM routing config from request
    llm_runtime: dict                   # actual runtime metadata of the active/final model
    stream_response: bool               # True when the API will stream synthesis tokens itself
    synthesis_prompt: str               # prepared synthesis prompt for streaming path
    citations_text: str                 # normalized reference index block for final answer
    step_number: int                    # current executing step number for SSE
    total_steps: int                    # total planned steps for SSE
    step_hint: str                      # current step detail for SSE
    pending_tool_calls: list[dict]      # tool calls selected by executor for SSE start events
    step_summary: str                   # summary text when a step finishes without more tool calls
    presentation: dict | None           # structured UI payload for charts/cards
    presentation_policy: dict | None    # state-decided presentation strategy (labels/kicker/tone)
    # ── Navigator / workspace additions ─────────────────────────────────────────
    roadmap: list[RoadmapItem]          # Navigator写入：相关章节地图，Planner/React据此约束搜索
    workspace: list[dict]               # 跨章节证据池：所有检索到的evidence，防止context washout

    # ── Iterative convergence / outer-loop contract verification ────────────────
    contract_results: list[ContractResult]   # 每轮合约验证结果
    outer_iteration: int                     # 外循环迭代计数，default 0
    max_outer_iterations: int                # 外循环上限，default 3
    quality_converged: bool                  # True 时合约全部通过或强制输出
    corrective_actions: list[str]            # 已执行精炼动作，防重复
    root_cause_node: str                     # 重放目标节点，由 trace_root_cause 设定
    tool_fallback_level: int                 # 工具降级深度，default 0
    used_tool_categories: list[str]          # 已尝试工具类别，防重复
