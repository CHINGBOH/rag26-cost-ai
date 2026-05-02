# 内部信号目录（Internal Signals Catalog）

> #94 Phase A 产物。盘点系统内部所有可被学习模块消费的信号源，并标注 gap。

---

## 信号清单

| 编号 | 信号 | 现有载体 | 字段/路径 | 聚合度 | Gap |
|------|------|----------|-----------|--------|-----|
| S1 | 用户查询原文 | `conversation_turns.user_content` | session_id + turn_index | 单条 | ✅ 完整 |
| S2 | LLM 回答全文 | `conversation_turns.assistant_content` | 同上 | 单条 | ✅ 完整 |
| S3 | 改写后的查询 | agent state（in-mem） | `state.rewritten_query` | 内存 | ❌ **未持久化** |
| S4 | 路径约束 | agent state | `state.path_constraint` | 内存 | ❌ **未持久化** |
| S5 | navigator roadmap | agent state | `state.roadmap` | 内存 | ❌ **未持久化** |
| S6 | 引用 chunks | agent_runs（或 trace） | `chunk_ids[]` | 按 run | ⚠️ 没有 chunk-level CTR |
| S7 | 工具调用序列 | OTEL traces | span tree | 按 trace | ⚠️ 未聚合命中率 |
| S8 | 合约违规 | logger | text log | 文本 | ❌ **未结构化入表** |
| S9 | 评分（5 维） | `rag_feedback` | overall + 4 dims | 单条 | ✅ 完整 |
| S10 | 文字反馈 | `rag_feedback.{praise,criticism,suggestion}` | text | 单条 | ⚠️ 未 NLP 聚类 |
| S11 | 反馈标签 | `rag_feedback.tags[]` | text[] | 单条 | ⚠️ 词频未统计 |
| S12 | 用户重问 | 全无 | — | — | ❌ **关键缺口** |
| S13 | LLM 自评 confidence | trace step | `evaluation.confidence` | 单条 | ⚠️ 未持久化 |
| S14 | 迭代次数 | `agent_runs.iterations` | int | 单条 | ✅ |
| S15 | 延迟分布 | `conversation_turns.latency_ms` | int | 单条 | ✅ |
| S16 | 拒答 / 兜底 | answer 文本模式匹配（"无法回答"） | text | 单条 | ❌ **未单独统计** |
| S17 | followup 被采纳 | 前端点击事件 | — | — | ❌ **没埋点** |
| S18 | path_constraint 失败 | navigator_node | logger | 文本 | ❌ **未结构化** |
| S19 | rerank 后排序变化 | rerank 节点 | 内存 | 内存 | ❌ **未持久化** |
| S20 | docker 健康事件 | `/health/detail` 历史快照 | — | — | ❌ **无历史** |

---

## Gap 优先级

### P0（数据缺失，必须补埋点）

- **S12 用户重问检测** — 同 session_id 内 user_content 语义近似率 > 0.85 的次数
  - **新表**：`signal_repeat_question(session_id, original_turn, repeat_turn, similarity, ts)`
  - **检测**：cosine(embedding(t_n), embedding(t_n-1)) > 0.85
  - **影响**：直接喂给 architect 的"高频未解决"队列

- **S8 合约违规结构化** — contract_verifier 已经产出 ContractResult，但没入表
  - **新表**：`signal_contract_violation(run_id, contract_name, violation_code, payload, ts)`
  - **影响**：趋势能直接生成 issue

- **S16 拒答检测** — 答案命中 `"无法回答|无法直接回答|未提供|不足以回答|均显示为N/A"` 任意一项
  - **新字段**：`agent_runs.is_refusal BOOLEAN`
  - **影响**：拒答率 > 阈值的 chapter → 自动入 architect inbox

### P1（已存在但未结构化/聚合）

- S6 chunk-level CTR：`signal_chunk_usage(chunk_id, run_id, was_cited, was_top_ranked)`
- S7 tool 命中率：物化视图 `mv_tool_hit_rate`，每小时刷新
- S10 NLP 聚类：feedback 文字段每周做一次 BERTopic 聚类，结果入 `signal_feedback_cluster`

### P2（短期内不致命，长期价值高）

- S3-S5 持久化：扩 `agent_runs` 加 jsonb 字段 `state_snapshot`
- S13 confidence 历史：用于评估 LLM 自评准确性
- S17 followup 埋点：前端 onClick → POST `/api/v1/learning/signal/followup_click`
- S19 rerank delta：评估 rerank 是否在做无用功
- S20 健康历史：每分钟快照写入 `signal_health_snapshot`

---

## 写回的 5 个回路（Where signals impact retrieval）

每条信号必须能回写到下面至少一个位置：

| 回写点 | 影响 | 写回字段 | 受哪些信号驱动 |
|--------|------|----------|----------------|
| **R1 navigator 关键词词典** | `_extract_navigator_keywords` 的近义词扩展 | `learning_dict_navigator(term, expansion[])` | S10/S12 |
| **R2 path_constraint 默认** | 高频章节路径前缀的快捷映射 | `learning_path_default(query_pattern, path_prefix)` | S6/S18 |
| **R3 planner few-shot** | 提示词中追加历史好/坏例子 | `learning_planner_examples(question, plan, label)` | S9/S14 |
| **R4 rerank 权重** | hybrid_search 的 BM25/dense/trgm 权重微调 | `learning_rerank_weights(query_class, weights jsonb)` | S6/S9 |
| **R5 tool 选择策略** | 哪个工具优先调用（命中率高优先） | `learning_tool_priority(query_class, tool, priority)` | S7 |

每条 `improvement_event` 必须显式声明它影响 R1-R5 中的哪一个，否则就是悬挂学习（违反 I1）。

---

## 下一步

1. 创建上述新表（migration 见 `sql/migrations/202605_learning_signals.sql`）
2. 在对应 Python 节点埋点写入
3. 实现 R1-R5 的 hot-load 逻辑（启动时 + SIGHUP 重读）
4. `topology_health.py` 把上述每条信号纳入 I1-I6 检查
