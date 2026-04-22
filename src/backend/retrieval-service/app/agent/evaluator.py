"""
Evaluator Node — 7 维检索质量评分
复用 api.py /api/v1/evaluate 的评分逻辑
"""

import re
import logging
from typing import List, Dict, Any

from langchain_core.messages import AIMessage

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
