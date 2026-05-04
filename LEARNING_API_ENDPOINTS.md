# Learning System API Endpoints (Layer 3)

## Overview

This document describes the complete Learning System API endpoints for the RAG Dashboard. These endpoints enable real-time problem detection, root cause analysis, and automated repair strategy management.

## Base URL

```
http://localhost:8080/api/v1/learning
```

All endpoints are routed through the Go Gateway on port 8080 to the Retrieval Service on port 8002.

## Endpoint Categories

### 1. Signal Collection & Monitoring (2 endpoints)
- `GET /signals` - Get latest aggregated signals
- `GET /signals-summary` - Get signal collection summary

### 2. Problem Detection & Analysis (3 endpoints)
- `GET /problems` - List detected problems
- `POST /analyze-problem` - Deep analyze root cause
- `GET /strategies` - Get repair strategies

### 3. Strategy Management & Approval (5 endpoints)
- `POST /apply-strategy` - Apply repair strategy
- `POST /approve-fix` - Approve fix for execution
- `POST /reject-fix` - Reject fix
- `POST /modify-strategy` - Modify strategy suggestion
- `GET /history` - Get improvement history

### 4. Statistics & Control (3 endpoints)
- `GET /stats` - Get learning system statistics
- `POST /trigger` - Manually trigger learning loop
- `GET /status` - Get learning system status

## Detailed Endpoint Specification

### 1. GET /signals

Get the latest aggregated signals from all 5 signal sources.

**Parameters:**
- `limit` (query, optional, default=100): Maximum number of signals to return

**Response:**
```json
{
  "timestamp": 1714898730000,
  "feedback_signals": [
    {
      "session_id": "sess_123",
      "message_id": "msg_456",
      "rating": 4,
      "tags": ["helpful", "accurate"],
      "feedback_text": "Very helpful response",
      "ts": 1714898720000
    }
  ],
  "failure_signals": [],
  "repeat_signals": [],
  "violation_signals": [],
  "topo_signals": [],
  "total_count": 1,
  "severity_score": 5.5,
  "collection_time_ms": 8.5
}
```

**Status Codes:**
- `200 OK` - Successfully retrieved signals
- `500 Internal Server Error` - Signal collection failed

---

### 2. GET /signals-summary

Get a summary of the signal collection (for dashboard display).

**Response:**
```json
{
  "last_collection": 1714898730000,
  "next_scheduled": 1714898790000,
  "signal_counts": {
    "feedback": 7,
    "failures": 1,
    "repeats": 0,
    "violations": 0,
    "topo": 0
  },
  "severity_trend": [5.5, 6.2, 4.8],
  "health_status": "good"
}
```

**Health Status Values:**
- `good` - severity_score <= 40
- `warning` - 40 < severity_score <= 70
- `critical` - severity_score > 70

**Status Codes:**
- `200 OK` - Successfully retrieved summary
- `500 Internal Server Error` - Summary generation failed

---

### 3. GET /problems

Get list of detected problems with optional filtering.

**Parameters:**
- `status` (query, optional): Filter by status ('open', 'analyzing', 'pending_review')
- `limit` (query, optional, default=50): Maximum number of problems to return

**Response:**
```json
{
  "problems": [
    {
      "problem_id": "prob_001",
      "category": "prompt_issue",
      "severity": "high",
      "affected_route": "R1_navigator_dict",
      "description": "Missing query type classification for price comparisons",
      "confidence": 0.92,
      "created_at": 1714898730000,
      "status": "open",
      "evidence": ["5 consecutive failures", "User feedback: poor results"],
      "additional_context": {}
    }
  ],
  "total": 12,
  "high_count": 4,
  "medium_count": 5,
  "low_count": 3
}
```

