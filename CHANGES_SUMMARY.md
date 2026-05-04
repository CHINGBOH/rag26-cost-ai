# Issue #96 修复 - 代码修改摘要

## 1. 后端 API 修改 (src/backend/retrieval-service/app/api.py)

### 修改 1a: learning_runs() 函数 - 时间戳转换
**位置**: 第 1266-1270 行
**修改前**:
```python
@router.get("/api/v1/learning/runs")
async def learning_runs(limit: int = 50, quality: Optional[str] = None):
    """Recent agent runs from JSONL log. Filter by quality=failure|weak|good."""
    runs = _read_jsonl(_os_learn.path.join(_LEARN_DIR, "agent_runs.jsonl"), limit=max(limit * 4, 200))
    if quality:
        runs = [r for r in runs if r.get("quality") == quality]
    runs.reverse()  # newest first
    return {"runs": runs[:limit], "total_in_window": len(runs)}
```

**修改后**:
```python
@router.get("/api/v1/learning/runs")
async def learning_runs(limit: int = 50, quality: Optional[str] = None):
    """Recent agent runs from JSONL log. Filter by quality=failure|weak|good."""
    runs = _read_jsonl(_os_learn.path.join(_LEARN_DIR, "agent_runs.jsonl"), limit=max(limit * 4, 200))
    if quality:
        runs = [r for r in runs if r.get("quality") == quality]
    runs.reverse()  # newest first
    # Convert ts from Unix seconds to milliseconds for frontend
    for run in runs[:limit]:
        if run.get('ts') and isinstance(run['ts'], (int, float)):
            run['ts'] = int(run['ts'] * 1000)
    return {"runs": runs[:limit], "total_in_window": len(runs)}
```

---

### 修改 1b: learning_gaps() 函数 - 添加 status 字段和时间戳转换
**位置**: 第 1317-1350 行
**修改前**:
```python
@router.get("/api/v1/learning/gaps")
async def learning_gaps(limit: int = 30):
    """Distinct failed/weak queries — surface knowledge gaps."""
    runs = _read_jsonl(_os_learn.path.join(_LEARN_DIR, "agent_runs.jsonl"), limit=500)
    seen: set[str] = set()
    gaps: list[dict] = []
    for r in reversed(runs):
        if r.get("quality") not in ("failure", "weak"):
            continue
        q = (r.get("query") or "").strip()
        if not q or q in seen:
            continue
        seen.add(q)
        gaps.append({
            "query": q,
            "ts": r.get("ts"),
            "quality": r.get("quality"),
            "refused": bool(r.get("refused")),
            "chunks_count": r.get("chunks_count", 0),
            "confidence": (r.get("evaluation") or {}).get("confidence", 0),
            "answer_preview": (r.get("answer") or "")[:200],
        })
        if len(gaps) >= limit:
            break
    return {"gaps": gaps}
```

**修改后**:
```python
@router.get("/api/v1/learning/gaps")
async def learning_gaps(limit: int = 30):
    """Distinct failed/weak queries — surface knowledge gaps."""
    runs = _read_jsonl(_os_learn.path.join(_LEARN_DIR, "agent_runs.jsonl"), limit=500)
    seen: set[str] = set()
    gaps: list[dict] = []
    for r in reversed(runs):
        if r.get("quality") not in ("failure", "weak"):
            continue
        q = (r.get("query") or "").strip()
        if not q or q in seen:
            continue
        seen.add(q)
        # Map quality to status: failure → open, weak → in_progress
        quality = r.get("quality", "unknown")
        status = "open" if quality == "failure" else "in_progress" if quality == "weak" else "open"
        ts = r.get("ts")
        # Convert ts from Unix seconds to milliseconds
        if ts and isinstance(ts, (int, float)):
            ts = int(ts * 1000)
        gaps.append({
            "query": q,
            "ts": ts,
            "quality": quality,
            "status": status,
            "refused": bool(r.get("refused")),
            "chunks_count": r.get("chunks_count", 0),
            "confidence": (r.get("evaluation") or {}).get("confidence", 0),
            "answer_preview": (r.get("answer") or "")[:200],
        })
        if len(gaps) >= limit:
            break
    return {"gaps": gaps}
```

