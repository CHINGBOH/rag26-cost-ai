"""
参数注册表 - 统一管理所有硬编码阈值和 magic numbers

目标：
- 所有可调参数在启动时注册
- 强制要求说明参数设定理由
- 支持参数审计和追踪
- 记录参数调优历史

优先级：
1. 运行时覆盖（临时调试）
2. 环境变量（ENV）
3. 配置文件（YAML）
4. 注册的默认值

示例用法：
    ```python
    from config.param_registry import ParamRegistry, param
    
    # 注册参数
    ParamRegistry.register(
        name="followup_coverage_threshold_high",
        value=0.65,
        rationale="A/B test 2024-Q1: 0.65 achieved 75% answerability",
        category="followup",
        source="app/agent/graph.py:3799"
    )
    
    # 使用参数
    threshold = param("followup_coverage_threshold_high")
    # 或者
    threshold = ParamRegistry.get("followup_coverage_threshold_high")
    ```
"""

from typing import Any, Dict, Optional, List, Callable
from datetime import datetime
from enum import Enum
import logging
import os

logger = logging.getLogger(__name__)


class ParamCategory(str, Enum):
    """参数分类"""
    RETRIEVAL = "retrieval"           # 检索相关（top_k, threshold）
    FOLLOWUP = "followup"             # 追问相关（覆盖率、过滤）
    LEARNING = "learning"             # 学习系统（重测、调度）
    EVALUATION = "evaluation"         # 评估相关（分数、阈值）
    CONTRACT = "contract"             # 合约验证
    TIMEOUT = "timeout"               # 超时设置
    ITERATION = "iteration"           # 迭代相关
    AGENT = "agent"                   # Agent 行为
    GENERAL = "general"               # 通用参数


class ParamMetadata:
    """参数元数据"""
    
    def __init__(
        self,
        name: str,
        value: Any,
        rationale: str,
        category: ParamCategory,
        source: str,
        unit: Optional[str] = None,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        deprecated: bool = False,
        replacement: Optional[str] = None
    ):
        self.name = name
        self.value = value
        self.rationale = rationale
        self.category = category
        self.source = source
        self.unit = unit
        self.min_value = min_value
        self.max_value = max_value
        self.deprecated = deprecated
        self.replacement = replacement
        self.registered_at = datetime.now()
        self.last_updated = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "value": self.value,
            "rationale": self.rationale,
            "category": self.category.value,
            "source": self.source,
            "unit": self.unit,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "deprecated": self.deprecated,
            "replacement": self.replacement,
            "registered_at": self.registered_at.isoformat(),
            "last_updated": self.last_updated.isoformat()
        }


