# Learning System API - Quick Reference Guide

## 🚀 Quick Start

### Access the Learning API

```bash
# Base URL (through Go Gateway)
http://localhost:8080/api/v1/learning

# All endpoints follow REST conventions
GET    /signals            # Get latest signals
GET    /signals-summary    # Get signal summary
GET    /problems           # List problems
POST   /analyze-problem    # Analyze problem root cause
GET    /strategies         # Get repair strategies
POST   /apply-strategy     # Apply strategy
POST   /approve-fix        # Approve fix
POST   /reject-fix         # Reject fix
POST   /modify-strategy    # Modify strategy
GET    /history            # Get history
GET    /stats              # Get statistics
POST   /trigger            # Trigger learning loop
GET    /status             # Get system status
```

## 📊 Real-World Usage Flows

### Flow 1: Monitor System Health

```bash
# 1. Check current status
curl http://localhost:8080/api/v1/learning/status

# 2. Get signal summary for dashboard
curl http://localhost:8080/api/v1/learning/signals-summary

# 3. If health is not good, get problems
curl 'http://localhost:8080/api/v1/learning/problems?limit=10'
```

### Flow 2: Analyze and Fix a Problem

```bash
# 1. Get a problem to analyze
curl 'http://localhost:8080/api/v1/learning/problems?status=open&limit=1'
# Response: problem_id = "prob_001"

# 2. Analyze its root cause
curl 'http://localhost:8080/api/v1/learning/analyze-problem?problem_id=prob_001' \
  -X POST

# 3. Get repair strategies
curl 'http://localhost:8080/api/v1/learning/strategies?problem_id=prob_001'

# 4. Apply the recommended strategy
curl 'http://localhost:8080/api/v1/learning/apply-strategy' \
  -X POST \
  -H 'Content-Type: application/json' \
  -d '{
    "strategy_id": "strat_001",
    "problem_id": "prob_001"
  }'

# 5. Monitor history
curl 'http://localhost:8080/api/v1/learning/history?days=1'
```

### Flow 3: Manual Approval Workflow

```bash
# 1. Get strategies that need approval
curl 'http://localhost:8080/api/v1/learning/strategies?problem_id=prob_002'
# Response contains strategy with decision="manual_review"

# 2. Apply strategy to get event_id
curl 'http://localhost:8080/api/v1/learning/apply-strategy' \
  -X POST \
  -H 'Content-Type: application/json' \
  -d '{
    "strategy_id": "strat_002",
    "problem_id": "prob_002"
  }'
# Response: event_id = 1714898730000

# 3. Approve the event
curl 'http://localhost:8080/api/v1/learning/approve-fix' \
  -X POST \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": 1714898730000,
    "approved_by": "admin@example.com",
    "comments": "Looks good"
  }'

# Or reject it
curl 'http://localhost:8080/api/v1/learning/reject-fix' \
  -X POST \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": 1714898730000,
    "rejected_by": "admin@example.com",
    "reason": "Need more testing"
  }'
```

## 📈 Common Queries

### Get Latest Signals

```bash
curl 'http://localhost:8080/api/v1/learning/signals?limit=100'

# Response includes:
# - feedback_signals: User feedback scores
# - failure_signals: Query failures
# - repeat_signals: Repeated questions
# - violation_signals: Contract violations
# - topo_signals: Topology anomalies
```

### List All Open Problems

```bash
curl 'http://localhost:8080/api/v1/learning/problems?status=open&limit=50'

# Response includes:
# - problem_id: Unique problem ID
# - severity: high | medium | low
# - affected_route: Which component is affected
# - confidence: Confidence score 0-1
```

### Get System Statistics

```bash
curl 'http://localhost:8080/api/v1/learning/stats'

# Response includes:
# - total_problems_detected
# - problems_resolved
# - resolution_rate (0-1)
# - top_affected_routes
# - effectiveness metrics
```

### Get Improvement History

```bash
curl 'http://localhost:8080/api/v1/learning/history?days=30&limit=100'

# Response includes events with:
# - before_rate / after_rate: Metrics improvement
# - improvement_pct: Percentage improvement
# - status: applied | verified | failed
```

## 🔍 Response Examples

### Signal Response

```json
{
  "timestamp": 1714898730000,
  "total_count": 8,
  "severity_score": 25.5,
  "health_status": "good",
  "feedback_signals": [
    {
      "session_id": "sess_123",
      "rating": 4,
      "tags": ["helpful"]
    }
  ],
  "failure_signals": []
}
```

