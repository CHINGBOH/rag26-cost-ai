# T8 — 后端 API 收敛迁移矩阵

> 跟踪：#134 子任务 S1（盘点 + 影响分析）
> 生成时间：2026-05-12
> 范围：`/api/v1/learning/*`

## 一句话总结

后端实际 **36 个** learning 端点（含 6 个 #133 主 issue 没列出的：`stats / status / next-run / trigger / failure-stats / feedback-insights`），前端 `metricsApi.ts` 21 个公共函数 + 2 处 TSX 内直接 fetch（`conversations`），后端测试 3 个文件大量引用，文档 5 个文件示例几十处，CLI 调 3 个端点。Grafana / Go 网关均不引用具体端点（已通过前缀代理）。

## 现状盘点

| 维度 | 数量 |
|---|---|
| 后端 `@router` 端点 | **36** |
| 前端 `metricsApi.ts` 调用函数 | 21 |
| 前端组件内直接 fetch（绕过 metricsApi） | 2（`SystemAssistant.tsx` + `GuideHistoryPanel.tsx`，都调 `/conversations`） |
| 后端测试文件 | 3（`test_learning_endpoints.py` / `test_learning_runs_unified_api.py` / `test_layer2_triggers.py`） |
| 顶层 `tests/` 引用 | 4（`test_dashboard_api.py` / `test_dashboard_frontend_integration.sh` / `e2e_test_report_final.json` / `E2E_TEST_REPORT.md`） |
| 文档 `.md` 引用 | 5+（`LEARNING_API_QUICK_REFERENCE.md` / `QUICK_START_LEARNING.md` / `LEARNING_API_ENDPOINTS.md` / `TROUBLESHOOTING_LEARNING.md` / `API_REFERENCE_LEARNING.md` / `ISSUE_96_*` 历史文档） |
| CLI 引用 | 1（`learning_cli.py` 调 3 个 gap 端点） |
| Grafana 引用 | 0 |
| Go 网关引用 | 0（按前缀代理，不依赖具体端点） |

## 完整迁移矩阵

> 列说明：
> - **新端点**：T8 收敛后的目标
> - **前端调用**：metricsApi.ts 中的 export 函数 + 直接 fetch 位置
> - **后端测试**：会被影响的 pytest 文件
> - **文档**：会被影响的 .md 文件
> - **CLI**：是否被 `learning_cli.py` 调用
> - **风险**：H=破坏面广 / M=有外部调用方 / L=内部使用

### 1) 汇总到 `GET /overview`（10 → 1）

| 旧端点 | 前端调用 | 后端测试 | 文档 | CLI | 风险 |
|---|---|---|---|---|---|
| `GET /summary` | `getLearningSummary()` | `test_layer2_triggers.py` | QUICK_REF / ISSUE_96 | — | M |
| `GET /dashboard` | `getLearningDashboard()` | `test_learning_runs_unified_api.py:168` + `tests/test_dashboard_api.py` + `tests/test_dashboard_frontend_integration.sh` | QUICK_START / ISSUE_96 | — | **H**（独立 e2e 脚本） |
| `GET /stats` | `getLearningStats()` | `test_learning_endpoints.py:877`（存在性检查） | QUICK_REF / QUICK_START | — | M |
| `GET /engine` | `getLearningEngine()` | `test_layer2_triggers.py:734` + `test_learning_runs_unified_api.py:262` | — | — | M |
| `GET /status` | — | `test_layer2_triggers.py:677` + `e2e_test_report_final.json` | QUICK_REF | — | L |
| `GET /next-run` | — | — | — | — | L |
| `GET /signals-summary` | `getSignalsSummary()` | `test_learning_endpoints.py:868` | QUICK_REF | — | L |
| `GET /failure-stats` | — | `test_layer2_triggers.py:585` | — | — | L |
| `GET /feedback-insights` | — | `test_layer2_triggers.py:615` | — | — | L |
| `GET /topology` | — | — | — | — | L（前端 T4 已下线对应 tab） |

### 2) `GET /runs`（保留，可加 `?include=feedback,conversation`）

| 旧端点 | 前端调用 | 后端测试 | 文档 | CLI | 风险 |
|---|---|---|---|---|---|
| `GET /runs` | `getLearningRuns(limit, quality, kind)` | `test_learning_runs_unified_api.py:90` | ISSUE_96 | — | L（保留） |

### 3) 汇总到 `GET /problems`（4 → 1）+ `POST /problems/{id}/analyze`

