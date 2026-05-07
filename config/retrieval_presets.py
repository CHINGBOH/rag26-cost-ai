"""
检索预设值 - 语义化的 top_k 配置

目标：
- 统一所有 top_k 参数
- 提供语义化的命名
- 避免硬编码 magic numbers

使用场景：
- NARROW (3): followup 覆盖检测，ultra-precise
- FOCUSED (5): category/concept 检索，精准锚定
- STANDARD (8): clause/pdf 页检索，标准检索
- BROAD (12): catalog/roadmap 检索，宽松探索
- DEEP (20): 用户显式要求深度召回
"""

from enum import IntEnum
from config.param_registry import ParamRegistry, ParamCategory


class RetrievalPresets(IntEnum):
    """
    检索预设值
    
    语义化的 top_k 配置，避免硬编码 magic numbers。
    
    使用示例：
        ```python
        from config.retrieval_presets import RetrievalPresets
        
        # 使用预设
        results = text_search(query, top_k=RetrievalPresets.NARROW)
        
        # 在 followup 覆盖检测中使用
        raw = _ts.invoke({"query": question, "top_k": RetrievalPresets.NARROW})
        ```
    """
    
    # Ultra-precise: 覆盖检测、高精度场景
    NARROW = 3
    
    # Focused: 分类、概念检索
    FOCUSED = 5
    
    # Standard: 条款、PDF 页检索
    STANDARD = 8
    
    # Broad: 目录、路线图检索
    BROAD = 12
    
    # Deep: 用户显式要求深度召回
    DEEP = 20


# ============================================================================
# 注册到参数注册表
# ============================================================================

def register_retrieval_presets():
    """注册检索预设到参数注册表"""
    
    ParamRegistry.register(
        name="retrieval_preset_narrow",
        value=RetrievalPresets.NARROW,
        rationale="Ultra-precise retrieval for coverage detection. "
                  "Small top_k reduces noise and focuses on best matches.",
        category=ParamCategory.RETRIEVAL,
        source="config/retrieval_presets.py:32",
        unit="count",
        min_value=1,
        max_value=5
    )
    
    ParamRegistry.register(
        name="retrieval_preset_focused",
        value=RetrievalPresets.FOCUSED,
        rationale="Focused retrieval for category and concept searches. "
                  "Balances precision and recall.",
        category=ParamCategory.RETRIEVAL,
        source="config/retrieval_presets.py:35",
        unit="count",
        min_value=3,
        max_value=8
    )
    
    ParamRegistry.register(
        name="retrieval_preset_standard",
        value=RetrievalPresets.STANDARD,
        rationale="Standard retrieval for clause and PDF page searches. "
                  "Most common use case.",
        category=ParamCategory.RETRIEVAL,
        source="config/retrieval_presets.py:38",
        unit="count",
        min_value=5,
        max_value=12
    )
    
    ParamRegistry.register(
        name="retrieval_preset_broad",
        value=RetrievalPresets.BROAD,
        rationale="Broad retrieval for catalog and roadmap exploration. "
                  "Allows more diverse results.",
        category=ParamCategory.RETRIEVAL,
        source="config/retrieval_presets.py:41",
        unit="count",
        min_value=8,
        max_value=20
    )
    
    ParamRegistry.register(
        name="retrieval_preset_deep",
        value=RetrievalPresets.DEEP,
        rationale="Deep retrieval for user-requested exhaustive search. "
                  "Maximum recall, used sparingly.",
        category=ParamCategory.RETRIEVAL,
        source="config/retrieval_presets.py:44",
        unit="count",
        min_value=10,
        max_value=50
    )


# ============================================================================
# Multiplier 配置
# ============================================================================

class RetrievalMultiplier:
    """
    检索倍数配置
    
    用于 vector_fetch_k 和 text_fetch_k 的动态调整。
    """
    
    # Vector fetch multiplier (召回时多取一些，后续 rerank)
    VECTOR_FETCH = 2.0
    
    # Text fetch multiplier (全文检索多样性更高，需要更多候选)
    TEXT_FETCH = 1.5


def register_retrieval_multipliers():
    """注册检索倍数到参数注册表"""
    
    ParamRegistry.register(
        name="retrieval_multiplier_vector_fetch",
        value=RetrievalMultiplier.VECTOR_FETCH,
        rationale="Vector search overfetches by 2x to compensate for semantic drift. "
                  "Reranker will filter down to target top_k.",
        category=ParamCategory.RETRIEVAL,
        source="config/retrieval_presets.py:103",
        unit="multiplier",
        min_value=1.0,
        max_value=5.0
    )
    
    ParamRegistry.register(
        name="retrieval_multiplier_text_fetch",
        value=RetrievalMultiplier.TEXT_FETCH,
        rationale="Text search (BM25) has higher diversity, 1.5x overfetch sufficient.",
        category=ParamCategory.RETRIEVAL,
        source="config/retrieval_presets.py:106",
        unit="multiplier",
        min_value=1.0,
        max_value=3.0
    )


# ============================================================================
# 自动注册
# ============================================================================

# 启动时自动注册
register_retrieval_presets()
register_retrieval_multipliers()