**Problem Categories:**
- `prompt_issue` - Issue with query understanding or prompt
- `tool_failure` - Tool or external service failure
- `routing_error` - Query routing to wrong handler
- `low_quality` - Low quality retrieval results
- `diversity_issue` - Insufficient result diversity
- `contract_violation` - Contract verification failure
- `topo_anomaly` - Topology/graph anomaly

**Status Codes:**
- `200 OK` - Successfully retrieved problems
- `500 Internal Server Error` - Problem detection failed

---

### 4. POST /analyze-problem

Deep analyze root cause of a specific problem.

**Request:**
```
POST /api/v1/learning/analyze-problem?problem_id=prob_001
```

**Response:**
```json
{
  "problem_id": "prob_001",
  "root_cause": "Navigator dict missing price comparison query pattern",
  "confidence": 0.88,
  "root_cause_type": "poor_query_understanding",
  "evidence": [
    "5 consecutive failures on price-related queries",
    "All failures point to R1_navigator_dict route",
    "Similar patterns in user feedback"
  ],
  "contributing_factors": [
    "Limited training data for price queries",
    "Rule coverage gap in navigator"
  ],
  "suggested_fixes": [
    "Add rule for price comparison queries",
    "Enhance query classification model"
  ],
  "repair_priority": "high"
}
```

**Root Cause Types:**
- `data_stale` - Outdated or stale data
- `poor_query_understanding` - Query not properly understood
- `suboptimal_ranking` - Results ranked poorly
- `tool_failure` - Tool/service failure
- `insufficient_diversity` - Results lack diversity
- `architecture_flaw` - System architecture issue
- `configuration_error` - Configuration problem
- `external_dependency` - External dependency failure

**Status Codes:**
- `200 OK` - Successfully analyzed root cause
- `404 Not Found` - Problem not found
- `500 Internal Server Error` - Analysis failed

---

### 5. GET /strategies

Get repair strategies for a specific problem.

**Parameters:**
- `problem_id` (query, required): ID of the problem

**Response:**
```json
{
  "problem_id": "prob_001",
  "strategies": [
    {
      "strategy_id": "strat_000",
      "action_type": "prompt_adjustment",
      "description": "Add price comparison query pattern",
      "route": "R1_navigator_dict",
      "risk_level": "low",
      "estimated_impact": 88,
      "decision": "auto_apply"
    },
    {
      "strategy_id": "strat_001",
      "action_type": "ranking_optimization",
      "description": "Enhance query classification model",
      "route": "R1_navigator_dict",
      "risk_level": "medium",
      "estimated_impact": 72,
      "decision": "manual_review"
    }
  ],
  "recommended": "strat_000",
  "all_auto_apply": false
}
```

**Action Types:**
- `data_refresh` - Refresh/update data
- `prompt_adjustment` - Adjust prompts or rules
- `ranking_optimization` - Optimize ranking algorithm
- `tool_upgrade` - Upgrade tool/service
- `diversity_enhancement` - Enhance result diversity
- `architecture_refactor` - Refactor architecture
- `config_fix` - Fix configuration
- `dependency_update` - Update dependency

**Risk Levels:**
- `low` - confidence >= 0.8, safe to auto-apply
- `medium` - 0.6 <= confidence < 0.8, requires review
- `high` - confidence < 0.6, manual verification required

**Status Codes:**
- `200 OK` - Successfully retrieved strategies
- `404 Not Found` - Problem not found
- `500 Internal Server Error` - Strategy generation failed

---

### 6. POST /apply-strategy

Apply a repair strategy.

**Request Body:**
```json
{
  "strategy_id": "strat_001",
  "problem_id": "prob_001",
  "approved_by": null
}
```

**Response:**
```json
{
  "event_id": 1714898730000,
  "strategy_id": "strat_001",
  "problem_id": "prob_001",
  "status": "queued",
  "message": "Queued for auto-execution",
  "run_id": "run_20260505_120000"
}
```

**Event Status:**
- `queued` - Waiting to execute (low-risk auto-apply)
- `approved` - Approved and queued for manual execution

