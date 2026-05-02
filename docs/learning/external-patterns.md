# 外部学习模式对照（External Patterns）

> #94 Phase C 产物。每种业内模式逐项判断"是否保我们的 6 个不变量"。

---

## 1. LangGraph CheckpointSaver + InterruptBefore

**核心**：每个图节点后自动保存 state，支持中断点（人工审批）。

**对 I1-I6 的影响**：

| 不变量 | 评估 | 备注 |
|---|---|---|
| I1 全连通 | ✅ 直接强化 | checkpoint 链是天然有向图 |
| I2 反馈可达 | ✅ | 中断点是人工反馈的入口 |
| I3 无悬挂 | ⚠️ 中性 | state 保留得太多反而难追溯关键节点 |
| I4 双轨可分 | ⚠️ | 需要在 metadata 加 source 字段 |
| I5 外部信号 | ❌ | 与之无关 |
| I6 形态无关 | ✅ | LangGraph 节点重构对外契约稳定 |

**采纳建议**：把 contract_verifier 的中断点对接 LangGraph InterruptBefore，让差评直接挂起 graph 等人工。

---

## 2. DSPy Compile / Teleprompter

**核心**：把 prompt 当成可优化参数，用历史好/坏样本反向"编译"出更优 prompt。

**对 I1-I6 的影响**：

| I1 | ✅ 形成"训练样本 → 编译 → 部署"闭环 |
| I2 | ✅ 差评样本可直接进 teleprompter 训练集 |
| I3 | ⚠️ 编译产物（新 prompt）需要可追溯到训练集，否则破坏 |
| I4 | ✅ DSPy 自然区分 demonstrations（人工标）和 bootstrapped（自动） |
| I5 | ❌ 与之无关 |
| I6 | ✅ |

**采纳建议**：planner few-shot 走 DSPy 风格 — `learning_planner_examples` 表里好/坏样本各 N 条，rotate compile，新 prompt 写回 prompt_registry 表（带 source + train_set_hash）。

---

## 3. OpenAI Evals harness

**核心**：把评估当作一等公民，定义评估集 → 跑 → 出 metrics → 决定是否回滚。

**对 I1-I6 的影响**：

| I1 | ✅ 评估是写回前的必经节点 |
| I2 | ⚠️ 评估通常用静态集，不一定挂得上动态反馈 |
| I3 | ✅ 评估集本身是版本化资产 |
| I4 | ✅ 区分"自动回归"vs"人工标注集" |
| I5 | ❌ |
| I6 | ✅ 评估集与实现无关 |

**采纳建议**：项目已有 `tests/test_agent_16.py`（16 题回归集），扩展为 evals harness：
- 多评估集（chapter / price / hybrid）
- 每次写回 R1-R5 任一回路前必须先跑评估
- 通过率退步 > 5% → 自动回滚 + 开 issue

---

## 4. Anthropic Constitutional AI（人工反馈编织）

**核心**：用一组"宪法"（principles）作为评估器，先用 AI 自评，再用人工 RM 校正。

**对 I1-I6 的影响**：

| I1 | ✅ 自评 → 人评 → 模型更新是闭环 |
| I2 | ✅ 人评直接进 RM |
| I3 | ✅ 宪法条目本身是结构化资产 |
| I4 | ⚠️ 自评/人评界限要严守，否则破坏 I4 |
| I5 | ❌ |
| I6 | ✅ |

**采纳建议**：把项目现有的 4 个 contract（query_analysis / navigator / tool / synthesize）当作"宪法"，每条 contract result 都进 `signal_contract_violation` 表，差评样本进人工标注队列，每月做一次"宪法修订"（更新 contract 阈值/规则）。

---

## 5. Reflexion（自我反思循环）

**核心**：失败后让 LLM 用语言反思失败原因，存入 episodic memory，下次重试前先读 memory。

**对 I1-I6 的影响**：

| I1 | ✅ 反思笔记是闭环里关键一环 |
| I2 | ✅ 失败 → 反思 → 下次改进，1 跳可达 |
| I3 | ⚠️ 反思笔记必须可追溯到具体 run_id |
| I4 | ✅ 反思是 auto，可标记 |
| I5 | ❌ |
| I6 | ✅ |

**采纳建议**：项目已有 `corrective_action_node`，扩成 Reflexion 风格 — 失败后让 LLM 写一段 ≤200 字反思，存 `signal_reflection(run_id, reason, suggested_fix)`，下次相似查询时由 navigator 读取该 session 的 reflection 作为 hint。

---

## 6. ReAct + Self-consistency

**核心**：多次采样答案 → 投票，提高鲁棒性。

**对 I1-I6 的影响**：

| I1 | ✅ |
| I2 | ❌ 与反馈闭环无关，是推理鲁棒性 |
| I3 | ✅ |
| I4 | ⚠️ |
| I5 | ❌ |
| I6 | ✅ |

**采纳建议**：低优先级。仅对高 stakes 查询（合规问、价格批量计算）启用 self-consistency；普通查询沿用单次。

---

## 综合采纳矩阵

| 模式 | 优先级 | 落到哪个回路 | 接入工时估算 |
|---|---|---|---|
| LangGraph Checkpoint+Interrupt | P0 | 工程基础 | 中 |
| DSPy 风格 prompt 自编译 | P1 | R3 planner few-shot | 中-高 |
| Evals harness | P0 | 写回 gate | 低-中 |
| Constitutional AI 风格契约 | P1 | 已有 contract 升级 | 中 |
| Reflexion 反思笔记 | P1 | corrective_action 升级 | 低 |
| Self-consistency | P3 | 高 stakes 路由 | 低 |

---

## 核心结论

**鲁棒性的关键不是采纳哪个特定框架，而是确保每条机制接入后 6 个不变量仍然成立。**

具体到本项目，最高 ROI 的两条：
1. **Evals harness** — 让 R1-R5 任何写回都必须先过 evals，否则 I6（形态无关）就只是嘴上说说。
2. **DSPy 风格 prompt registry** — 让 planner / synthesize prompt 进入版本化资产，可回滚，强化 I4。
