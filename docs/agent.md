# Agent 核心任务与跑通标准

> 本文档是 RAG Agent 的**核心任务说明书**，面向开发和调试 Agent 的工程师/AI助手。
> 目标：让 Agent 能**调用工具完成带索引的回答**，并**通过质量审核与递归迭代**，直至 16 道测试题全部跑通。
>
> 关联文档：
> - `agent-implementation-plan.md` — Agent 架构实施计划
> - `rag-agent-architecture-enhancement.md` — RAG Agent 架构完善方案
> - `rag-architecture-inspection-report.md` — 架构检测报告
> - `langgraph-runtime-core.md` — LangGraph Runtime 拆解

---

## 一、Agent 核心能力定义

Agent 不是简单的"问答机器人"，而是一个**具备工具调用、质量自审、递归优化能力的自治系统**。

### 1.1 核心循环（Runtime）

```
用户Query
    │
    ▼
[Query Understanding] ──→ 意图识别（定额查询/信息价/计算/对比）
    │
    ▼
[Planning] ──→ 选择检索策略 + 生成子查询
    │
    ▼
[Tool Calling] ──→ 调用四库工具（vector/keyword/graph/structured/calculator）
    │
    ▼
[Generation] ──→ LLM生成带索引（citations）的自然语言回答
    │
    ▼
[Evaluation] ──→ 质量自审（7维评分）
    │
    ├──→ passed === true ──→ [Output] ✅ 返回回答
    │
    └──→ passed === false && iterations < max
            │
            ▼
        [Re-planning] 调整策略 ──→ 回到 Planning 迭代优化
```

### 1.2 关键组件

| 组件 | 文件位置 | 职责 |
|------|----------|------|
| **Agent Factory** | `src/backend/server/src/modules/agent/src/factory.ts` | 创建 LangChain Agent 实例 |
| **ReAct Agent** | `src/backend/server/src/modules/agent/src/react-loop.ts` | LangChain ReAct 循环，LLM 决策工具调用 |
| **四库 Tools** | `src/backend/server/src/modules/agent/src/tools.ts` | vectorSearch/keywordSearch/graphSearch/calculator |
| **Cascade Retrieval** | `src/backend/server/src/modules/retrieval/src/cascade-retrieval.ts` | 四库级联检索 |
| **Runtime design reference** | `docs/langgraph-runtime-core.md` | Channel/State/runtime 设计参考 |

---

## 二、16 道核心测试题（跑通标准）

以下测试题覆盖**定额查询、信息价对比、费率计算、标准解读**四大场景。Agent 必须全部通过，才算"跑通"。

| 序号 | 测试问题 | 考察能力 | 关键工具 |
|------|----------|----------|----------|
| 01 | 安装工程消耗量标准中送配电装置系统调试的计算规则是什么？ | 定额规则检索与解释 | `keywordSearch` → `vectorSearch` |
| 02 | 25版装饰工程消耗量标准中，楼梯面层中玻璃地板的人工费是多少？ | 定额子目精确数值检索 | `keywordSearch` + PostgreSQL |
| 03 | 对比深圳市2025年12月和2023年12月工程建设信息价中，电力电缆规格型号为0.6/1KV YJV 5×120的价格差异 | 跨时间信息价对比 | `keywordSearch` ×2 + `calculator` |
| 04 | 根据深圳信息价分析下从25年开始至今的装配式混凝土预制构件价格走势 | 时序数据分析 | `keywordSearch` + `calculator` |
| 05 | 2025年深圳信息价中钛合金门窗的价格是多少 | 单点信息价精确查询 | `keywordSearch` + PostgreSQL |
| 06 | 详细说明深圳市工程建设地方标准中，关于安全文明施工费的组成内容、计算基数以及计取规定 | 多维度标准条文综合解读 | `vectorSearch` → `graphSearch` |
| 07 | 工程项目中施工地点要按照什么要求填写 | 规范填写规则检索 | `vectorSearch` |
| 08 | 2025版费率标准中，房建工程赶工措施费的推荐系数是多少？ | 费率系数精确查询 | `keywordSearch` |
| 09 | 一般计税方法下，税前工程造价中的费用是否包含进项税额？ | 税务/计价规则判断 | `vectorSearch` |
| 10 | 总包管理服务费的计算基数是什么？ | 计算基数定义查询 | `vectorSearch` |
| 11 | 模块化建筑工程施工工期定额适用于单体预制箱体应用比例大于多少的±0.00以上工程？ | 定额适用条件精确查询 | `keywordSearch` |
| 12 | 2023版与2025版费率标准中，利润率的参考范围是否一致？ | 跨版本标准对比 | `vectorSearch` ×2 + `graphSearch` |
| 13 | 某工程人工费100万、材料费200万、机械费50万、企业管理费25万，企业管理费率是多少？ | 数值反推计算 | `keywordSearch` → `calculator` |
| 14 | 按2025版标准，如果机械费为0，企业管理费的计算基数是什么 | 边界条件规则查询 | `keywordSearch` + `vectorSearch` |
| 15 | 2026年1月，中砂的价格是多少元/m³？ | 最新信息价实时查询 | `keywordSearch` + PostgreSQL |
| 16 | 2026年1月，电线、电缆价格较上月的变化幅度是多少？ | 环比变化幅度计算 | `keywordSearch` ×2 + `calculator` |

