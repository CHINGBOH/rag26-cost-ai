"""
Retrieval Filter — 检索结果后处理层
功能：分数阈值过滤、内容去重、Token Budget 裁剪
"""

import hashlib
import logging

logger = logging.getLogger(__name__)

# 分数阈值：不同来源的分数体系不同，必须分别设定
# - pgvector/hybrid_vector: 余弦相似度，0~1，有意义区间 0.40+
# - pg_fulltext/hybrid_text: ts_rank，中文自然值 0.01~0.20，不能用 0.60
# - fee_rates: 结构化精确查询，score 固定为 0.90，实际不过滤
SCORE_THRESHOLDS: dict[str, float] = {
    "pgvector":        0.40,
    "pg_fulltext":     0.01,
    "hybrid_vector":   0.40,
    "hybrid_text":     0.01,
    "fee_rates":       0.00,
    "default":         0.40,
}
# 保留旧名称，供外部调用方向后兼容（用 default 值）
SCORE_THRESHOLD = SCORE_THRESHOLDS["default"]
MAX_CONTEXT_TOKENS = 6000
MAX_CHUNKS = 8


def _passes_threshold(chunk: dict) -> bool:
    """根据 source_db 字段选择对应阈值判断 chunk 是否通过过滤"""
    src = chunk.get("source_db") or chunk.get("database") or "default"
    threshold = SCORE_THRESHOLDS.get(src, SCORE_THRESHOLDS["default"])
    return chunk.get("score", 0) >= threshold


def filter_chunks(
    chunks: list[dict],
    threshold: float = SCORE_THRESHOLD,
    max_tokens: int = MAX_CONTEXT_TOKENS,
    max_chunks: int = MAX_CHUNKS,
) -> list[dict]:
    """
    对检索结果进行多级过滤：
      1. 分数阈值过滤（按 source_db 分别使用对应阈值，忽略 threshold 参数）
      2. 内容 hash 去重
      3. 按分数排序取 top-N
      4. Token budget 裁剪（超限时截断而非丢弃高分 chunk）

    注意：threshold 参数保留以维持向后兼容，实际过滤逻辑使用 _passes_threshold()。
    """
    if not chunks:
        return []

    # 1. 分数阈值过滤（per-source）
    filtered = [c for c in chunks if _passes_threshold(c)]
    if not filtered:
        logger.warning(
            f"[filter] all {len(chunks)} chunks below per-source thresholds"
            f" (sources: {set(c.get('source_db','?') for c in chunks)})"
        )
        # 如果全部低于阈值，至少保留最高分的一条（避免完全无结果）
        if chunks:
            best = max(chunks, key=lambda x: x.get("score", 0))
            filtered = [best]

    # 2. 内容 hash 去重
    seen_hashes = set()
    unique = []
    for c in filtered:
        content = c.get("content", "")
        h = hashlib.md5(content.encode()).hexdigest()
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique.append(c)
    filtered = unique

    # 3. 按分数排序，取 top-N
    filtered = sorted(filtered, key=lambda x: x.get("score", 0), reverse=True)[:max_chunks]

    # 4. Token budget 裁剪
    total_tokens = 0
    result = []
    for c in filtered:
        content = c.get("content", "")
        tokens = len(content) // 3  # 粗估：中文字符 ≈ 1 token / 字
        if total_tokens + tokens > max_tokens:
            remaining = (max_tokens - total_tokens) * 3
            if remaining > 200 and c.get("score", 0) > 0.75:
                # 高分 chunk 截断保留
                truncated = {**c, "content": content[:remaining] + "...（截断）"}
                result.append(truncated)
                total_tokens += remaining // 3
            break
        result.append(c)
        total_tokens += tokens

    logger.info(
        f"[filter] {len(chunks)} → {len(result)} chunks, "
        f"threshold={threshold}, max_chunks={max_chunks}, tokens≈{total_tokens}"
    )
    return result