**Status Codes:**
- `200 OK` - Strategy applied successfully
- `500 Internal Server Error` - Application failed

---

### 7. POST /approve-fix

Approve a fix for execution.

**Request Body:**
```json
{
  "event_id": 1714898730000,
  "comments": "Looks good to apply",
  "approved_by": "user@example.com"
}
```

**Response:**
```json
{
  "event_id": 1714898730000,
  "status": "approved",
  "message": "Queued for execution",
  "approved_by": "user@example.com",
  "approved_at": 1714898735000
}
```

**Status Codes:**
- `200 OK` - Fix approved successfully
- `500 Internal Server Error` - Approval failed

---

### 8. POST /reject-fix

Reject a fix.

**Request Body:**
```json
{
  "event_id": 1714898730000,
  "reason": "Too risky, needs more testing",
  "rejected_by": "user@example.com"
}
```

**Response:**
```json
{
  "event_id": 1714898730000,
  "status": "rejected",
  "reason": "Too risky, needs more testing",
  "rejected_by": "user@example.com",
  "rejected_at": 1714898735000
}
```

**Status Codes:**
- `200 OK` - Fix rejected successfully
- `500 Internal Server Error` - Rejection failed

---

### 9. POST /modify-strategy

Modify a strategy suggestion before applying it.

**Request Body:**
```json
{
  "strategy_id": "strat_001",
  "problem_id": "prob_001",
  "modifications": {
    "description": "Modified description",
    "risk_level": "medium"
  }
}
```

**Response:**
```json
{
  "strategy_id": "strat_001_modified_1714898730",
  "problem_id": "prob_001",
  "status": "modified",
  "message": "Strategy modified and ready for re-application",
  "modifications": {
    "description": "Modified description",
    "risk_level": "medium"
  }
}
```

**Status Codes:**
- `200 OK` - Strategy modified successfully
- `500 Internal Server Error` - Modification failed

---

### 10. GET /history

Get improvement history with optional filtering.

**Parameters:**
- `days` (query, optional, default=30): Number of days to look back
- `route` (query, optional): Filter by affected route
- `limit` (query, optional, default=100): Maximum events to return

**Response:**
```json
{
  "period": "last 30 days",
  "events": [
    {
      "event_id": 123,
      "timestamp": 1714898730000,
      "problem_id": "prob_001",
      "route": "R1_navigator_dict",
      "action": "Add price query pattern",
      "status": "verified",
      "before_rate": 0.50,
      "after_rate": 0.75,
      "delta": 0.25,
      "improvement_pct": 50
    }
  ],
  "summary": {
    "total_events": 12,
    "successful": 8,
    "failed": 2,
    "reverted": 2,
    "avg_improvement": 0.15,
    "total_improvement": 1.2
  }
}
```

**Event Status Values:**
- `applied` - Applied to production
- `verified` - Applied and verified working
- `failed` - Application failed
- `reverted` - Applied but then reverted

**Status Codes:**
- `200 OK` - Successfully retrieved history
- `500 Internal Server Error` - History retrieval failed

---

### 11. GET /stats

Get learning system statistics.

**Response:**
```json
{
  "period": "last 30 days",
  "total_problems_detected": 24,
  "problems_resolved": 18,
  "resolution_rate": 0.75,
  "avg_resolution_time": 3600,
  "top_affected_routes": [
    {
      "route": "R1_navigator_dict",
      "problem_count": 8,
      "resolved": 6
    },
    {
      "route": "R2_query_analyzer",
      "problem_count": 5,
      "resolved": 4
    }
  ],
  "effectiveness": {
    "avg_improvement_per_fix": 0.18,
    "total_improvement": 2.88,
    "failed_attempts": 3
  }
}
```

**Status Codes:**
- `200 OK` - Successfully retrieved statistics
- `500 Internal Server Error` - Statistics generation failed

---