### 2.1 "跑通"判定标准（必须全部满足）

1. **有索引引用（Citations）**：回答末尾必须标注参考来源（如：参考《深圳市2025版费率标准》第3.2条、chunk_xxx）
2. **数值准确**：涉及金额、系数、比例的问题，数值必须与原始文档一致
3. **工具调用痕迹**：LangFuse / 日志中可见至少一次 `vectorSearch` / `keywordSearch` / `graphSearch` 调用
4. **质量审核通过**：`evaluation.passed === true`（confidence ≥ 0.7 且有引用）
5. **无幻觉**：LLM 未编造原始文档中不存在的规则或数值

---

## 三、带索引回答的生成机制

Agent 的最终输出必须是**结构化回答 + 引用溯源**，不是裸文本。

### 3.1 输出 Schema

```typescript
interface StructuredOutput {
  answer: string;              // 自然语言回答（中文）
  indices: IndexReference[];   // 引用索引列表
  calculations: Calculation[]; // 计算过程记录（造价题必备）
  confidence: number;          // 置信度 [0, 1]
}

interface IndexReference {
  chunkId: string;             // 来源 chunk ID
  docId: string;               // 来源文档 ID
  pageNumber?: number;         // 页码
  text: string;                // 引用的原文片段
  sourceDb: 'vector' | 'keyword' | 'graph' | 'structured';
}
```

### 3.2 生成流程

1. **上下文组装**：将 `retrievedChunks` 按得分排序，取 Top-K 作为 LLM 上下文
2. **Prompt 约束**：系统 Prompt 明确要求"标注参考来源"、"严禁编造"
3. **引用提取**：LLM 回答后，用正则/匹配算法将关键句与 `retrievedChunks` 对齐，生成 `citations`
4. **计算记录**：若调用了 `calculator`，将表达式和结果记入 `calculations`

### 3.3 Prompt 模板（生成阶段）

```
你是一个建筑工程造价领域的专业助手。请基于以下检索结果回答用户问题。

检索结果：
{retrieved_chunks}

用户问题：{query}

要求：
1. 用中文清晰、简洁地回答
2. 如果涉及数值，必须严格使用检索结果中的原始数值
3. 在回答末尾标注参考来源（格式：参考 [文档名] 第X页 / chunk_id）
4. 如果信息不足，明确说明"根据现有资料无法完全回答"
5. 不要编造任何检索结果中不存在的内容
```

---

## 四、回答质量审核（Self-Evaluation）

每次生成后，必须对回答进行多维评分。

### 4.1 评分维度

```typescript
interface EvaluationResult {
  completeness: number;      // 信息完整性 [0, 1]
  consistency: number;       // 逻辑一致性 [0, 1]
  confidence: number;        // 综合置信度 [0, 1]
  informationGain: number;   // 信息增益（相比上一轮）
  sourceDiversity: number;   // 来源多样性 [0, 1]
  factConsistency: number;   // 事实一致性（与检索结果对比）
  coverageEstimate: number;  // 覆盖率估计 [0, 1]
  overall: number;           // 综合得分
  passed: boolean;           // 是否通过阈值
  suggestions?: string[];    // 优化建议
}
```