| 旧端点 | 前端调用 | 后端测试 | 文档 | CLI | 风险 |
|---|---|---|---|---|---|
| `GET /problems` | `getDetectedProblems(status?, limit)` | `test_layer2_triggers.py:775,816` + `test_learning_endpoints.py:869` + `e2e_test_report_final.json` | QUICK_REF / QUICK_START / ISSUE_96 | — | **H** |
| `GET /signals` | `getLatestSignals(limit)` | `test_learning_endpoints.py:867` + `e2e_test_report_final.json` | QUICK_REF / QUICK_START | — | M |
| `GET /blindspots` | `getLearningBlindspots(minSize)` | `test_layer2_triggers.py:953,982` + `e2e_test_report_final.json` | — | — | M |
| `POST /analyze-problem` | `analyzeRootCause(problemId)` | `test_learning_endpoints.py:870` + `e2e_test_report_final.json` | QUICK_REF / QUICK_START | — | M |
| `GET /strategies` | `getRepairStrategies(problemId)` | `test_layer2_triggers.py:858` + `test_learning_endpoints.py:871` + `e2e_test_report_final.json` | QUICK_REF / QUICK_START | — | M（合并到 `/problems/{id}/strategies`） |

### 4) 汇总到 `GET /gaps`（3 → 1）

| 旧端点 | 前端调用 | 后端测试 | 文档 | CLI | 风险 |
|---|---|---|---|---|---|
| `GET /gaps` | `getLearningGaps()` | `test_layer2_triggers.py:890` + `test_learning_endpoints.py:471` + `e2e_test_report_final.json` | ISSUE_96 | — | M |
| `GET /gaps/workbench` | `getLearningGapWorkbench()` | `test_learning_endpoints.py:728` | — | **是** (`learning_cli.py:87`) | **H**（CLI 用） |
| `GET /gaps/{key}` | — | — | — | — | L |

### 5) 汇总到 `POST /gaps/{key}/action`（4 → 1）

| 旧端点 | 前端调用 | 后端测试 | 文档 | CLI | 风险 |
|---|---|---|---|---|---|
| `POST /gaps/triage` | `triageGaps()` | `test_learning_endpoints.py:517,573` | — | **是** (`learning_cli.py:79`) | **H** |
| `POST /gaps/{key}/retest` | `retestGap()` | — | — | **是** (`learning_cli.py:104`) | M |
| `POST /gaps/{key}/transition/{action}` | `transitionGap()` | — | — | — | M |
| `POST /gaps/reconcile` | — | — | — | — | L |

### 6) 汇总到 `GET /improvements`（3 → 1）+ `POST /improvements/{id}/review`

| 旧端点 | 前端调用 | 后端测试 | 文档 | CLI | 风险 |
|---|---|---|---|---|---|
| `GET /history` | `getImprovementHistory()` | `test_learning_endpoints.py:876` + `e2e_test_report_final.json` | QUICK_REF / QUICK_START / ISSUE_96 | — | **H** |
| `GET /improvement-events` | — | — | — | — | L |
| `GET /radar` | — | docs 提及未实现端点 `radar/{id}/decision` | docs/learning/external-radar-sources.md | — | L（已规划集成进 improvements 流） |
| `POST /approve-fix` | `approveFix(eventId, comments?)` | `test_layer2_triggers.py:1117` + `test_learning_endpoints.py:873` + `e2e_test_report_final.json` | QUICK_REF / QUICK_START / ISSUE_96 | — | **H** |
| `POST /reject-fix` | `rejectFix(eventId, reason)` | `test_learning_endpoints.py:874` + `e2e_test_report_final.json` | QUICK_REF / QUICK_START | — | M |
| `POST /modify-strategy` | — | `test_learning_endpoints.py:875` + `e2e_test_report_final.json` | — | — | L |
| `POST /apply-strategy` | — | `test_layer2_triggers.py:1065,1104` + `test_learning_endpoints.py:872` + `e2e_test_report_final.json` | QUICK_REF / QUICK_START | — | M（业务侧端点，需保留语义） |
| `POST /radar/{id}/review` | — | — | — | — | L |

### 7) 保留为单独端点

| 旧端点 | 前端调用 | 后端测试 | 文档 | CLI | 决定 |
|---|---|---|---|---|---|
| `POST /trigger` | — | `test_layer2_triggers.py:555` + `test_learning_endpoints.py:878` + `e2e_test_report_final.json` | QUICK_START | — | **保留** — 手动触发学习回路语义独立 |