---

### 修改 1c: learning_conversations() 函数 - 时间戳转换
**位置**: 第 1376-1378 行
**修改前**:
```python
        finally:
            await conn.close()
        turns = [dict(r) for r in rows]
        return {"turns": turns, "total": len(turns)}
```

**修改后**:
```python
        finally:
            await conn.close()
        turns = [dict(r) for r in rows]
        # Convert ts from Unix seconds to milliseconds for frontend
        for turn in turns:
            if turn.get('ts'):
                turn['ts'] = int(turn['ts'] * 1000)
        return {"turns": turns, "total": len(turns)}
```

---

### 修改 1d: learning_feedback_stats() 函数 - 时间戳转换
**位置**: 第 1413-1415 行
**修改前**:
```python
        finally:
            await conn.close()
        records = [dict(r) for r in rows]
        trend = [{"day": str(r["day"])[:10], "positive": r["positive"], "total": r["total"]} for r in trend_rows]
```

**修改后**:
```python
        finally:
            await conn.close()
        records = [dict(r) for r in rows]
        # Convert ts from Unix seconds to milliseconds for frontend
        for record in records:
            if record.get('ts'):
                record['ts'] = int(record['ts'] * 1000)
        trend = [{"day": str(r["day"])[:10], "positive": r["positive"], "total": r["total"]} for r in trend_rows]
```

---

## 2. 前端接口定义修改 (src/frontend/web/src/services/metricsApi.ts)

### 修改 2a: ConversationTurn 接口
**位置**: 第 91 行
**修改前**:
```typescript
export interface ConversationTurn {
  id: number;
  session_id: string;
  turn_index: number;
  user_content: string;
  assistant_content: string;
  source: string;
  status: string;
  latency_ms: number | null;
  ts: string;
}
```

**修改后**:
```typescript
export interface ConversationTurn {
  id: number;
  session_id: string;
  turn_index: number;
  user_content: string;
  assistant_content: string;
  source: string;
  status: string;
  latency_ms: number | null;
  ts: number | string;
}
```

---

### 修改 2b: FeedbackRecord 接口
**位置**: 第 95 行
**修改前**:
```typescript
export interface FeedbackRecord {
  ts: string;
  session_id: string;
  // ... 其他字段
}
```

**修改后**:
```typescript
export interface FeedbackRecord {
  ts: number | string;
  session_id: string;
  // ... 其他字段
}
```

---

### 修改 2c: LearningRun 接口
**位置**: 第 162 行
**修改前**:
```typescript
export interface LearningRun {
  ts: string;
  query: string;
  // ... 其他字段
}
```

**修改后**:
```typescript
export interface LearningRun {
  ts: number | string;
  query: string;
  // ... 其他字段
}
```

---

### 修改 2d: LearningGap 接口 (新增 status 字段)
**位置**: 第 190-199 行
**修改前**:
```typescript
export interface LearningGap {
  query: string;
  ts: string;
  quality: string;
  refused: boolean;
  chunks_count: number;
  confidence: number;
  answer_preview: string;
}
```

**修改后**:
```typescript
export interface LearningGap {
  query: string;
  ts: number | string;
  quality: string;
  status: string;
  refused: boolean;
  chunks_count: number;
  confidence: number;
  answer_preview: string;
}
```

---

### 修改 2e: LearningEngineStatus 接口
**位置**: 第 463 行
**修改前**:
```typescript
export interface LearningEngineStatus {
  // ...
  last_run: {
    ts?: string;
    file?: string;
    // ...
  };
  // ...
}
```

**修改后**:
```typescript
export interface LearningEngineStatus {
  // ...
  last_run: {
    ts?: number | string;
    file?: string;
    // ...
  };
  // ...
}
```

---

## 3. 前端 React 组件修改 (src/frontend/web/src/pages/LearningPage.tsx)