### 4.2 审核规则

| 审核项 | 阈值 | 未通过时的优化动作 |
|--------|------|-------------------|
| `confidence` | ≥ 0.70 | 触发 `planning` → 调整检索策略或子查询 |
| `hasCitations` | 必须 > 0 | 触发 `retrieving` → 扩大 topK 或换数据库 |
| `factConsistency` | ≥ 0.80 | 触发 `reasoning` → 重新核对检索结果与回答 |
| `sourceDiversity` | ≥ 0.30 | 触发 `retrieving` → 启用 fusion 多库检索 |
| `iterations` | ≤ maxIterations | 超过则强制结束并标记 `passed = false` |

### 4.3 审核 Prompt 模板

```
请对以下问答进行质量审核：

问题：{query}
回答：{response}
引用来源：{citations}
检索结果：{retrieved_chunks}

请从以下维度评分（0-1）：
1. completeness: 回答是否完整覆盖了问题的所有要点？
2. consistency: 回答内部是否逻辑一致？
3. factConsistency: 回答中的事实是否与检索结果一致？有无幻觉？
4. sourceDiversity: 引用来源是否多样？
5. confidence: 综合置信度

输出JSON格式：{"completeness": 0.85, "consistency": 0.9, ..., "passed": true/false, "suggestions": ["..."]}
```

---

## 五、递归迭代优化

### 5.1 迭代控制逻辑

```
[evaluating]
    │
    ├──→ passed === true ───────────────→ [completed] ✅
    │
    ├──→ passed === false && iters < max ──→ [planning] 🔄 迭代
    │                                           │
    │   ├──→ 检索不足？扩大 topK / 换库 / 改写查询
    │   ├──→ 数值存疑？调用 calculator 验证
    │   ├──→ 跨文档对比？补充 time-filter / version-filter
    │   └──→ 引用缺失？强制 LLM 重新生成并插入 citations
    │
    └──→ iters >= max ──────────────────→ [completed] ⛔ 强制结束（标记失败）
```

### 5.2 状态机代码（XState v5）

```typescript
evaluating: {
  invoke: {
    src: 'evaluateResponse',
    onDone: [
      {
        guard: ({ context }) => context.evaluation?.passed ?? false,
        target: 'completed',
        actions: 'assignEvaluation'
      },
      {
        guard: ({ context }) => {
          return !context.evaluation?.passed && context.iterations < context.maxIterations
        },
        target: 'planning',
        actions: ['assignEvaluation', 'incrementDepth']
      },
      {
        target: 'completed',
        actions: 'assignEvaluation'
      }
    ]
  }
}
```

### 5.3 常见迭代场景

| 场景 | 第一轮问题 | 优化动作 | 第二轮改进 |
|------|-----------|----------|-----------|
| 检索结果为空 | keywordSearch 未命中"赶工措施费" | 改用 vectorSearch 语义检索 | 命中《费率标准》相关条文 |
| 引用缺失 | LLM 输出裸文本无 citations | 在 Prompt 中加"必须标注来源" | 输出带 chunk_id 的引用 |
| 数值错误 | LLM 将 0.85 写成 0.8 | 启用 PostgreSQL 结构化查询获取精确值 | 数值与原文一致 |
| 跨时间对比失败 | 只检索到 2025-12 数据 | planning 生成两个子查询（2023-12, 2025-12） | 获取两个时间点数据后计算差异 |
| 计算错误 | 费率反推公式错误 | 调用 calculator 验证：25/(100+200+50) | 结果正确 = 7.14% |

---

## 六、造价领域特殊处理

### 6.1 定额子目精确匹配

- 使用 `keywordSearch` 匹配"25版"、"装饰工程"、"楼梯面层"、"玻璃地板"等关键词
- 若关键词未命中，降级为 `vectorSearch` 语义检索
- 命中后提取"人工费"字段，若文档中为表格，通过 PostgreSQL 结构化查询获取

### 6.2 信息价时序查询

- 查询需带 `time_range` filter（如 2025-01 至 2026-01）
- 对比类问题（03、04、16）需执行两次检索，再用 `calculator` 计算差异/涨幅
- 结果需注明"信息价来源：深圳市建设工程造价管理站"

