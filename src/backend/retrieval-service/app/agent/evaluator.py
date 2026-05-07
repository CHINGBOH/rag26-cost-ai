"""
Evaluator Node — 7 维检索质量评分
复用 api.py /api/v1/evaluate 的评分逻辑

Issue #124: 添加 StrictSemanticEvaluator 使用LLM语义验证，避免分数通胀
"""

import re
import logging
from typing import List, Dict, Any

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

logger = logging.getLogger(__name__)


def evaluate_retrieval_quality(
    chunks: List[dict],
    generated_answer: str,
    history_rounds: int = 0,
    query_type: str = "semantic",
) -> dict:
    """
    7 维评分（语义查询）或 快速通过（价格查询）
    阈值：
      - semantic: confidence >= 0.7 AND fact_consistency >= 0.6 → passed
      - price:    有精确匹配结果且答案含数字 → passed
    """
    try:
        # ── 价格查询：简化评估 ──
        if query_type == "price":
            has_chunks = len(chunks) > 0
            has_price_number = bool(re.search(r"\d+\.?\d*", generated_answer))

            # 时间惩罚：旧数据降权
            current_year_month = ""
            for c in chunks:
                meta = c.get("metadata", {})
                if isinstance(meta, dict) and meta.get("year_month"):
                    current_year_month = meta.get("year_month")
                    break

            confidence = 0.85 if (has_chunks and has_price_number) else 0.4
            if has_chunks and not has_price_number:
                confidence = 0.55  # 有数据但 LLM 没给出数字

            passed = has_chunks and has_price_number

            # Phase 1+ Task 2: Observability integration for price query evaluation
            try:
                from config.observability import log_decision, DecisionType
                log_decision(
                    decision_type=DecisionType.EVALUATION_SCORE,
                    context={
                        "query_type": "price",
                        "history_rounds": history_rounds,
                        "chunks_count": len(chunks),
                        "answer_length": len(generated_answer)
                    },
                    params_used={
                        "requires_chunks": True,
                        "requires_price_number": True
                    },
                    outcome={
                        "passed": passed,
                        "has_chunks": has_chunks,
                        "has_price_number": has_price_number,
                        "confidence": confidence
                    },
                    reason=(
                        f"Price query evaluation: chunks={'✓' if has_chunks else '✗'}, "
                        f"price_number={'✓' if has_price_number else '✗'} → {'PASS' if passed else 'FAIL'}"
                    ),
                    confidence=confidence,
                    metadata={
                        "current_year_month": current_year_month
                    }
                )
            except Exception as e:
                logger.warning(f"[Evaluator] Observability logging failed: {e}")

            return {
                "passed": passed,
                "completeness": 0.9 if has_chunks else 0.3,
                "consistency": 0.9 if has_chunks else 0.3,
                "confidence": round(confidence, 4),
                "information_gain": max(0.1, 0.5 - history_rounds * 0.1),
                "source_diversity": min(len(set(c.get("doc_id", "") for c in chunks)) / 3, 1.0),
                "fact_consistency": 0.9 if has_price_number else 0.3,
                "coverage_estimate": 0.9 if has_chunks else 0.2,
                "feedback": "评估通过" if passed else "未提取到有效价格数字，请补充检索",
            }

        # ── 语义查询：保留原有 7 维评分 ──
        avg_score = sum(c.get("score", 0) for c in chunks) / len(chunks) if chunks else 0

        sources = set(c.get("source", c.get("doc_id", "")) for c in chunks)
        source_diversity = min(len(sources) / 3, 1.0)

        information_gain = max(0.1, 0.5 - history_rounds * 0.1)

        total_length = sum(len(c.get("content", "")) for c in chunks)
        completeness = min(total_length / 2000, 0.95)

        scores = [c.get("score", 0) for c in chunks]
        if scores:
            avg = sum(scores) / len(scores)
            variance = sum((s - avg) ** 2 for s in scores) / len(scores)
            consistency = max(0.5, 1 - variance)
        else:
            consistency = 0.5

        citations = re.findall(r"\[\d+\]", generated_answer)
        citations += re.findall(r"【[^】]+】", generated_answer)
        fact_consistency = min(0.6 + len(citations) * 0.1, 0.95)

        coverage_estimate = min(avg_score * source_diversity * 1.5, 0.95)

        confidence = (completeness + consistency + fact_consistency + source_diversity) / 4

        passed = confidence >= 0.7 and fact_consistency >= 0.6

        # Phase 1+ Task 2: Observability integration for evaluation scoring
        try:
            from config.observability import log_decision, DecisionType
            log_decision(
                decision_type=DecisionType.EVALUATION_SCORE,
                context={
                    "query_type": query_type,
                    "history_rounds": history_rounds,
                    "chunks_count": len(chunks),
                    "answer_length": len(generated_answer)
                },
                params_used={
                    "confidence_threshold": 0.7,
                    "fact_consistency_threshold": 0.6
                },
                outcome={
                    "passed": passed,
                    "confidence": confidence,
                    "fact_consistency": fact_consistency,
                    "completeness": completeness,
                    "source_diversity": source_diversity
                },
                reason=(
                    f"Semantic query evaluation: confidence={confidence:.2f}, "
                    f"fact_consistency={fact_consistency:.2f} → {'PASS' if passed else 'FAIL'}"
                ),
                confidence=confidence,
                metadata={
                    "avg_chunk_score": avg_score,
                    "total_length": total_length,
                    "citations_found": len(citations)
                }
            )
        except Exception as e:
            logger.warning(f"[Evaluator] Observability logging failed: {e}")

        return {
            "passed": passed,
            "completeness": round(completeness, 4),
            "consistency": round(consistency, 4),
            "confidence": round(confidence, 4),
            "information_gain": round(information_gain, 4),
            "source_diversity": round(source_diversity, 4),
            "fact_consistency": round(fact_consistency, 4),
            "coverage_estimate": round(coverage_estimate, 4),
            "feedback": (
                "评估通过" if passed
                else f"置信度({confidence:.2f})或事实一致性({fact_consistency:.2f})不足，请补充检索"
            ),
        }
    except Exception as e:
        logger.error(f"[Evaluator] error: {e}")
        return {
            "passed": False,
            "completeness": 0.5,
            "consistency": 0.5,
            "confidence": 0.5,
            "information_gain": 0.3,
            "source_diversity": 0.5,
            "fact_consistency": 0.5,
            "coverage_estimate": 0.5,
            "feedback": f"评估出错: {e}",
        }


