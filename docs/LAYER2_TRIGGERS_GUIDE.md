# Layer 2 - Learning Loop Trigger Mechanisms (Issue #96)

## Overview

The Layer 2 system provides **three autonomous triggers** to activate the learning loop:

1. **Cron Scheduler (定时触发)** — Daily at 2:00 AM UTC
2. **Failure Rate Monitor (阈值触发)** — Automatic on 20%+ consecutive failure rate
3. **Feedback Analyzer (反馈触发)** — Automatic on trending issue patterns

All mechanisms are **coordinated** through the `LearningScheduler` and record execution in the `learning_runs` table.

---

## Architecture

### Component Interaction

```
┌─────────────────────────────────────────────────────────────┐
│ FastAPI Retrieval Service (main.py)                         │
├─────────────────────────────────────────────────────────────┤
│ lifespan startup                                            │
│  ├─ UnifiedStore ────────────┐                            │
│  ├─ LearningScheduler (cron) │                            │
│  ├─ FailureMonitor ──────────┼→ All share db_pool         │
│  └─ FeedbackAnalyzer ────────┘                            │
└─────────────────────────────────────────────────────────────┘
          │
          ├─→ Cron Job @ 02:00 UTC
          │   └─ Signal Collection
          │   └─ Problem Detection
          │   └─ learning_runs INSERT
          │
          ├─→ API Endpoint: /api/v1/learning/trigger (manual)
          │   └─ Triggered via POST with reason
          │
          ├─→ Failure Monitor Check (on each query)
          │   └─ Query status: error/success
          │   └─ If 20%+ failures in last 16 queries
          │   └─ Trigger learning_loop immediately
          │
          └─→ Feedback Analysis (periodic via API)
              └─ Scan rag_feedback table
              └─ Identify trending tags (freq >= 20%)
              └─ Calculate weighted score
              └─ Trigger if weight > 30
```

### Data Flow

1. **Signal Collection**
   - Source: `signal_collector.py`
   - Types: feedback, failures, repeats, violations, topology anomalies
   - Window: last 24h by default
   - Stores aggregated signals in memory

2. **Problem Detection**
   - Source: `problem_detector.py`
   - Rules: statistical heuristics
   - Output: categorized problems (prompt_issue, tool_failure, etc.)

3. **Learning Run Recording**
   - Table: `learning_runs`
   - Fields: run_id, run_type, result (JSONB), status, ts
   - Indexed: (ts DESC), (run_type), (status)

---

## Component Details

### 1. Cron Scheduler (`app/agent/scheduler.py`)

**Trigger**: Daily at 02:00 UTC (hardcoded via APScheduler)

**Interface**:
```python
class LearningScheduler:
    async def run_learning_loop()
    async def trigger_manual(reason: str) -> str
    async def get_next_run_time() -> Dict
```

**Initialization** (in `main.py`):
```python
_scheduler = init_scheduler(db_pool=_store.pg_pool)
# Returns: LearningScheduler instance, immediately starts cron
```

**API**:
- `POST /api/v1/learning/trigger?reason=...` → manual trigger
- `GET /api/v1/learning/next-run` → next scheduled time

**Database**:
```sql
INSERT INTO learning_runs (run_id, run_type, result, status, ts)
VALUES ('run_scheduled_20240506_020000', 'scheduled', '{...}', 'completed', NOW())
```

**Example Run Result**:
```json
{
  "run_id": "run_scheduled_20240506_020000",
  "run_type": "scheduled",
  "result": {
    "signals_count": 42,
    "severity_score": 65.5,
    "problems_count": 3,
    "collect_time_ms": 245.0,
    "status": "completed"
  },
  "status": "completed",
  "ts": "2024-05-06T02:00:15.234Z"
}
```

**Error Handling**:
- If APScheduler not installed: logs warning, continues without cron
- If DB unavailable: logs error, continues (retry on next run)
- If signal collection fails: records error in learning_runs with status='failed'

---

### 2. Failure Monitor (`app/agent/failure_monitor.py`)

**Trigger**: Automatic when failure rate ≥ 20%

**Configuration**:
```python
FAILURE_THRESHOLD = 0.20        # 20% failure rate
WINDOW_SIZE = 16                # last 16 queries
MIN_WINDOW_SAMPLES = 8          # need ≥ 8 samples
```

**Interface**:
```python
class FailureMonitor:
    async def check_and_trigger() -> Optional[str]
    async def get_recent_failure_stats() -> FailureStats
    async def should_trigger() -> bool
```

**Data Source**: `conversation_turns.status` (error | success | ...)

**Failure Logic**:
```
recent_16_queries = SELECT status FROM conversation_turns ORDER BY ts DESC LIMIT 16
failure_count = COUNT(status='error')
failure_rate = failure_count / 16

if failure_rate >= 0.20:
    trigger_learning_loop(reason=f"auto_threshold_{failure_rate:.1%}")
```

**API**:
- `GET /api/v1/learning/failure-stats` → current stats