class ParamRegistry:
    """
    参数注册表
    
    职责：
    1. 注册所有可调参数
    2. 提供参数查询接口
    3. 支持运行时覆盖（调试用）
    4. 审计未说明理由的参数
    5. 记录参数变更历史
    """
    
    # 注册表：{param_name: ParamMetadata}
    _registry: Dict[str, ParamMetadata] = {}
    
    # 运行时覆盖（最高优先级）
    _runtime_overrides: Dict[str, Any] = {}
    
    # 变更历史
    _change_history: List[Dict[str, Any]] = []
    
    @classmethod
    def register(
        cls,
        name: str,
        value: Any,
        rationale: str,
        category: ParamCategory = ParamCategory.GENERAL,
        source: str = "unknown",
        unit: Optional[str] = None,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        deprecated: bool = False,
        replacement: Optional[str] = None
    ) -> None:
        """
        注册一个参数
        
        Args:
            name: 参数名称（唯一标识）
            value: 默认值
            rationale: 设定理由（强制要求）
            category: 参数分类
            source: 定义位置（文件:行号）
            unit: 单位（如 "seconds", "percentage", "count"）
            min_value: 最小值（可选）
            max_value: 最大值（可选）
            deprecated: 是否废弃
            replacement: 替代参数（如果废弃）
        
        示例：
            ParamRegistry.register(
                name="followup_coverage_threshold_high",
                value=0.65,
                rationale="A/B test 2024-Q1: 0.65 achieved 75% answerability vs 0.45 at 45%",
                category=ParamCategory.FOLLOWUP,
                source="app/agent/graph.py:3799",
                unit="score",
                min_value=0.0,
                max_value=1.0
            )
        """
        if not rationale or rationale.strip() in ("", "unknown", "TODO", "TBD"):
            logger.warning(
                f"[ParamRegistry] Parameter '{name}' registered without proper rationale. "
                f"Please provide a meaningful explanation."
            )
        
        metadata = ParamMetadata(
            name=name,
            value=value,
            rationale=rationale,
            category=category,
            source=source,
            unit=unit,
            min_value=min_value,
            max_value=max_value,
            deprecated=deprecated,
            replacement=replacement
        )
        
        # 检查重复注册
        if name in cls._registry:
            old_value = cls._registry[name].value
            if old_value != value:
                logger.warning(
                    f"[ParamRegistry] Parameter '{name}' re-registered with different value: "
                    f"{old_value} -> {value}"
                )
                cls._log_change(name, old_value, value, "re-registration", source)
        
        cls._registry[name] = metadata
        logger.debug(f"[ParamRegistry] Registered: {name}={value} ({category.value})")
    
    @classmethod
    def get(cls, name: str, default: Any = None) -> Any:
        """
        获取参数值
        
        优先级：
        1. 运行时覆盖
        2. 环境变量（PARAM__<NAME>）
        3. 注册的默认值
        4. fallback default
        
        Args:
            name: 参数名称
            default: 如果参数不存在，返回此默认值
        
        Returns:
            参数值
        """
        # 优先级 1: 运行时覆盖
        if name in cls._runtime_overrides:
            return cls._runtime_overrides[name]
        
        # 优先级 2: 环境变量
        env_key = f"PARAM__{name.upper()}"
        env_value = os.getenv(env_key)
        if env_value is not None:
            # 尝试转换类型
            if name in cls._registry:
                original_type = type(cls._registry[name].value)
                try:
                    if original_type == bool:
                        return env_value.lower() in ("true", "1", "yes")
                    elif original_type == int:
                        return int(env_value)
                    elif original_type == float:
                        return float(env_value)
                    else:
                        return env_value
                except ValueError:
                    logger.warning(
                        f"[ParamRegistry] Failed to convert env var {env_key}={env_value} "
                        f"to {original_type.__name__}"
                    )
        
        # 优先级 3: 注册的默认值
        if name in cls._registry:
            metadata = cls._registry[name]
            if metadata.deprecated:
                logger.warning(
                    f"[ParamRegistry] Parameter '{name}' is deprecated. "
                    f"Use '{metadata.replacement}' instead."
                )
            return metadata.value
        
        # 优先级 4: fallback
        if default is None:
            logger.warning(f"[ParamRegistry] Parameter '{name}' not found, returning None")
        return default
    
    @classmethod
    def set_runtime(cls, name: str, value: Any) -> None:
        """
        运行时临时覆盖参数（用于调试）
        
        注意：此覆盖不持久化，重启后失效
        
        Args:
            name: 参数名称
            value: 新值
        """
        old_value = cls.get(name)
        cls._runtime_overrides[name] = value
        cls._log_change(name, old_value, value, "runtime_override", "runtime")
        logger.warning(f"[ParamRegistry] Runtime override: {name}={value}")
    
    @classmethod
    def clear_runtime(cls, name: Optional[str] = None) -> None:
        """清除运行时覆盖"""
        if name:
            cls._runtime_overrides.pop(name, None)
            logger.info(f"[ParamRegistry] Runtime override cleared: {name}")
        else:
            cls._runtime_overrides.clear()
            logger.info("[ParamRegistry] All runtime overrides cleared")
    
    @classmethod
    def audit(cls) -> Dict[str, List[str]]:
        """
        审计参数注册表
        
        Returns:
            Dict: {
                "missing_rationale": [参数名列表],
                "deprecated": [参数名列表],
                "out_of_range": [参数名列表],
                "unknown_source": [参数名列表]
            }
        """
        issues = {
            "missing_rationale": [],
            "deprecated": [],
            "out_of_range": [],
            "unknown_source": []
        }
        
        for name, metadata in cls._registry.items():
            # 检查 rationale
            if not metadata.rationale or metadata.rationale.strip() in ("", "unknown", "TODO", "TBD"):
                issues["missing_rationale"].append(name)
            
            # 检查废弃
            if metadata.deprecated:
                issues["deprecated"].append(name)
            
            # 检查范围
            if metadata.min_value is not None and metadata.value < metadata.min_value:
                issues["out_of_range"].append(f"{name}: {metadata.value} < {metadata.min_value}")
            if metadata.max_value is not None and metadata.value > metadata.max_value:
                issues["out_of_range"].append(f"{name}: {metadata.value} > {metadata.max_value}")
            
            # 检查来源
            if metadata.source in ("unknown", ""):
                issues["unknown_source"].append(name)
        
        return issues
    
    @classmethod
    def get_by_category(cls, category: ParamCategory) -> Dict[str, ParamMetadata]:
        """按分类获取参数"""
        return {
            name: metadata
            for name, metadata in cls._registry.items()
            if metadata.category == category
        }
    
    @classmethod
    def get_all(cls) -> Dict[str, ParamMetadata]:
        """获取所有注册的参数"""
        return cls._registry.copy()
    
    @classmethod
    def get_change_history(cls, limit: int = 50) -> List[Dict[str, Any]]:
        """获取参数变更历史"""
        return cls._change_history[-limit:]
    
    @classmethod
    def export_to_dict(cls) -> Dict[str, Any]:
        """导出为字典（用于 API 响应）"""
        return {
            "parameters": {name: meta.to_dict() for name, meta in cls._registry.items()},
            "runtime_overrides": cls._runtime_overrides.copy(),
            "change_history": cls.get_change_history()
        }
    
    @classmethod
    def _log_change(cls, name: str, old_value: Any, new_value: Any, reason: str, source: str):
        """记录参数变更"""
        cls._change_history.append({
            "timestamp": datetime.now().isoformat(),
            "name": name,
            "old_value": old_value,
            "new_value": new_value,
            "reason": reason,
            "source": source
        })


# ============================================================================
# 便捷函数
# ============================================================================

def param(name: str, default: Any = None) -> Any:
    """
    便捷函数：获取参数值
    
    示例：
        from config.param_registry import param
        
        threshold = param("followup_coverage_threshold_high")
    """
    return ParamRegistry.get(name, default)


def register_param(
    name: str,
    value: Any,
    rationale: str,
    category: ParamCategory = ParamCategory.GENERAL,
    **kwargs
) -> None:
    """
    便捷函数：注册参数
    
    示例：
        from config.param_registry import register_param, ParamCategory
        
        register_param(
            "followup_coverage_threshold_high",
            0.65,
            "A/B test 2024-Q1",
            ParamCategory.FOLLOWUP
        )
    """
    ParamRegistry.register(name, value, rationale, category, **kwargs)