### 8) 前端组件直接 fetch 的「孤儿」端点

| 旧端点 | 前端调用方 | 决定 |
|---|---|---|
| `GET /conversations` | `metricsApi.ts:getConversations()` + **`SystemAssistant.tsx:191`** + **`GuideHistoryPanel.tsx:61`** | 两处 TSX 直接 fetch 需要先收口到 `metricsApi.ts`，再统一切换到 `/overview?include=conversations` 或保留单独端点 |
| `GET /feedback-stats` | `getFeedbackStats()` | 评估合并到 `/overview?include=feedback` |

### 9) 移到 `_internal/`（前端 T2 已折叠到自检抽屉）

| 旧端点 | 新端点 | 前端调用 | 后端测试 | 风险 |
|---|---|---|---|---|
| `GET /projections/drift` | `GET /_internal/drift` | `getLearningProjectionDrift(runId?)` | `test_learning_runs_unified_api.py:105` | L（仅运维） |
| `POST /projections/reconcile` | `POST /_internal/reconcile` | `reconcileLearningProjections(runId?)` | `test_learning_runs_unified_api.py:122` | L（仅运维） |

## 调用方影响汇总

### 前端 `metricsApi.ts`（**21 个**公共函数，1 个文件，集中切换风险低）

```
getLearningSummary           getLearningDashboard          getLearningProjectionDrift
reconcileLearningProjections getLearningRuns                getLearningGaps
getLearningGapWorkbench       getLearningBlindspots         getConversations
getFeedbackStats              getLearningEngine             getLatestSignals
getSignalsSummary             getDetectedProblems           analyzeRootCause
getRepairStrategies           approveFix                    rejectFix
getImprovementHistory          getLearningStats              triageGaps
retestGap                     transitionGap
```

### 前端 TSX 直接 fetch（**2 处**，必须先收口）

- `src/frontend/web/src/components/SystemAssistant.tsx:191` — `fetch('/api/v1/learning/conversations?source=guide&limit=20')`
- `src/frontend/web/src/components/agent/GuideHistoryPanel.tsx:61` — `fetch('/api/v1/learning/conversations?source=guide&limit=50')`

**行动**：S4 之前先做一个准备 PR，把这两处也走 `metricsApi.ts` 的 `getConversations(limit, source)`。

### 后端测试（**3 个文件**，影响最大）

| 文件 | 涉及端点 |
|---|---|
| `tests/test_learning_endpoints.py` | gaps / gaps/triage / gaps/workbench + 12 个端点的存在性巨型 assert（L867-879） |
| `tests/test_learning_runs_unified_api.py` | runs / projections/drift+reconcile / dashboard / engine |
| `tests/test_layer2_triggers.py` | trigger / failure-stats / feedback-insights / status / engine / problems / strategies / gaps / summary / blindspots / apply-strategy / approve-fix（11 个端点） |

**`test_learning_endpoints.py:867-879` 是「端点存在性」检查**，硬编码了 12 个旧路径。T8 必须把这段改成断言新路径存在。

### 顶层 tests/ 中独立脚本

| 文件 | 涉及端点 | 行动 |
|---|---|---|
| `tests/test_dashboard_api.py` | dashboard | 改调 `/overview` |
| `tests/test_dashboard_frontend_integration.sh` | dashboard | shell 脚本，curl 改路径 |
| `tests/e2e_test_report_final.json` | 16 个端点的旧报告（数据） | 历史报告，不动；T8 完成后再生成新报告 |
| `tests/E2E_TEST_REPORT.md` | 旧报告引用 | 历史文档，不动 |

### CLI（`learning_cli.py`）— 3 处直接 HTTP 调用

```python
L79:  /api/v1/learning/gaps/triage             → /gaps/_/action  (body action=triage)
L87:  /api/v1/learning/gaps/workbench          → /gaps?view=workbench
L104: /api/v1/learning/gaps/{gap_key}/retest   → /gaps/{key}/action (body action=retest)
```

CLI 走 `args.base_url` + path 拼接，切换时一并改。

### 文档需要重写