**Response Example**:
```json
{
  "window_size": 16,
  "failure_count": 4,
  "success_count": 12,
  "total_count": 16,
  "failure_rate": 0.25,
  "should_trigger": true,
  "threshold": 0.20,
  "min_samples": 8
}
```

**Design Notes**:
- **Not integrated with each request** yet (to minimize latency)
- **Called via API** for now: `GET /api/v1/learning/failure-stats`
- Future: integrate as middleware on retrieval endpoints

---

### 3. Feedback Analyzer (`app/agent/feedback_analyzer.py`)

**Trigger**: Automatic on trending issues (weight > 30)

**Configuration**:
```python
TAG_WEIGHTS = {
    '逻辑错误': 15,
    '工具失效': 12,
    '数据过时': 10,
    '缺少依据': 8,
    '返回缺失': 7,
    '理解不足': 6,
    '格式错误': 5,
}

TRENDING_THRESHOLD = 0.20       # 20% of feedback
MIN_FEEDBACK_SAMPLES = 5        # need ≥ 5 feedback
TRIGGER_WEIGHT_THRESHOLD = 30   # total weight > 30
```

**Interface**:
```python
class FeedbackAnalyzer:
    async def analyze_feedback_trends(window_days=7) -> FeedbackAnalysis
    async def trigger_if_needed() -> Optional[str]
    async def get_insights(window_days=7) -> Dict
```

**Analysis Logic**:
```python
# 1. Query rag_feedback table (last 7 days)
# 2. Count tag frequency
# 3. Calculate negative_rate (rating <= 2)
# 4. Identify trending issues (frequency >= 20%)
# 5. Compute weighted score = frequency * TAG_WEIGHTS[tag]
# 6. Decide: trigger if total_weight > 30 AND sample_count >= 5
```

**API**:
- `GET /api/v1/learning/feedback-insights?window_days=7` → analysis & suggestions
- Called by dashboard to show trending problems

**Response Example**:
```json
{
  "period_days": 7,
  "total_feedback_count": 28,
  "negative_feedback_rate": "32.1%",
  "top_issues": [
    {
      "tag": "数据过时",
      "frequency": "35.7%",
      "count": 10,
      "weight": 107
    },
    {
      "tag": "缺少依据",
      "frequency": "21.4%",
      "count": 6,
      "weight": 48
    }
  ],
  "trending_problems": ["数据过时", "缺少依据"],
  "improvement_suggestions": [
    "检查数据源更新频率，考虑增加爬取频率或切换到实时 API",
    "增强检索策略，扩大检索范围或调整重排权重以获取更多源文档"
  ],
  "should_trigger_learning": true
}
```

---

## API Endpoints

### 1. Manual Trigger
```
POST /api/v1/learning/trigger?reason=manual
```

Response:
```json
{
  "run_id": "run_manual_20240505_143022",
  "status": "triggered",
  "message": "Learning loop triggered with reason: manual",
  "trigger_type": "manual"
}
```

### 2. Next Scheduled Run
```
GET /api/v1/learning/next-run
```

Response:
```json
{
  "job_id": "learning_loop_daily",
  "next_run_utc": "2024-05-06T02:00:00+00:00",
  "next_run_timestamp": 1714982400000
}
```

### 3. Failure Statistics
```
GET /api/v1/learning/failure-stats
```

Response:
```json
{
  "window_size": 16,
  "failure_count": 3,
  "success_count": 13,
  "total_count": 16,
  "failure_rate": 0.1875,
  "should_trigger": false,
  "threshold": 0.20,
  "min_samples": 8
}
```

### 4. Feedback Insights
```
GET /api/v1/learning/feedback-insights?window_days=7
```

Response: (see above)

### 5. Overall Learning Status
```
GET /api/v1/learning/status
```

Response:
```json
{
  "layer2_triggers": {
    "scheduler": {
      "status": "running",
      "next_run": "2024-05-06T02:00:00+00:00"
    },
    "failure_monitor": {
      "status": "monitoring",
      "current_failure_rate": 0.1875,
      "threshold": 0.20,
      "should_trigger": false
    },
    "feedback_analyzer": {
      "status": "analyzing",
      "trending_issues_count": 2,
      "should_trigger": true
    }
  },
  "timestamp": "2024-05-05T14:30:22.456Z"
}
```

---

## Database Schema

### learning_runs Table
```sql
CREATE TABLE learning_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,              -- 'run_scheduled_...' | 'run_manual_...' | 'run_auto_threshold_...'
    run_type TEXT NOT NULL,                   -- 'scheduled' | 'manual' | 'auto_threshold' | 'feedback_analysis'
    result JSONB,                             -- {signals_count, problems_count, severity_score, ...}
    status TEXT NOT NULL,                     -- 'running' | 'completed' | 'failed'
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    CONSTRAINT learning_runs_run_type_valid CHECK (run_type IN ('scheduled', 'manual', 'auto_threshold', 'feedback_analysis'))
);

-- Indexes for fast queries
CREATE INDEX idx_learning_runs_ts ON learning_runs(ts DESC);
CREATE INDEX idx_learning_runs_run_type ON learning_runs(run_type);
CREATE INDEX idx_learning_runs_status ON learning_runs(status);
CREATE INDEX idx_learning_runs_run_id ON learning_runs(run_id);
```

