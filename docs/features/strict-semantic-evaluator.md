# Issue #124: 严格语义评估器

## 问题背景

**分数通胀问题**：原有评估使用硬编码规则，垃圾答案也能拿高分：
- 有chunks就给0.56+基础分
- 多个chunks线性加分（0.08/chunk）
- 没有验证是否真正回答问题
- 结果：答非所问也能拿0.7+

## 解决方案

### StrictSemanticEvaluator - LLM语义验证

使用LLM判断答案是否**真正回答了**问题。

**评分标准（1-5分）**：
- 1分：完全没回答
- 2分：提到相关概念，但没回答核心问题
- 3分：部分回答
- 4分：基本回答完整
- 5分：完美回答

**通过条件**：
- `semantic_score >= 0.6`
- `fact_consistency >= 0.5`
- `len(chunks) > 0`

### Feature Flag控制

```bash
# 启用严格评估
export ENABLE_STRICT_EVALUATION=true

# 使用原有规则（默认）
export ENABLE_STRICT_EVALUATION=false
```

## 测试结果

✅ **9/9 tests passed**

```bash
cd src/backend/retrieval-service
python -m pytest tests/test_strict_evaluator.py -v
```

## 案例对比

### 垃圾答案被识别 ✅

**问题**：混凝土强度等级与抗渗等级的关系是什么？  
**答案**：混凝土强度等级分为C15-C80，抗渗等级分为P4-P12。

- 旧评估器: confidence=0.72 ✅ passed ❌  
- 新评估器: semantic=0.25 ✗ failed ✅

### 好答案得高分 ✅

**答案**：强度等级与抗渗等级呈正相关。强度越高抗渗性越好，C30+可达P6-P8【doc_3】。

- 新评估器: semantic=0.85, raw=5/5 ✅ passed ✅

## 性能

- LLM调用：1次/评估
- Prompt: ~250 tokens
- 输出: 1 token
- 失败降级到启发式规则

## 相关Issue

- **#124** (P1): 评估分数通胀 ✅
- **#118** (P1): Contract伪收敛
- **#113**: Feature Flag系统

**实现**: 2026-05-08  
**默认**: 关闭（需显式启用）
