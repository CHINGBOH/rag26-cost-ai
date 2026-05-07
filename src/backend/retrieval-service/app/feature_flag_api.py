"""
Feature Flag API Routes
提供 feature flags 的查询、更新、历史查看等 HTTP 端点
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
import logging

# 将在 main.py 中初始化
_feature_flag_repo = None

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/feature-flags", tags=["feature-flags"])


# ============================================================================
# Request/Response Models
# ============================================================================

class FeatureFlagUpdateRequest(BaseModel):
    """更新 feature flag 的请求"""
    enabled: Optional[bool] = None
    description: Optional[str] = None
    rollout_percentage: Optional[int] = Field(None, ge=0, le=100)
    target_users: Optional[List[str]] = None
    target_environments: Optional[List[str]] = None
    updated_by: Optional[str] = "api"
    metadata: Optional[Dict[str, Any]] = None


class RuntimeOverrideRequest(BaseModel):
    """运行时临时覆盖的请求"""
    enabled: bool
    ttl_seconds: Optional[int] = Field(None, ge=0, le=86400, description="过期时间（秒），最多24小时")


class FeatureFlagResponse(BaseModel):
    """Feature flag 响应"""
    flag_name: str
    enabled: bool
    description: Optional[str]
    rollout_percentage: int
    target_users: List[str]
    target_environments: List[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    updated_by: Optional[str]
    metadata: Dict[str, Any]


class FeatureFlagStatusResponse(BaseModel):
    """Feature flag 状态响应（包含来源信息）"""
    flag_name: str
    enabled: bool
    source: str  # "runtime_override" | "database" | "default"
    expires_at: Optional[str]
    default_value: bool


# ============================================================================
# Dependencies
# ============================================================================

def get_feature_flag_repo():
    """获取 FeatureFlagRepository 实例"""
    if _feature_flag_repo is None:
        raise HTTPException(status_code=503, detail="Feature flag repository not initialized")
    return _feature_flag_repo


def set_feature_flag_repo(repo):
    """设置全局 repository 实例（在 main.py 中调用）"""
    global _feature_flag_repo
    _feature_flag_repo = repo


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/", response_model=Dict[str, FeatureFlagStatusResponse])
async def list_feature_flags():
    """
    列出所有 feature flags 的当前状态
    
    Returns:
        Dict[str, FeatureFlagStatusResponse]: 所有 flags 的状态
    
    Example:
        GET /api/v1/feature-flags/
        
        Response:
        {
            "FOLLOWUP_STRICT_COVERAGE": {
                "flag_name": "FOLLOWUP_STRICT_COVERAGE",
                "enabled": true,
                "source": "database",
                "expires_at": null,
                "default_value": false
            },
            ...
        }
    """
    from config.feature_flags import FeatureFlags
    
    all_flags = FeatureFlags.get_all()
    
    return {
        flag_name: FeatureFlagStatusResponse(
            flag_name=flag_name,
            enabled=info["enabled"],
            source=info["source"],
            expires_at=info["expires_at"],
            default_value=info["default"]
        )
        for flag_name, info in all_flags.items()
    }


@router.get("/{flag_name}", response_model=FeatureFlagStatusResponse)
async def get_feature_flag(flag_name: str):
    """
    获取单个 feature flag 的状态
    
    Args:
        flag_name: Feature flag 名称
    
    Returns:
        FeatureFlagStatusResponse: Flag 状态
    
    Example:
        GET /api/v1/feature-flags/FOLLOWUP_STRICT_COVERAGE
    """
    from config.feature_flags import FeatureFlags
    
    info = FeatureFlags.get_flag_info(flag_name)
    
    if "error" in info:
        raise HTTPException(status_code=404, detail=info["error"])
    
    return FeatureFlagStatusResponse(
        flag_name=flag_name,
        enabled=info["enabled"],
        source=info["source"],
        expires_at=info.get("expires_at"),
        default_value=info["default"]
    )


@router.get("/{flag_name}/details", response_model=FeatureFlagResponse)
async def get_feature_flag_details(
    flag_name: str,
    repo=Depends(get_feature_flag_repo)
):
    """
    获取 feature flag 的详细信息（从数据库）
    
    Args:
        flag_name: Feature flag 名称
    
    Returns:
        FeatureFlagResponse: Flag 详细信息
    
    Example:
        GET /api/v1/feature-flags/FOLLOWUP_STRICT_COVERAGE/details
    """
    flag = await repo.get(flag_name)
    
    if not flag:
        raise HTTPException(status_code=404, detail=f"Feature flag '{flag_name}' not found")
    
    return FeatureFlagResponse(**flag.to_dict())


@router.put("/{flag_name}", response_model=FeatureFlagResponse)
async def update_feature_flag(
    flag_name: str,
    request: FeatureFlagUpdateRequest,
    repo=Depends(get_feature_flag_repo)
):
    """
    更新 feature flag（持久化到数据库）
    
    Args:
        flag_name: Feature flag 名称
        request: 更新请求
    
    Returns:
        FeatureFlagResponse: 更新后的 flag
    
    Example:
        PUT /api/v1/feature-flags/FOLLOWUP_STRICT_COVERAGE
        {
            "enabled": true,
            "rollout_percentage": 50,
            "updated_by": "admin"
        }
    """
    flag = await repo.update(
        flag_name=flag_name,
        enabled=request.enabled,
        description=request.description,
        rollout_percentage=request.rollout_percentage,
        target_users=request.target_users,
        target_environments=request.target_environments,
        updated_by=request.updated_by,
        metadata=request.metadata
    )
    
    if not flag:
        raise HTTPException(status_code=404, detail=f"Feature flag '{flag_name}' not found")
    
    # 触发缓存重新加载
    from config.feature_flags import FeatureFlags
    await FeatureFlags.reload_from_db()
    
    logger.info(f"[FeatureFlagAPI] Updated flag: {flag_name}, enabled={request.enabled}")
    
    return FeatureFlagResponse(**flag.to_dict())


@router.post("/{flag_name}/runtime-override")
async def set_runtime_override(
    flag_name: str,
    request: RuntimeOverrideRequest
):
    """
    运行时临时覆盖 feature flag（不持久化）
    
    用于紧急热修复场景，例如：
    - 生产环境发现新功能有问题，需要立即关闭
    - 临时启用调试功能
    
    Args:
        flag_name: Feature flag 名称
        request: 运行时覆盖请求
    
    Returns:
        Dict: 操作结果
    
    Example:
        POST /api/v1/feature-flags/EVALUATION_STRICT_MODE/runtime-override
        {
            "enabled": false,
            "ttl_seconds": 3600
        }
    """
    from config.feature_flags import FeatureFlags
    
    FeatureFlags.set_runtime(
        flag=flag_name,
        value=request.enabled,
        ttl_seconds=request.ttl_seconds
    )
    
    logger.warning(
        f"[FeatureFlagAPI] Runtime override set: {flag_name}={request.enabled}, "
        f"ttl={request.ttl_seconds}s"
    )
    
    return {
        "success": True,
        "flag_name": flag_name,
        "enabled": request.enabled,
        "ttl_seconds": request.ttl_seconds,
        "message": "Runtime override applied (not persisted to database)"
    }


@router.delete("/{flag_name}/runtime-override")
async def clear_runtime_override(flag_name: str):
    """
    清除运行时覆盖
    
    Args:
        flag_name: Feature flag 名称
    
    Returns:
        Dict: 操作结果
    
    Example:
        DELETE /api/v1/feature-flags/EVALUATION_STRICT_MODE/runtime-override
    """
    from config.feature_flags import FeatureFlags
    
    FeatureFlags.clear_runtime(flag=flag_name)
    
    logger.info(f"[FeatureFlagAPI] Runtime override cleared: {flag_name}")
    
    return {
        "success": True,
        "flag_name": flag_name,
        "message": "Runtime override cleared"
    }


@router.get("/{flag_name}/history")
async def get_feature_flag_history(
    flag_name: str,
    limit: int = 50,
    repo=Depends(get_feature_flag_repo)
):
    """
    获取 feature flag 变更历史
    
    Args:
        flag_name: Feature flag 名称
        limit: 返回记录数量限制
    
    Returns:
        List[Dict]: 变更历史
    
    Example:
        GET /api/v1/feature-flags/FOLLOWUP_STRICT_COVERAGE/history?limit=10
    """
    history = await repo.get_history(flag_name, limit=limit)
    
    return {
        "flag_name": flag_name,
        "history": history
    }


@router.post("/reload")
async def reload_from_database():
    """
    从数据库重新加载所有 feature flags
    
    触发缓存刷新
    
    Returns:
        Dict: 操作结果
    
    Example:
        POST /api/v1/feature-flags/reload
    """
    from config.feature_flags import FeatureFlags
    
    await FeatureFlags.reload_from_db()
    
    logger.info("[FeatureFlagAPI] Reloaded feature flags from database")
    
    return {
        "success": True,
        "message": "Feature flags reloaded from database"
    }
