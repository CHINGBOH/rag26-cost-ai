"""
Feature Flag 系统 - 支持运行时行为动态切换
支持：
- 灰度发布和 A/B 测试
- 快速回滚问题功能
- 无需重启服务即可调整行为
- 优先级：运行时覆盖 > 数据库 > 代码默认值
"""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class FeatureFlagName(str, Enum):
    """Feature flag 名称枚举"""
    
    # Followup 相关
    FOLLOWUP_STRICT_COVERAGE = "FOLLOWUP_STRICT_COVERAGE"
    
    # 学习系统相关
    LEARNING_ADAPTIVE_SCHEDULING = "LEARNING_ADAPTIVE_SCHEDULING"
    LEARNING_GAP_WHITELIST = "LEARNING_GAP_WHITELIST"
    
    # Agent 相关
    TOOL_EXPLAINABLE_SELECTION = "TOOL_EXPLAINABLE_SELECTION"
    CONTRACT_CONVERGENCE_POLICY = "CONTRACT_CONVERGENCE_POLICY"
    
    # 评估相关
    EVALUATION_STRICT_MODE = "EVALUATION_STRICT_MODE"
    
    # 价格查询相关
    PRICE_QUERY_TIME_VALIDATION = "PRICE_QUERY_TIME_VALIDATION"
    
    # 配置相关
    UNIFIED_CONFIG_LOADER = "UNIFIED_CONFIG_LOADER"