### 12. POST /trigger

Manually trigger the learning loop.

**Request Body:**
```json
{
  "reason": "Manual check",
  "force": false
}
```

**Response:**
```json
{
  "run_id": "run_20260505_120000",
  "status": "queued",
  "message": "Learning loop triggered manually",
  "reason": "manual_check",
  "estimated_duration": 300,
  "triggered_at": 1714898730000
}
```

**Status Codes:**
- `200 OK` - Learning loop triggered successfully
- `500 Internal Server Error` - Trigger failed

---

### 13. GET /status

Get current learning system status.

**Response:**
```json
{
  "engine_status": "idle",
  "last_run": 1714898730000,
  "next_scheduled": 1714985130000,
  "pending_approvals": 0,
  "queued_executions": 0,
  "signal_count": 8,
  "severity_score": 5.5,
  "health": "good"
}
```

**Engine Status Values:**
- `idle` - Not currently running
- `running` - Learning loop in progress
- `waiting_approval` - Waiting for manual approval

**Status Codes:**
- `200 OK` - Successfully retrieved status
- `500 Internal Server Error` - Status retrieval failed

---

## Error Handling

All endpoints use standard HTTP status codes:

- `200 OK` - Request successful
- `400 Bad Request` - Invalid parameters
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

Error responses follow this format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

---

## Data Formats

### Timestamps

All timestamps are in **milliseconds since Unix epoch** (1970-01-01). This ensures consistency across JavaScript (frontend) and Python (backend).

Example: `1714898730000` = 2026-05-05 12:00:30 UTC

### Confidence Scores

Confidence scores range from `0` to `1`:
- `0.0` - No confidence
- `0.5` - 50% confidence
- `1.0` - 100% confidence

### Severity Levels

Problems are classified by severity:
- `high` - Critical issue, needs immediate attention
- `medium` - Important issue, should be addressed soon
- `low` - Minor issue, can be addressed later

---

## Integration with Go Gateway

The Go Gateway proxies all `/api/v1/learning/*` requests to the Retrieval Service:

```go
// From proxy.go - route mapping
"/api/v1/learning": "retrieval",
```

This means:
- Frontend requests to `http://localhost:8080/api/v1/learning/signals`
- Are forwarded to `http://localhost:8002/api/v1/learning/signals`
- Where the FastAPI Retrieval Service handles them

---

## Frontend Usage Example

```typescript
// Fetch latest signals from the learning system
const response = await fetch('http://localhost:8080/api/v1/learning/signals');
const data = await response.json();

// Get detected problems
const problemsResponse = await fetch('http://localhost:8080/api/v1/learning/problems?limit=50');
const problems = await problemsResponse.json();

// Analyze specific problem's root cause
const analyzeResponse = await fetch(
  'http://localhost:8080/api/v1/learning/analyze-problem?problem_id=prob_001',
  { method: 'POST' }
);
const rootCause = await analyzeResponse.json();

// Apply a repair strategy
const applyResponse = await fetch(
  'http://localhost:8080/api/v1/learning/apply-strategy',
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      strategy_id: 'strat_001',
      problem_id: 'prob_001'
    })
  }
);
const result = await applyResponse.json();
```

---

## Next Steps

1. ✅ All 13 endpoints implemented in FastAPI
2. ✅ Go Gateway routing configured
3. ✅ Unit tests and validation
4. ⏭️ Integration tests against running services
5. ⏭️ Frontend dashboard integration
6. ⏭️ WebSocket notifications for real-time updates
7. ⏭️ Performance optimization (caching, pagination)

---

## Related Documentation

- [Signal Collection (Layer 2)](./LAYER2_SIGNALS.md)
- [Problem Detection Framework](./PROBLEM_DETECTOR.md)
- [Root Cause Analysis](./ROOT_CAUSE_ANALYZER.md)
- [Go Gateway Routing](../../go-services/internal/gateway/README.md)