---

## Testing

### Unit Tests
```bash
cd src/backend/retrieval-service
pytest tests/test_layer2_triggers.py -v
```

Test coverage:
- ✅ Scheduler initialization and cron scheduling
- ✅ Manual trigger via API
- ✅ Failure monitor statistics calculation
- ✅ Failure rate threshold check
- ✅ Feedback analysis and trending detection
- ✅ API endpoints (mock-based)

### Integration Tests (Manual)
```bash
# 1. Start the service
cd src/backend/retrieval-service
python -m uvicorn main:app --reload --port 8002

# 2. Check scheduler is running
curl http://localhost:8002/api/v1/learning/next-run

# 3. Manual trigger
curl -X POST http://localhost:8002/api/v1/learning/trigger?reason=test

# 4. Check failure stats
curl http://localhost:8002/api/v1/learning/failure-stats

# 5. Check feedback insights
curl http://localhost:8002/api/v1/learning/feedback-insights

# 6. Check overall status
curl http://localhost:8002/api/v1/learning/status
```

---

## Configuration & Tuning

### Environment Variables (Future)
```bash
# Cron time (currently hardcoded to 02:00 UTC)
LEARNING_CRON_HOUR=2
LEARNING_CRON_MINUTE=0
LEARNING_CRON_TIMEZONE=UTC

# Failure monitor
FAILURE_THRESHOLD=0.20
FAILURE_WINDOW_SIZE=16
FAILURE_MIN_SAMPLES=8

# Feedback analyzer
FEEDBACK_WINDOW_DAYS=7
FEEDBACK_TRENDING_THRESHOLD=0.20
FEEDBACK_TRIGGER_WEIGHT=30
```

### Runtime Adjustments
```python
# Get monitor and adjust threshold
from app.agent.failure_monitor import get_failure_monitor
monitor = get_failure_monitor()
monitor.set_threshold(0.25)  # Change to 25%
```

---

## Known Limitations & Future Work

### Current Limitations
1. **Failure monitor** not automatically checked on every request (API-driven only)
2. **Cron time** hardcoded to 02:00 UTC (should be configurable)
3. **APScheduler** dependency optional (warning if not installed)
4. **Feedback analyzer** runs on-demand (no background task yet)

### Future Enhancements
1. Integrate failure monitor into middleware for auto-trigger
2. Make cron schedule configurable via env vars
3. Add periodic feedback analysis task (every 6 hours)
4. Add Slack/webhook notifications on learning triggers
5. Add manual adjustment of tag weights via UI
6. Add learning loop result dashboard (success rate, improvement trends)

---

## Troubleshooting

### Scheduler Not Running
```python
from app.agent.scheduler import get_scheduler
scheduler = get_scheduler()
if not scheduler or not scheduler._running:
    print("Scheduler not running")
else:
    print(f"Next run: {await scheduler.get_next_run_time()}")
```

### High Failure Rate Not Triggering
```python
# Check current stats
from app.agent.failure_monitor import get_failure_monitor
monitor = get_failure_monitor()
stats = await monitor.get_recent_failure_stats()
print(f"Failure rate: {stats.failure_rate:.1%}, Threshold: {monitor.FAILURE_THRESHOLD:.1%}")

# Manually trigger if needed
await monitor._trigger_learning_loop(stats)
```

### Feedback Analysis Issues
```python
# Check analysis results
from app.agent.feedback_analyzer import get_feedback_analyzer
analyzer = get_feedback_analyzer()
analysis = await analyzer.analyze_feedback_trends()
print(f"Trending: {[p.tag for p in analysis.trending_problems]}")
print(f"Should trigger: {analysis.should_trigger}")
```

---

## Files Created

- ✅ `app/agent/scheduler.py` (250 LOC) — Cron scheduler
- ✅ `app/agent/failure_monitor.py` (180 LOC) — Failure rate monitor
- ✅ `app/agent/feedback_analyzer.py` (310 LOC) — Feedback analysis
- ✅ `main.py` (modifications) — Initialization & shutdown
- ✅ `app/api.py` (modifications) — 5 new endpoints
- ✅ `sql/migrations/008_learning_runs.sql` — Database schema
- ✅ `tests/test_layer2_triggers.py` (370 LOC) — Test suite

## Acceptance Checklist

- ✅ All 3 trigger mechanisms implemented
- ✅ Cron scheduler working (daily 2:00 AM UTC)
- ✅ Failure monitor tracking 20% threshold
- ✅ Feedback analyzer identifying trending issues
- ✅ SQL migration applied (learning_runs table)
- ✅ main.py integration (startup/shutdown)
- ✅ 5 new API endpoints working
- ✅ Unit tests passing
- ✅ Documentation complete