class FeatureFlags:
    """
    Feature Flag 管理器
    
    优先级（从高到低）：
    1. 运行时临时覆盖 (_runtime_overrides)
    2. 数据库持久化配置 (通过 FeatureFlagRepository)
    3. 代码默认值 (DEFAULT_VALUES)
    
    示例用法:
        ```python
        # 检查 flag 是否启用
        if FeatureFlags.is_enabled("FOLLOWUP_STRICT_COVERAGE"):
            # 使用严格覆盖率检测
            pass
        
        # 运行时临时启用（用于紧急热修复）
        FeatureFlags.set_runtime("EVALUATION_STRICT_MODE", True, ttl_seconds=3600)
        
        # 从数据库重新加载
        await FeatureFlags.reload_from_db()
        ```
    """
    
    # 代码默认值（最低优先级）
    DEFAULT_VALUES: Dict[str, bool] = {
        # Followup 默认不启用严格模式（避免破坏现有行为）
        FeatureFlagName.FOLLOWUP_STRICT_COVERAGE: False,
        
        # 学习系统默认不启用自适应调度（需要测试后再开启）
        FeatureFlagName.LEARNING_ADAPTIVE_SCHEDULING: False,
        FeatureFlagName.LEARNING_GAP_WHITELIST: False,
        
        # Agent 工具选择默认不启用可解释性（额外 LLM 调用成本）
        FeatureFlagName.TOOL_EXPLAINABLE_SELECTION: False,
        FeatureFlagName.CONTRACT_CONVERGENCE_POLICY: False,
        
        # 评估默认不启用严格模式（避免所有答案都低分）
        FeatureFlagName.EVALUATION_STRICT_MODE: False,
        
        # 价格查询时间验证默认启用（防止明显错误）
        FeatureFlagName.PRICE_QUERY_TIME_VALIDATION: True,
        
        # 统一配置加载器默认启用
        FeatureFlagName.UNIFIED_CONFIG_LOADER: True,
    }
    
    # 运行时临时覆盖（最高优先级）
    _runtime_overrides: Dict[str, bool] = {}
    _runtime_ttl: Dict[str, datetime] = {}
    
    # 数据库缓存
    _db_cache: Dict[str, bool] = {}
    _last_reload: Optional[datetime] = None
    _cache_ttl: timedelta = timedelta(minutes=5)  # 数据库缓存5分钟
    
    @classmethod
    def is_enabled(cls, flag: str) -> bool:
        """
        检查 feature flag 是否启用
        
        Args:
            flag: Feature flag 名称（字符串或枚举）
        
        Returns:
            bool: True 表示启用，False 表示禁用
        """
        # 规范化 flag 名称
        flag_name = flag.value if isinstance(flag, FeatureFlagName) else flag
        
        # 优先级 1: 运行时临时覆盖
        if flag_name in cls._runtime_overrides:
            # 检查是否过期
            if flag_name in cls._runtime_ttl:
                if datetime.now() > cls._runtime_ttl[flag_name]:
                    # 过期，删除
                    del cls._runtime_overrides[flag_name]
                    del cls._runtime_ttl[flag_name]
                    logger.info(f"[FeatureFlags] Runtime override expired: {flag_name}")
                else:
                    return cls._runtime_overrides[flag_name]
            else:
                return cls._runtime_overrides[flag_name]
        
        # 优先级 2: 数据库缓存
        if cls._should_reload_from_db():
            # 需要重新加载（缓存过期）
            # 注意：这里是同步方法，不能直接调用异步的 reload_from_db
            # 生产环境应该有后台任务定期刷新缓存
            pass
        
        if flag_name in cls._db_cache:
            return cls._db_cache[flag_name]
        
        # 优先级 3: 代码默认值
        return cls.DEFAULT_VALUES.get(flag_name, False)
    
    @classmethod
    def set_runtime(cls, flag: str, value: bool, ttl_seconds: Optional[int] = None):
        """
        运行时临时覆盖 feature flag（用于紧急开关）
        
        Args:
            flag: Feature flag 名称
            value: True 启用，False 禁用
            ttl_seconds: 过期时间（秒），None 表示永不过期
        
        示例:
            # 紧急关闭严格评估模式
            FeatureFlags.set_runtime("EVALUATION_STRICT_MODE", False, ttl_seconds=3600)
        """
        flag_name = flag.value if isinstance(flag, FeatureFlagName) else flag
        
        cls._runtime_overrides[flag_name] = value
        
        if ttl_seconds:
            cls._runtime_ttl[flag_name] = datetime.now() + timedelta(seconds=ttl_seconds)
            logger.warning(
                f"[FeatureFlags] Runtime override set: {flag_name}={value} (TTL: {ttl_seconds}s)"
            )
        else:
            logger.warning(f"[FeatureFlags] Runtime override set: {flag_name}={value} (no TTL)")
    
    @classmethod
    def clear_runtime(cls, flag: Optional[str] = None):
        """清除运行时覆盖"""
        if flag:
            flag_name = flag.value if isinstance(flag, FeatureFlagName) else flag
            cls._runtime_overrides.pop(flag_name, None)
            cls._runtime_ttl.pop(flag_name, None)
            logger.info(f"[FeatureFlags] Runtime override cleared: {flag_name}")
        else:
            cls._runtime_overrides.clear()
            cls._runtime_ttl.clear()
            logger.info("[FeatureFlags] All runtime overrides cleared")
    
    @classmethod
    async def reload_from_db(cls):
        """
        从数据库重新加载 feature flags
        
        注意：需要在 async 上下文中调用
        """
        try:
            # TODO: 实现数据库读取
            # from .repositories import FeatureFlagRepository
            # repo = FeatureFlagRepository()
            # db_flags = await repo.get_all()
            # cls._db_cache = {f.flag_name: f.enabled for f in db_flags}
            
            cls._last_reload = datetime.now()
            logger.info(f"[FeatureFlags] Reloaded from database, count: {len(cls._db_cache)}")
        except Exception as e:
            logger.error(f"[FeatureFlags] Failed to reload from database: {e}")
    
    @classmethod
    def _should_reload_from_db(cls) -> bool:
        """检查是否需要从数据库重新加载"""
        if cls._last_reload is None:
            return True
        
        return datetime.now() - cls._last_reload > cls._cache_ttl
    
    @classmethod
    def get_all(cls) -> Dict[str, Dict[str, Any]]:
        """
        获取所有 feature flags 的状态
        
        Returns:
            Dict: {flag_name: {enabled: bool, source: str}}
        """
        result = {}
        
        for flag_name in cls.DEFAULT_VALUES.keys():
            # 确定当前值和来源
            if flag_name in cls._runtime_overrides:
                enabled = cls._runtime_overrides[flag_name]
                source = "runtime_override"
                ttl = cls._runtime_ttl.get(flag_name)
                expires_at = ttl.isoformat() if ttl else None
            elif flag_name in cls._db_cache:
                enabled = cls._db_cache[flag_name]
                source = "database"
                expires_at = None
            else:
                enabled = cls.DEFAULT_VALUES[flag_name]
                source = "default"
                expires_at = None
            
            result[flag_name] = {
                "enabled": enabled,
                "source": source,
                "expires_at": expires_at,
                "default": cls.DEFAULT_VALUES[flag_name]
            }
        
        return result
    
    @classmethod
    def get_flag_info(cls, flag: str) -> Dict[str, Any]:
        """获取单个 flag 的详细信息"""
        flag_name = flag.value if isinstance(flag, FeatureFlagName) else flag
        all_flags = cls.get_all()
        return all_flags.get(flag_name, {
            "enabled": False,
            "source": "unknown",
            "error": "Flag not found"
        })


# 便捷函数
def is_feature_enabled(flag: str) -> bool:
    """
    便捷函数：检查 feature flag 是否启用
    
    示例:
        from config.feature_flags import is_feature_enabled
        
        if is_feature_enabled("FOLLOWUP_STRICT_COVERAGE"):
            # 使用严格覆盖率检测
            pass
    """
    return FeatureFlags.is_enabled(flag)
