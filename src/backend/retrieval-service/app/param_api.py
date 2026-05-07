"""
参数注册表 REST API

提供 HTTP 接口查询和管理参数注册表。

Endpoints:
- GET  /api/v1/params/             - 列出所有参数
- GET  /api/v1/params/{name}       - 获取单个参数
- GET  /api/v1/params/category/{category} - 按分类获取
- PUT  /api/v1/params/{name}/runtime - 运行时覆盖参数
- DELETE /api/v1/params/{name}/runtime - 清除运行时覆盖
- GET  /api/v1/params/audit        - 审计参数注册表
- GET  /api/v1/params/changes      - 获取变更历史
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import logging

from config.param_registry import ParamRegistry, ParamCategory, param

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/params", tags=["parameters"])


# ============================================================================
# Request/Response Models
# ============================================================================

class ParamResponse(BaseModel):
    """参数响应模型"""
    name: str
    value: Any
    rationale: str
    category: str
    source: str
    unit: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    deprecated: bool = False
    replacement: Optional[str] = None
    registered_at: str
    last_updated: str


class RuntimeOverrideRequest(BaseModel):
    """运行时覆盖请求"""
    value: Any = Field(..., description="新的参数值")


class ParamListResponse(BaseModel):
    """参数列表响应"""
    total: int
    parameters: List[ParamResponse]


class AuditResponse(BaseModel):
    """审计结果响应"""
    issues: Dict[str, List[str]]
    summary: str


class ChangeHistoryResponse(BaseModel):
    """变更历史响应"""
    total: int
    changes: List[Dict[str, Any]]


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/", response_model=ParamListResponse)
async def list_parameters(
    category: Optional[str] = Query(None, description="按分类过滤"),
    deprecated: Optional[bool] = Query(None, description="只显示废弃/非废弃参数"),
    search: Optional[str] = Query(None, description="搜索参数名")
) -> ParamListResponse:
    """
    列出所有参数
    
    查询参数：
    - category: 按分类过滤 (retrieval, followup, learning, etc.)
    - deprecated: true=只显示废弃, false=只显示非废弃, null=显示所有
    - search: 搜索参数名（大小写不敏感）
    
    示例：
        GET /api/v1/params/
        GET /api/v1/params/?category=followup
        GET /api/v1/params/?deprecated=false
        GET /api/v1/params/?search=threshold
    """
    all_params = ParamRegistry.get_all()
    
    # 过滤
    filtered = {}
    for name, metadata in all_params.items():
        # 分类过滤
        if category and metadata.category.value != category:
            continue
        
        # 废弃状态过滤
        if deprecated is not None and metadata.deprecated != deprecated:
            continue
        
        # 搜索过滤
        if search and search.lower() not in name.lower():
            continue
        
        filtered[name] = metadata
    
    # 转换为响应格式
    params = [
        ParamResponse(
            name=name,
            value=meta.value,
            rationale=meta.rationale,
            category=meta.category.value,
            source=meta.source,
            unit=meta.unit,
            min_value=meta.min_value,
            max_value=meta.max_value,
            deprecated=meta.deprecated,
            replacement=meta.replacement,
            registered_at=meta.registered_at.isoformat(),
            last_updated=meta.last_updated.isoformat()
        )
        for name, meta in sorted(filtered.items())
    ]
    
    return ParamListResponse(total=len(params), parameters=params)


@router.get("/{name}", response_model=ParamResponse)
async def get_parameter(name: str) -> ParamResponse:
    """
    获取单个参数详情
    
    路径参数：
    - name: 参数名称
    
    示例：
        GET /api/v1/params/followup_coverage_threshold_high
    """
    all_params = ParamRegistry.get_all()
    
    if name not in all_params:
        raise HTTPException(status_code=404, detail=f"Parameter '{name}' not found")
    
    meta = all_params[name]
    
    return ParamResponse(
        name=name,
        value=ParamRegistry.get(name),  # 获取实际值（可能有运行时覆盖）
        rationale=meta.rationale,
        category=meta.category.value,
        source=meta.source,
        unit=meta.unit,
        min_value=meta.min_value,
        max_value=meta.max_value,
        deprecated=meta.deprecated,
        replacement=meta.replacement,
        registered_at=meta.registered_at.isoformat(),
        last_updated=meta.last_updated.isoformat()
    )


@router.get("/category/{category}", response_model=ParamListResponse)
async def get_parameters_by_category(category: str) -> ParamListResponse:
    """
    按分类获取参数
    
    路径参数：
    - category: 参数分类 (retrieval, followup, learning, evaluation, etc.)
    
    示例：
        GET /api/v1/params/category/followup
    """
    try:
        cat_enum = ParamCategory(category)
    except ValueError:
        valid_categories = [c.value for c in ParamCategory]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category '{category}'. Valid values: {valid_categories}"
        )
    
    params_dict = ParamRegistry.get_by_category(cat_enum)
    
    params = [
        ParamResponse(
            name=name,
            value=ParamRegistry.get(name),
            rationale=meta.rationale,
            category=meta.category.value,
            source=meta.source,
            unit=meta.unit,
            min_value=meta.min_value,
            max_value=meta.max_value,
            deprecated=meta.deprecated,
            replacement=meta.replacement,
            registered_at=meta.registered_at.isoformat(),
            last_updated=meta.last_updated.isoformat()
        )
        for name, meta in sorted(params_dict.items())
    ]
    
    return ParamListResponse(total=len(params), parameters=params)


@router.put("/{name}/runtime")
async def set_runtime_override(
    name: str,
    request: RuntimeOverrideRequest
) -> Dict[str, Any]:
    """
    运行时覆盖参数（用于调试）
    
    ⚠️  警告：运行时覆盖不持久化，重启后失效。
    ⚠️  生产环境慎用，建议只在开发/测试环境使用。
    
    路径参数：
    - name: 参数名称
    
    请求体：
    - value: 新的参数值
    
    示例：
        PUT /api/v1/params/followup_coverage_threshold_high/runtime
        {
          "value": 0.70
        }
    """
    all_params = ParamRegistry.get_all()
    
    if name not in all_params:
        raise HTTPException(status_code=404, detail=f"Parameter '{name}' not found")
    
    old_value = ParamRegistry.get(name)
    new_value = request.value
    
    # 类型检查
    expected_type = type(all_params[name].value)
    if not isinstance(new_value, expected_type):
        raise HTTPException(
            status_code=400,
            detail=f"Type mismatch: expected {expected_type.__name__}, got {type(new_value).__name__}"
        )
    
    # 范围检查
    meta = all_params[name]
    if meta.min_value is not None and new_value < meta.min_value:
        raise HTTPException(
            status_code=400,
            detail=f"Value {new_value} is below minimum {meta.min_value}"
        )
    if meta.max_value is not None and new_value > meta.max_value:
        raise HTTPException(
            status_code=400,
            detail=f"Value {new_value} is above maximum {meta.max_value}"
        )
    
    # 设置运行时覆盖
    ParamRegistry.set_runtime(name, new_value)
    
    logger.warning(
        f"[ParamRegistry API] Runtime override set: {name}={new_value} (was {old_value})"
    )
    
    return {
        "success": True,
        "parameter": name,
        "old_value": old_value,
        "new_value": new_value,
        "message": "Runtime override set successfully. This will be lost on restart."
    }


@router.delete("/{name}/runtime")
async def clear_runtime_override(name: str) -> Dict[str, Any]:
    """
    清除运行时覆盖
    
    路径参数：
    - name: 参数名称
    
    示例：
        DELETE /api/v1/params/followup_coverage_threshold_high/runtime
    """
    all_params = ParamRegistry.get_all()
    
    if name not in all_params:
        raise HTTPException(status_code=404, detail=f"Parameter '{name}' not found")
    
    ParamRegistry.clear_runtime(name)
    
    logger.info(f"[ParamRegistry API] Runtime override cleared: {name}")
    
    return {
        "success": True,
        "parameter": name,
        "message": "Runtime override cleared"
    }


@router.get("/audit", response_model=AuditResponse)
async def audit_parameters() -> AuditResponse:
    """
    审计参数注册表
    
    检查：
    - 缺少理由说明的参数
    - 已废弃的参数
    - 超出范围的参数
    - 来源不明的参数
    
    示例：
        GET /api/v1/params/audit
    """
    issues = ParamRegistry.audit()
    
    # 生成摘要
    total_issues = sum(len(items) for items in issues.values())
    
    if total_issues == 0:
        summary = "✅ No issues found. All parameters are properly registered."
    else:
        summary = f"⚠️  Found {total_issues} issues across {len([k for k, v in issues.items() if v])} categories."
    
    return AuditResponse(issues=issues, summary=summary)


@router.get("/changes", response_model=ChangeHistoryResponse)
async def get_change_history(limit: int = Query(50, ge=1, le=500)) -> ChangeHistoryResponse:
    """
    获取参数变更历史
    
    查询参数：
    - limit: 返回最近 N 条记录 (默认 50, 最大 500)
    
    示例：
        GET /api/v1/params/changes
        GET /api/v1/params/changes?limit=100
    """
    changes = ParamRegistry.get_change_history(limit=limit)
    
    return ChangeHistoryResponse(total=len(changes), changes=changes)


# ============================================================================
# Helper: 批量获取参数值（内部使用）
# ============================================================================

@router.post("/_batch")
async def batch_get_parameters(names: List[str]) -> Dict[str, Any]:
    """
    批量获取参数值（内部 API）
    
    请求体：
    - names: 参数名列表
    
    返回：
    - {param_name: value}
    
    示例：
        POST /api/v1/params/_batch
        ["followup_coverage_threshold_high", "followup_coverage_threshold_med"]
    """
    result = {}
    
    for name in names:
        try:
            result[name] = param(name)
        except Exception as e:
            logger.warning(f"[ParamRegistry API] Failed to get param '{name}': {e}")
            result[name] = None
    
    return result