# ── Issue #124: Strict Semantic Evaluator ───────────────────────────


class StrictSemanticEvaluator:
    """
    严格语义评估器 - 使用 LLM 验证答案是否真正回答了问题
    
    目标：避免分数通胀，让垃圾答案<0.5，一般答案0.5-0.7，好答案>0.75
    """
    
    def __init__(self):
        self.enabled = True  # Feature flag placeholder
    
    def evaluate_answer_quality(
        self,
        query: str,
        answer: str,
        chunks: List[dict],
        query_type: str = "semantic"
    ) -> dict:
        """
        使用LLM进行语义验证，判断答案是否真正回答了问题
        
        Returns:
            dict with keys: semantic_score, completeness, confidence, fact_consistency
        """
        try:
            # Import here to avoid circular dependency
            from app.agent.prompts import invoke_llm
            
            # 构造评估prompt
            prompt = f"""你是一个严格的答案质量评估员。判断这个答案是否**真正回答了**问题。

问题: {query}
答案: {answer}

评分标准（1-5分）：
1分：完全没回答，答非所问，或答案空洞无意义
2分：提到相关概念，但没有回答核心问题（例如：问"关系"，只列举了定义）
3分：部分回答，缺少关键信息或逻辑不完整
4分：基本回答，信息完整且符合问题要求
5分：完美回答，信息准确、全面且结构清晰

**判断规则**：
- 如果问题问的是"关系"、"区别"、"对比"，答案必须明确说明关系/区别，不能只列举定义
- 如果问题要求"计算"、"推导"，答案必须给出计算过程或结果
- 如果答案包含"无法回答"、"未找到"等拒绝回答的内容，给1分
- 如果答案过于简短（< 10字）且没有实质内容，给1-2分

只输出一个整数分数（1-5），不要任何解释或其他文字。"""
            
            messages = [
                SystemMessage(content="你是一个严格的质量评估专家。"),
                HumanMessage(content=prompt)
            ]
            
            response, _ = invoke_llm(messages, thinking=False, prefer_strong=False)
            score_text = response.content.strip()
            
            # 提取数字分数
            match = re.search(r"[1-5]", score_text)
            if match:
                llm_score = int(match.group())
            else:
                logger.warning(f"[StrictEvaluator] 无法解析LLM评分: {score_text}, 使用默认值3")
                llm_score = 3
            
            # 归一化到 0-1 区间
            normalized_score = (llm_score - 1) / 4.0
            
            # 基于LLM评分计算其他维度
            completeness = normalized_score
            confidence = normalized_score * 0.9  # 略打折扣
            
            # 事实一致性：检查答案内容是否来自chunks
            fact_consistency = self._check_fact_consistency(chunks, answer)
            
            # 信息增益：基于语义分数
            information_gain = max(0.1, normalized_score * 0.8)
            
            # 来源多样性：保留原有逻辑
            source_diversity = self._calc_source_diversity(chunks)
            
            # 覆盖率估计
            coverage_estimate = min(normalized_score * 1.1, 0.95)
            
            # 一致性：基于语义分数和事实一致性
            consistency = (normalized_score + fact_consistency) / 2
            
            # 判断是否通过：严格标准
            passed = (
                normalized_score >= 0.6  # 语义分数至少3.4/5 (60%)
                and fact_consistency >= 0.5  # 事实一致性至少50%
                and len(chunks) > 0  # 必须有检索结果
            )
            
            return {
                "passed": passed,
                "completeness": round(completeness, 4),
                "consistency": round(consistency, 4),
                "confidence": round(confidence, 4),
                "information_gain": round(information_gain, 4),
                "source_diversity": round(source_diversity, 4),
                "fact_consistency": round(fact_consistency, 4),
                "coverage_estimate": round(coverage_estimate, 4),
                "semantic_score": round(normalized_score, 4),
                "llm_raw_score": llm_score,
                "feedback": self._generate_feedback(passed, normalized_score, fact_consistency),
            }
            
        except Exception as e:
            logger.error(f"[StrictEvaluator] 语义评估失败: {e}", exc_info=True)
            # 降级到保守评分
            return {
                "passed": False,
                "completeness": 0.4,
                "consistency": 0.4,
                "confidence": 0.4,
                "information_gain": 0.3,
                "source_diversity": 0.4,
                "fact_consistency": 0.4,
                "coverage_estimate": 0.4,
                "semantic_score": 0.4,
                "llm_raw_score": 0,
                "feedback": f"评估失败（降级评分）: {e}",
            }
    
    def _check_fact_consistency(self, chunks: List[dict], answer: str) -> float:
        """
        检查答案中的事实是否来自检索结果
        
        启发式规则：
        - 检查答案中是否包含chunks的关键词
        - 检查是否有引用标注（【】或[]）
        """
        if not chunks or not answer:
            return 0.3
        
        # 检查引用标注
        citations = re.findall(r"【[^】]+】|\[\d+\]", answer)
        citation_score = min(len(citations) * 0.15, 0.4)
        
        # 检查关键词重叠
        chunk_texts = " ".join(c.get("content", "") for c in chunks[:5])  # 取前5个chunk
        overlap_count = 0
        answer_words = set(answer)
        for word in answer_words:
            if len(word) >= 2 and word in chunk_texts:
                overlap_count += 1
        
        overlap_score = min(overlap_count / 20, 0.5)  # 至少20个重叠词达到0.5
        
        # 综合评分
        fact_score = min(citation_score + overlap_score, 0.95)
        return round(fact_score, 4)
    
    def _calc_source_diversity(self, chunks: List[dict]) -> float:
        """计算来源多样性"""
        if not chunks:
            return 0.0
        
        sources = set()
        for c in chunks:
            source = c.get("source") or c.get("doc_id") or c.get("doc_filename") or ""
            if source:
                sources.add(source)
        
        # 3个及以上来源视为高多样性
        diversity = min(len(sources) / 3.0, 1.0)
        return round(diversity, 4)
    
    def _generate_feedback(self, passed: bool, semantic_score: float, fact_consistency: float) -> str:
        """生成反馈信息"""
        if passed:
            if semantic_score >= 0.8:
                return "评估通过 - 高质量答案"
            else:
                return "评估通过 - 答案符合基本要求"
        else:
            if semantic_score < 0.4:
                return f"语义质量不足({semantic_score:.2f}<0.6)，答案未真正回答问题"
            elif fact_consistency < 0.5:
                return f"事实一致性不足({fact_consistency:.2f}<0.5)，答案与检索结果关联性弱"
            else:
                return "未找到足够的检索结果"
