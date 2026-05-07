"""
Observability API - 查询决策记录

提供 HTTP 接口查询决策日志和生成审计报告。

Endpoints:
- GET  /api/v1/observability/decisions         - 查询决策记录
- GET  /api/v1/observability/stats             - 获取统计信息
- GET  /api/v1/observability/decision/{id}     - 获取单个决策
- GET  /api/v1/observability/decision-chain/{id} - 获取决策链
- POST /api/v1/observability/flush             - 强制flush缓冲区
- GET  /api/v1/observability/audit             - 生成审计报告
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import logging
import json
from pathlib import Path

from config.observability import DecisionLogger, DecisionType, Decision

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/observability", tags=["observability"])


# ============================================================================
# Request/Response Models
# ============================================================================

class DecisionResponse(BaseModel):
    """决策响应模型"""
    decision_id: str
    decision_type: str
    timestamp: str
    context: Dict[str, Any]
    params_used: Dict[str, Any]
    outcome: Any
    reason: str
    metadata: Dict[str, Any] = {}
    parent_id: Optional[str] = None


class DecisionListResponse(BaseModel):
    """决策列表响应"""
    total: int
    decisions: List[DecisionResponse]


class StatsResponse(BaseModel):
    """统计信息响应"""
    total_logged: int
    buffer_size: int
    by_type: Dict[str, int]
    by_outcome: Dict[str, int]
    log_file: Optional[str]


class AuditReportResponse(BaseModel):
    """审计报告响应"""
    period: str
    total_decisions: int
    by_type: Dict[str, int]
    param_usage: Dict[str, int]
    top_params: List[Dict[str, Any]]
    decision_patterns: List[Dict[str, Any]]
    recommendations: List[str]


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/decisions", response_model=DecisionListResponse)
async def query_decisions(
    decision_type: Optional[str] = Query(None, description="决策类型"),
    start_time: Optional[str] = Query(None, description="开始时间 (ISO 8601)"),
    end_time: Optional[str] = Query(None, description="结束时间 (ISO 8601)"),
    param_name: Optional[str] = Query(None, description="按使用的参数名过滤"),
    limit: int = Query(100, ge=1, le=1000, description="最多返回 N 条")
) -> DecisionListResponse:
    """
    查询决策记录
    
    查询参数：
    - decision_type: 决策类型 (followup_filter, learning_trigger, etc.)
    - start_time: 开始时间 (ISO 8601 格式)
    - end_time: 结束时间
    - param_name: 按使用的参数名过滤
    - limit: 最多返回多少条记录
    
    示例：
        GET /api/v1/observability/decisions
        GET /api/v1/observability/decisions?decision_type=followup_filter
        GET /api/v1/observability/decisions?param_name=followup_coverage_threshold_high
        GET /api/v1/observability/decisions?start_time=2024-01-01T00:00:00Z
    """
    # 解析时间
    start_dt = None
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid start_time format: {start_time}")
    
    end_dt = None
    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid end_time format: {end_time}")
    
    # 解析决策类型
    dt_enum = None
    if decision_type:
        try:
            dt_enum = DecisionType(decision_type)
        except ValueError:
            valid_types = [dt.value for dt in DecisionType]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid decision_type '{decision_type}'. Valid values: {valid_types}"
            )
    
    # 查询
    decisions = DecisionLogger.query(
        decision_type=dt_enum,
        start_time=start_dt,
        end_time=end_dt,
        param_name=param_name,
        limit=limit
    )
    
    # 转换为响应格式
    decision_responses = [
        DecisionResponse(
            decision_id=d.decision_id,
            decision_type=d.decision_type.value if isinstance(d.decision_type, DecisionType) else d.decision_type,
            timestamp=d.timestamp.isoformat(),
            context=d.context,
            params_used=d.params_used,
            outcome=d.outcome,
            reason=d.reason,
            metadata=d.metadata,
            parent_id=d.parent_id
        )
        for d in decisions
    ]
    
    return DecisionListResponse(total=len(decision_responses), decisions=decision_responses)


@router.get("/stats", response_model=StatsResponse)
async def get_stats() -> StatsResponse:
    """
    获取统计信息
    
    返回：
    - 总决策数
    - 缓冲区大小
    - 按类型统计
    - 按结果统计
    - 当前日志文件
    
    示例：
        GET /api/v1/observability/stats
    """
    stats = DecisionLogger.get_stats()
    
    return StatsResponse(
        total_logged=stats["total_logged"],
        buffer_size=stats["buffer_size"],
        by_type=stats["by_type"],
        by_outcome=stats["by_outcome"],
        log_file=stats["log_file"]
    )


@router.get("/decision/{decision_id}", response_model=DecisionResponse)
async def get_decision(decision_id: str) -> DecisionResponse:
    """
    获取单个决策详情
    
    路径参数：
    - decision_id: 决策 ID
    
    示例：
        GET /api/v1/observability/decision/123e4567-e89b-12d3-a456-426614174000
    """
    # 从内存缓冲区查找
    for decision in DecisionLogger._buffer:
        if decision.decision_id == decision_id:
            return DecisionResponse(
                decision_id=decision.decision_id,
                decision_type=decision.decision_type.value if isinstance(decision.decision_type, DecisionType) else decision.decision_type,
                timestamp=decision.timestamp.isoformat(),
                context=decision.context,
                params_used=decision.params_used,
                outcome=decision.outcome,
                reason=decision.reason,
                metadata=decision.metadata,
                parent_id=decision.parent_id
            )
    
    # 从日志文件查找（如果需要）
    # TODO: 实现文件搜索
    
    raise HTTPException(status_code=404, detail=f"Decision '{decision_id}' not found")


@router.get("/decision-chain/{decision_id}")
async def get_decision_chain(decision_id: str) -> Dict[str, Any]:
    """
    获取决策链（包括父决策和子决策）
    
    路径参数：
    - decision_id: 决策 ID
    
    返回：
    - 当前决策
    - 父决策链
    - 子决策链
    
    示例：
        GET /api/v1/observability/decision-chain/123e4567-e89b-12d3-a456-426614174000
    """
    # TODO: 实现决策链追踪
    raise HTTPException(status_code=501, detail="Decision chain tracking not yet implemented")


@router.post("/flush")
async def flush_buffer() -> Dict[str, Any]:
    """
    强制flush缓冲区到文件
    
    用于确保决策记录持久化。
    
    示例：
        POST /api/v1/observability/flush
    """
    buffer_size = len(DecisionLogger._buffer)
    
    DecisionLogger.flush()
    
    return {
        "success": True,
        "flushed": buffer_size,
        "message": f"Flushed {buffer_size} decisions to log file"
    }


@router.get("/audit", response_model=AuditReportResponse)
async def generate_audit_report(
    period: str = Query("24h", description="审计周期: 1h, 24h, 7d, 30d")
) -> AuditReportResponse:
    """
    生成审计报告
    
    查询参数：
    - period: 审计周期（1h, 24h, 7d, 30d）
    
    返回：
    - 时间范围内的决策统计
    - 参数使用频率
    - 决策模式分析
    - 改进建议
    
    示例：
        GET /api/v1/observability/audit
        GET /api/v1/observability/audit?period=7d
    """
    # 解析周期
    period_map = {
        "1h": timedelta(hours=1),
        "24h": timedelta(days=1),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30)
    }
    
    if period not in period_map:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Valid values: {list(period_map.keys())}"
        )
    
    delta = period_map[period]
    start_time = datetime.now() - delta
    
    # 查询决策
    decisions = DecisionLogger.query(start_time=start_time, limit=10000)
    
    # 统计
    by_type = {}
    param_usage = {}
    
    for decision in decisions:
        # 按类型统计
        dt = decision.decision_type.value if isinstance(decision.decision_type, DecisionType) else decision.decision_type
        by_type[dt] = by_type.get(dt, 0) + 1
        
        # 参数使用统计
        for param_name in decision.params_used:
            param_usage[param_name] = param_usage.get(param_name, 0) + 1
    
    # Top 参数
    top_params = sorted(
        [{"param": k, "usage_count": v} for k, v in param_usage.items()],
        key=lambda x: x["usage_count"],
        reverse=True
    )[:10]
    
    # 决策模式分析
    decision_patterns = []
    
    # 检测高频拒绝
    followup_rejected = sum(
        1 for d in decisions
        if d.decision_type == DecisionType.FOLLOWUP_FILTER and d.outcome in (False, "rejected", "reject")
    )
    
    if followup_rejected > len(decisions) * 0.5:
        decision_patterns.append({
            "pattern": "high_followup_rejection_rate",
            "count": followup_rejected,
            "percentage": round(followup_rejected / len(decisions) * 100, 1),
            "severity": "warning"
        })
    
    # 生成建议
    recommendations = []
    
    if followup_rejected > len(decisions) * 0.7:
        recommendations.append(
            "High followup rejection rate (>70%). Consider lowering coverage thresholds."
        )
    
    if "followup_coverage_threshold_high" in param_usage and param_usage["followup_coverage_threshold_high"] > 100:
        recommendations.append(
            "Parameter 'followup_coverage_threshold_high' used frequently. "
            "Consider A/B testing different threshold values."
        )
    
    return AuditReportResponse(
        period=period,
        total_decisions=len(decisions),
        by_type=by_type,
        param_usage=param_usage,
        top_params=top_params,
        decision_patterns=decision_patterns,
        recommendations=recommendations
    )


# ============================================================================
# Helper: 批量查询（内部使用）
# ============================================================================

@router.post("/_batch-query")
async def batch_query_decisions(
    queries: List[Dict[str, Any]]
) -> List[DecisionListResponse]:
    """
    批量查询决策（内部 API）
    
    请求体：
    - queries: 查询条件列表
    
    示例：
        POST /api/v1/observability/_batch-query
        [
          {"decision_type": "followup_filter", "limit": 50},
          {"decision_type": "learning_trigger", "limit": 50}
        ]
    """
    results = []
    
    for query_params in queries:
        dt_enum = None
        if "decision_type" in query_params:
            try:
                dt_enum = DecisionType(query_params["decision_type"])
            except ValueError:
                continue
        
        decisions = DecisionLogger.query(
            decision_type=dt_enum,
            limit=query_params.get("limit", 100)
        )
        
        decision_responses = [
            DecisionResponse(
                decision_id=d.decision_id,
                decision_type=d.decision_type.value if isinstance(d.decision_type, DecisionType) else d.decision_type,
                timestamp=d.timestamp.isoformat(),
                context=d.context,
                params_used=d.params_used,
                outcome=d.outcome,
                reason=d.reason,
                metadata=d.metadata,
                parent_id=d.parent_id
            )
            for d in decisions
        ]
        
        results.append(DecisionListResponse(total=len(decision_responses), decisions=decision_responses))
    
    return results