| 文件 | 引用次数 | 策略 |
|---|---|---|
| `LEARNING_API_QUICK_REFERENCE.md` | ~20 | **重写**，按新表面组织 |
| `QUICK_START_LEARNING.md` | ~30（含一个表格 + curl 示例 + Python 代码片段） | **重写** |
| `LEARNING_API_ENDPOINTS.md` | ~5 | **重写** |
| `API_REFERENCE_LEARNING.md` | 未在 grep 中显示，可能描述性 | 检查后决定 |
| `TROUBLESHOOTING_LEARNING.md` | 未匹配 | 检查后决定 |
| `ISSUE_96_*.md` × 4 | ~10 | 历史记录，**不改**，仅在引用旧端点处加 `> 注：此处端点已在 #134 中合并，仅供历史参考` 提示 |
| `docs/learning/internal-signals.md` | 1 (`signal/followup_click` 未实现的占位) | 评估是否清理 |
| `docs/learning/external-radar-sources.md` | 2 (`radar` + `radar/{id}/decision` 未实现的占位) | 评估是否清理 |

## 端点对照速查（按新表面分组）

```
GET  /api/v1/learning/overview                       ← summary + dashboard + stats + engine + signals-summary + status + next-run + failure-stats + feedback-insights + topology
GET  /api/v1/learning/runs                           ← runs（保留）
GET  /api/v1/learning/problems                       ← problems + signals + blindspots
POST /api/v1/learning/problems/{id}/analyze          ← analyze-problem
GET  /api/v1/learning/problems/{id}/strategies       ← strategies
GET  /api/v1/learning/gaps                           ← gaps + gaps/workbench + gaps/{key}
POST /api/v1/learning/gaps/{key}/action              ← gaps/triage + gaps/{key}/retest + gaps/{key}/transition/{action} + gaps/reconcile
GET  /api/v1/learning/improvements                   ← history + improvement-events + radar
POST /api/v1/learning/improvements/{id}/review       ← approve-fix + reject-fix + modify-strategy + apply-strategy + radar/{id}/review
POST /api/v1/learning/trigger                        ← trigger（保留）

GET  /api/v1/learning/_internal/drift                ← projections/drift
POST /api/v1/learning/_internal/reconcile            ← projections/reconcile
```

**净缩减：36 → 12（10 个用户面 + 2 个 `_internal/`），表面积 -67%。**

> 比 #134 issue 原目标多 2 个（`/problems/{id}/analyze` 和 `/problems/{id}/strategies` 作为子资源单独保留），因为它们是**写操作 + 读操作分离**，强行合到 `/problems` 会让那个端点过载。

## 切换风险与优先级

### High 风险（影响多个调用方，需要 dual-read 期）

- `GET /dashboard` — 有独立 e2e 脚本 `tests/test_dashboard_*`
- `GET /problems` — 前端 + 多个测试 + 文档
- `GET /history` — 前端 + 测试 + 文档
- `POST /approve-fix` — 前端 ReviewsPanel + 测试 + 文档
- `GET /gaps/workbench` — CLI 用
- `POST /gaps/triage` — CLI 用

### Medium 风险（前端 metricsApi + 测试）

`summary` / `stats` / `engine` / `signals` / `blindspots` / `analyze-problem` / `strategies` / `gaps` / `retest` / `transition` / `reject-fix` / `apply-strategy`

### Low 风险（无前端调用或仅文档提及）

`status` / `next-run` / `signals-summary`（前端通过 overview 一次拿） / `failure-stats` / `feedback-insights` / `topology` / `improvement-events` / `modify-strategy` / `radar*` / `gaps/{key}` / `gaps/reconcile` / `projections/*`

## 切换建议（给 S2/S3/S4 排序）

1. **先做准备 PR**：把 `SystemAssistant.tsx` / `GuideHistoryPanel.tsx` 的直接 fetch 改走 `metricsApi.getConversations()`——这样 S4 的前端切换可以**集中在一个文件**完成
2. **High 风险端点先上 dual-read**：保留旧端点 + 新端点同时返回相同语义，加 `Deprecation: true` header，前端切完后再下线
3. **CLI 同步切换**：S4 切前端时一并改 `learning_cli.py` 3 处
4. **文档先重写 QUICK_REFERENCE + ENDPOINTS**：让外部读者立刻看到新表面；历史文档（ISSUE_96_*）加注释指向新端点

## 未在原 #134 issue 列出但应一并处理

- 6 个 #133 主 issue 没列出的端点：`stats / status / next-run / trigger / failure-stats / feedback-insights`（其中 5 个属于"系统状态汇总"，1 个 `trigger` 保留独立）
- 前端 2 处 TSX 直接 fetch（绕过 metricsApi）
- 3 个文档目录的"占位未实现端点"（`signal/followup_click` / `radar/decision`）应一并清理或转为 backlog