### 6.3 费率计算验证

- 检索到费率规则后，若用户给出具体数值（如 13 题），调用 `calculator` 反推费率
- 验证公式：`企业管理费率 = 企业管理费 / (人工费 + 材料费 + 机械费)`
- 边界条件：机械费为 0 时，基数是否包含机械费（需按 2025 版标准条文判定）

### 6.4 跨版本标准对比

- 同时检索 2023 版和 2025 版费率标准
- 用 `graphSearch` 关联"利润率"实体，获取两个版本的关系节点
- 对比回答需分别引用两个版本的条文号

---

## 七、跑通验证流程

### 7.1 单条测试

```bash
# 启动服务
./start-all.sh local

# 发送测试请求
curl -X POST http://localhost:8080/api/rag/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "2025版费率标准中，房建工程赶工措施费的推荐系数是多少？",
    "options": { "maxIterations": 5, "enableEvaluation": true }
  }'

# 期望返回：
# {
#   "answer": "根据《深圳市建设工程计价费率标准（2025版）》，房建工程赶工措施费的推荐系数为X%。",
#   "indices": [{"chunkId": "...", "docId": "费率标准2025.pdf", "pageNumber": 15, ...}],
#   "calculations": [],
#   "confidence": 0.92,
#   "evaluation": { "passed": true, "overall": 0.91 }
# }
```

### 7.2 批量跑通测试（16条）

```bash
cd /home/l/rag-dashboard
python tests/test_agent_16.py

# Node.js 端仅保留 /api/agent/run 的 SSE contract smoke
cd src/backend/server
npx vitest run src/__tests__/rag-agent-core.test.ts
```

### 7.3 质量报告

测试完成后生成报告：

```json
{
  "total": 16,
  "passed": 16,
  "failed": 0,
  "details": [
    {
      "id": "01",
      "query": "...",
      "passed": true,
      "confidence": 0.91,
      "iterations": 1,
      "toolsUsed": ["keywordSearch"],
      "latencyMs": 850
    }
  ]
}
```

**必须 16/16 通过，才算 Agent 跑通。**

---

## 八、质量不达标排查手册

| 现象 | 根因 | 修复方案 |
|------|------|----------|
| 回答无引用 | LLM 未输出 citations / 检索结果为空 | 检查 Prompt 是否强制要求引用；检查 Qdrant 是否有对应数据 |
| 数值错误 | 表格数据解析错误 / LLM 幻觉 | 启用 PostgreSQL 结构化查询；Prompt 中加"严格按原文数值回答" |
| 跨时间对比失败 | 只检索到一个时间点的数据 | 在 planning 阶段生成多个子查询 |
| 费率计算错误 | 计算基数理解错误 | 检索"计算基数"定义条文，用 calculator 验证 |
| 迭代死循环 | 每次检索结果相同 | 设置 diversity 要求；启用查询改写（query rewriting） |
| 超时 | 检索延迟高或迭代次数过多 | 调小 maxIterations；启用检索缓存；Qdrant 加 payload 索引 |
| 工具选择错误 | LLM 选了不合适的工具 | 优化 tool description；增加 few-shot 示例 |
| 输出格式不稳定 | LLM 未按 schema 输出 | 使用 `with_structured_output` 强制约束；增加 JSON 修复逻辑 |

---

## 九、关联文件索引

| 文件 | 说明 |
|------|------|
| `src/backend/server/src/modules/agent/src/factory.ts` | Agent 工厂 |
| `src/backend/server/src/modules/agent/src/react-loop.ts` | ReAct Agent 循环 |
| `src/backend/server/src/modules/agent/src/tools.ts` | 四库工具定义 |
| `src/backend/server/src/modules/retrieval/src/cascade-retrieval.ts` | 级联检索服务 |
| `docs/langgraph-runtime-core.md` | runtime / Channel / checkpoint 设计参考 |
| `src/backend/python-legacy/ragas_eval.py` | Ragas 语义质量评估 |
| `infrastructure/promptfooconfig.yaml` | Promptfoo A/B 测试配置 |
| `config/config.yaml` | 检索权重、模型参数配置 |

---

*文档版本: 1.0*
*更新日期: 2026-04-19*