### 修改 3: 知识缺口列表显示 - 添加状态标记
**位置**: 第 154-164 行
**修改前**:
```jsx
<div className="gap-meta">
  <span className={`badge q-${g.quality}`}>{QUALITY_ZH[g.quality] ?? g.quality}</span>
  {g.refused && <span className="badge refused">拒答</span>}
  <span className="muted small">片段 {g.chunks_count}</span>
  <span className="muted small">置信 {g.confidence.toFixed(2)}</span>
  <span className="muted small">{fmtDateTime(g.ts)}</span>
</div>
```

**修改后**:
```jsx
<div className="gap-meta">
  <span className={`badge q-${g.quality}`}>{QUALITY_ZH[g.quality] ?? g.quality}</span>
  {g.status === 'resolved' && <span className="badge status-resolved">✅ 已解决</span>}
  {g.status === 'in_progress' && <span className="badge status-in-progress">🔄 处理中</span>}
  {g.status === 'open' && <span className="badge status-open">❌ 未开始</span>}
  {g.status === 'blocked' && <span className="badge status-blocked">🚫 被阻止</span>}
  {g.refused && <span className="badge refused">拒答</span>}
  <span className="muted small">片段 {g.chunks_count}</span>
  <span className="muted small">置信 {g.confidence.toFixed(2)}</span>
  <span className="muted small">{fmtDateTime(g.ts)}</span>
</div>
```

---

## 4. 前端样式表修改 (src/frontend/web/src/pages/LearningPage.css)

### 修改 4: 添加状态标记样式
**位置**: 第 48-51 行 (在 badge 样式之后)
**修改前**:
```css
.badge.q-good    { background: rgba(16,185,129,0.15); color: #10b981; }
.badge.q-weak    { background: rgba(245,158,11,0.15); color: #f59e0b; }
.badge.q-failure { background: rgba(220,38,38,0.15); color: #dc2626; }
.badge.refused   { background: rgba(220,38,38,0.15); color: #dc2626; }

.bar-list { list-style: none; margin: 0; padding: 0; }
```

**修改后**:
```css
.badge.q-good    { background: rgba(16,185,129,0.15); color: #10b981; }
.badge.q-weak    { background: rgba(245,158,11,0.15); color: #f59e0b; }
.badge.q-failure { background: rgba(220,38,38,0.15); color: #dc2626; }
.badge.refused   { background: rgba(220,38,38,0.15); color: #dc2626; }
.badge.status-resolved { background: rgba(16,185,129,0.15); color: #10b981; font-size: 12px; text-transform: none; }
.badge.status-in-progress { background: rgba(245,158,11,0.15); color: #f59e0b; font-size: 12px; text-transform: none; }
.badge.status-open { background: rgba(220,38,38,0.15); color: #dc2626; font-size: 12px; text-transform: none; }
.badge.status-blocked { background: rgba(107,114,128,0.15); color: #6b7280; font-size: 12px; text-transform: none; }

.bar-list { list-style: none; margin: 0; padding: 0; }
```

---

## 修改总结

| 文件 | 修改类型 | 行号 | 描述 |
|------|--------|------|------|
| api.py | 时间戳转换 | 1266-1270 | learning_runs() 添加 ts 转换 |
| api.py | 状态字段+转换 | 1334-1344 | learning_gaps() 添加 status 和 ts 转换 |
| api.py | 时间戳转换 | 1376-1378 | learning_conversations() 添加 ts 转换 |
| api.py | 时间戳转换 | 1413-1415 | learning_feedback_stats() 添加 ts 转换 |
| metricsApi.ts | 接口更新 | 91, 95, 162, 194, 463 | ts 类型更新，status 字段新增 |
| LearningPage.tsx | UI 显示 | 154-164 | 添加状态标记显示 |
| LearningPage.css | 样式 | 48-51 | 添加 4 个状态样式 |

---

**总代码行数变化**: +50 行代码修改
**测试覆盖**: Python 语法检查 ✓, TypeScript 编译 ✓