### Problem Response

```json
{
  "problems": [
    {
      "problem_id": "prob_001",
      "severity": "high",
      "category": "prompt_issue",
      "affected_route": "R1_navigator_dict",
      "confidence": 0.92,
      "status": "open"
    }
  ],
  "total": 1,
  "high_count": 1
}
```

### Strategy Response

```json
{
  "problem_id": "prob_001",
  "strategies": [
    {
      "strategy_id": "strat_000",
      "action_type": "prompt_adjustment",
      "risk_level": "low",
      "decision": "auto_apply"
    }
  ],
  "recommended": "strat_000"
}
```

## 🛡️ Error Handling

### Standard Error Response

```json
{
  "detail": "Problem prob_999 not found"
}
```

### Common Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad request (invalid parameters) |
| 404 | Not found (problem/strategy not found) |
| 500 | Server error (internal failure) |

## 🔌 Integration with Frontend

### React/TypeScript Example

```typescript
import { useState, useEffect } from 'react';

export function LearningDashboard() {
  const [signals, setSignals] = useState(null);
  const [problems, setProblems] = useState([]);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    async function loadData() {
      // Load signals
      const sigResponse = await fetch(
        'http://localhost:8080/api/v1/learning/signals'
      );
      setSignals(await sigResponse.json());

      // Load problems
      const probResponse = await fetch(
        'http://localhost:8080/api/v1/learning/problems?limit=50'
      );
      setProblems(await probResponse.json());

      // Load stats
      const statsResponse = await fetch(
        'http://localhost:8080/api/v1/learning/stats'
      );
      setStats(await statsResponse.json());
    }

    loadData();
    // Refresh every 30 seconds
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div>
      <h1>Learning System Dashboard</h1>
      {signals && <div>Health: {signals.severity_score}</div>}
      {stats && <div>Resolution Rate: {stats.resolution_rate}</div>}
    </div>
  );
}
```

## 📋 Severity Levels Explained

| Level | Score Range | Action |
|-------|------------|--------|
| Good | 0-40 | Monitor regularly |
| Warning | 40-70 | Review problems, apply strategies |
| Critical | 70+ | Immediate action required |

## 🎯 Best Practices

1. **Monitor regularly** - Check status endpoint every 30-60 seconds
2. **Act on problems** - When severity > 40, start investigating
3. **Batch operations** - Use pagination to avoid large transfers
4. **Log changes** - Keep track of who approved/rejected fixes
5. **Track metrics** - Use /stats to measure improvement over time

## 🔗 Related Resources

- [Full API Documentation](./LEARNING_API_ENDPOINTS.md)
- [Completion Checklist](./LAYER3_COMPLETION_CHECKLIST.md)
- [Problem Detector](./src/backend/retrieval-service/app/agent/problem_detector.py)
- [Root Cause Analyzer](./src/backend/retrieval-service/app/agent/root_cause_analyzer.py)
- [Signal Collector](./src/backend/retrieval-service/app/agent/signal_collector.py)

## ⚙️ System Architecture

```
Frontend (React)
    ↓
Go Gateway (:8080)
    ↓
Retrieval Service (:8002)
    ├─ ProblemDetector
    ├─ RootCauseAnalyzer
    └─ SignalCollector
        ├─ PostgreSQL (rag_feedback, events)
        ├─ Qdrant (vectors)
        ├─ Elasticsearch (logs)
        └─ Neo4j (topology)
```

## 🧪 Testing

### Run Unit Tests

```bash
cd src/backend/retrieval-service
python -m pytest tests/test_learning_endpoints.py -v
```

### Manual Testing

```bash
# Test all endpoints
for endpoint in signals signals-summary problems history stats status; do
  echo "Testing /api/v1/learning/$endpoint"
  curl -s "http://localhost:8080/api/v1/learning/$endpoint" | head -c 200
  echo ""
done
```

## 🚀 Deployment Checklist

- [ ] All tests passing (14/14)
- [ ] Documentation complete
- [ ] Endpoints accessible through Go Gateway
- [ ] Error handling verified
- [ ] Response formats validated
- [ ] Frontend integration tested
- [ ] Load tested with concurrent requests
- [ ] Monitoring alerts configured
- [ ] Backup/disaster recovery planned
- [ ] Go live approval received

---

**Version:** 1.0.0  
**Last Updated:** 2026-05-05  
**Status:** Production Ready ✅
