# 学习模块 — 拓扑不变量（Invariants）

> 本文是 #94 的核心契约：**鲁棒性不来自固定形态，来自这 6 个不变量在每次迭代后仍然成立。**

---

## I1 — 全连通（Closed Loop）

**含义**：从任意一次用户查询出发，能到达反馈、学习、回写、再次检索。无孤立子图。

**形式化**：

```
∀ q ∈ query:
  ∃ path: query → analyzer → navigator → retriever → tool → synthesize
                         → verifier → feedback → learner → architect → (improvement) → navigator/path/tool
```

**度量**：图上每条边的 `last_traversed_at` 在任意 30 天窗口内都被走过；图遍历从 query 节点 BFS 能覆盖所有 12 个节点。

**违反症状**：
- 反馈写了但没人读 → learner 入度=0
- 改进事件写了但没回写到检索 → architect 出度=0

---

## I2 — 反馈可达（Feedback Reachability）

**含义**：任何一次评分/差评/追问都能在 ≤N 跳内影响下一次同类查询的检索路径。

**形式化**：

```
∀ f ∈ feedback where rating == -1:
  ∃ improvement_event e:
    e.source_feedback_id == f.id
    AND e.applied_at IS NOT NULL
    AND ∃ q' ∈ query where similar(q'.text, f.query)
                       AND q'.ts > e.applied_at
                       AND q' 经过 e.affected_path
```

**度量**：
- `improvement_events.source_feedback_id` 非空率
- 差评 → 改进 中位时延（目标 ≤ 24h）

---

## I3 — 无悬挂证据（No Dangling Evidence）

**含义**：所有 chunk 引用都能反向定位到源文件、源段落、入库时间。

**形式化**：

```
∀ chunk c used in answer:
  c.file_name IS NOT NULL
  AND c.path IS NOT NULL
  AND c.metadata IS NOT NULL
  AND (c.parent_summary IS NOT NULL OR c.depth ≤ 2)
```

**度量**：text_chunks 中三字段非空率 ≥ 99%。

---

## I4 — 双轨可分（Auditable Two-Track）

**含义**：自动学习和人工学习产物显式标记，可独立审计/回滚。

**形式化**：

```
∀ e ∈ improvement_events:
  e.source ∈ {'auto', 'human', 'external'}
  AND e.actor IS NOT NULL
  AND e.reversible_by IS NOT NULL
```

**度量**：每条 improvement_event 三字段都填。回滚演练每月一次成功。

---

## I5 — 外部信号入口（External Signal Port）

**含义**：至少一个常开端口接收外部信号（新模型 / 新工具 / 新论文 / 依赖升级）。

**形式化**：

```
tech_radar 表：
  最近 7 天有 ≥ 1 条新写入（除休假窗口）
  来源种类 ≥ 3（多样性）
```

**度量**：`SELECT COUNT(DISTINCT source), MAX(fetched_at) FROM tech_radar WHERE fetched_at > NOW() - interval '7 days'`。

---

## I6 — 形态无关（Shape-Invariant）

**含义**：拆/合/换工具不破坏 I1-I5。

**形式化**：

```
∀ refactor r:
  invariants_before(r) == invariants_after(r) == ALL_OK
```

**度量**：每次合并 PR 后自动跑 `topology_health.py`，必须 6 全 OK 才能 merge（CI gate）。

---

## 拓扑节点与边（参考形态）

> 形态可变，但**所有边的语义必须存在**，否则不变量破坏。

```
[query] ──user→ [analyzer] ──rewrite→ [navigator] ──path→ [retriever]
                                                         ↓ tool_call
[synthesize] ←results── [verifier] ←chunks── [tool]
     ↓ stream
[user_feedback] ──rating/comment→ [learner]
                                       ↓ aggregate
                                  [architect]
                                       ↓ patch
            ┌─────────────────────────┴────────────┐
            ↓                                      ↓
    [navigator_dict]                         [path_default]
            └─────────── (闭环回到 navigator) ─────┘

[external_signal] ──daily_radar→ [architect]
```

12 节点、约 16 条边。每条边带 `last_traversed_at` 时间戳。任何边超过 30 天未走 → 该边对应能力退化告警。

---

## 校验脚本

`scripts/topology_health.py` 检查上述 6 项，CI 上 PR 必跑。
