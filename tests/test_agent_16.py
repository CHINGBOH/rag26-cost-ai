"""
Agent 16 题冒烟测试
逐条发 POST 到 /api/v1/agent，记录结构化响应

判定标准（三重门）：
  1. has_chunks: 检索到文本块
  2. not_refused: answer 不含拒绝回答模式（"无法回答"等）
  3. has_keyword: answer 包含该题的期望关键词

三者全满足才算 passed。confidence 仅作参考，不作判定依据。
"""

import json
import time
import requests
from datetime import datetime
from pathlib import Path

BASE_URL = "http://localhost:8002"
QUESTION_FILE = Path(__file__).resolve().parents[1] / "data" / "knowledge_base" / "智能体问答.md"
RUN_ID = datetime.now().strftime("%Y%m%d%H%M%S")


def _load_questions() -> list[str]:
    questions: list[str] = []
    for line in QUESTION_FILE.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        parts = [part.strip() for part in line.split("|")[1:-1]]
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        questions.append(parts[2])
    return questions

# 拒绝回答模式 —— answer 包含任意一个即视为 FAIL
REFUSAL_PATTERNS = [
    "无法直接回答", "无法回答", "无法提供", "无法分析",
    "无法对比", "无法计算", "不足以回答", "均显示为N/A",
    "无相关数据", "无法得出", "无法给出",
    # "未包含" 已移除：该词常出现于"其他来源未包含XX但已从来源Y取得答案"
    # 这类上下文说明不代表拒绝回答，保留会造成 Q8 假阳性
]

# 每题期望答案必须包含的关键词（任意一个命中即可）
# None 表示该题数据库确认无数据，只要不拒绝且有 chunks 即可
EXPECTED_KEYWORDS = [
    # Q01 安装工程消耗量标准送配电调试
    ["送配电", "系统调试", "计算规则", "计量单位"],
    # Q02 玻璃地板人工费
    ["玻璃地板", "人工费", "工日", "元"],
    # Q03 电力电缆价格对比
    ["YJV", "价格", "元", "差异", "2025", "2023"],
    # Q04 装配式混凝土预制构件走势
    ["装配式", "预制构件", "价格", "走势", "元"],
    # Q05 铝合金门窗工人工价格
    ["371", "铝合金门窗", "工日"],
    # Q06 安全文明施工费
    ["安全文明施工费", "计算基数", "费率"],
    # Q07 施工地点填写
    ["施工地点", "行政区域", "填写"],
    # Q08 赶工措施费推荐系数
    ["赶工", "推荐系数", "1.0%", "1%"],
    # Q09 进项税额
    ["进项税额", "不包含", "税前工程造价"],
    # Q10 总包管理服务费计算基数
    ["总包管理", "分包工程", "计算基数"],
    # Q11 模块化建筑工期定额
    ["模块化", "预制箱体", "比例", "%"],
    # Q12 利润率对比
    ["利润率", "2023", "2025", "一致", "不一致"],
    # Q13 利润计算
    ["利润", "20.44%", "5%", "万"],
    # Q14 机械费为0时计算基数
    ["人工费", "计算基数", "机械费"],
    # Q15 中砂价格
    ["中砂", "元", "m³", "/m³"],
    # Q16 电线电缆价格变化
    ["电线", "电缆", "变化", "上月", "%", "元"],
]

QUESTIONS = _load_questions()


def _is_refused(answer: str) -> tuple[bool, str]:
    """检查 answer 是否包含拒绝回答模式，返回 (is_refused, matched_pattern)"""
    for pat in REFUSAL_PATTERNS:
        if pat in answer:
            return True, pat
    return False, ""


def _has_expected_keyword(answer: str, keywords: list[str]) -> tuple[bool, str]:
    """检查 answer 是否包含期望关键词，返回 (found, matched_keyword)"""
    for kw in keywords:
        if kw in answer:
            return True, kw
    return False, ""


def test_one(idx: int, query: str) -> dict:
    print(f"\n[{idx:02d}/16] {query[:60]}...")
    expected_kws = EXPECTED_KEYWORDS[idx - 1]
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/agent",
            json={"query": query, "session_id": f"test-{RUN_ID}-{idx:02d}", "max_iterations": 3},
            timeout=300,
        )
        if resp.status_code != 200:
            err = f"HTTP {resp.status_code}: {resp.text[:200]}"
            print(f"  ❌ {err}")
            return {"ok": False, "error": err, "query": query}

        data = resp.json()
        answer = data.get("answer", "")
        chunks = data.get("chunks", [])
        evaluation = data.get("evaluation") or {}
        iterations = data.get("iterations", 0)
        api_passed = bool(evaluation.get("passed", False))

        llm_unconfigured = "[检索结果摘要，未配置 LLM]" in answer or "[Agent 执行错误" in answer

        # 三重门判定
        has_chunks = len(chunks) > 0
        refused, refusal_pat = _is_refused(answer)
        kw_found, matched_kw = _has_expected_keyword(answer, expected_kws)

        real_passed = has_chunks and not refused and kw_found and api_passed and not llm_unconfigured

        fail_reason = ""
        if not has_chunks:
            fail_reason = "no_chunks"
        elif refused:
            fail_reason = f"refused({refusal_pat})"
        elif not api_passed:
            fail_reason = f"api_failed({evaluation.get('feedback', 'unknown')})"
        elif not kw_found:
            fail_reason = f"missing_keyword(expected_one_of={expected_kws[:3]}...)"

        result = {
            "ok": True,
            "query": query,
            "answer_preview": answer[:300],
            "answer_len": len(answer),
            "chunks_count": len(chunks),
            "confidence": evaluation.get("confidence", 0),
            "passed": real_passed,
            "fail_reason": fail_reason,
            "matched_keyword": matched_kw,
            "api_passed": api_passed,
            "iterations": iterations,
            "llm_unconfigured": llm_unconfigured,
            "evaluation": evaluation,
        }

        if real_passed:
            print(f"  ✅ chunks={result['chunks_count']}, conf={result['confidence']:.3f}, keyword='{matched_kw}', iters={iterations}")
        else:
            print(f"  ❌ chunks={result['chunks_count']}, conf={result['confidence']:.3f}, FAIL={fail_reason}, iters={iterations}")
            print(f"     answer: {answer[:120]}")
        if llm_unconfigured:
            print(f"  ⚠️  LLM 未配置或执行错误")
        return result

    except Exception as e:
        print(f"  ❌ Exception: {e}")
        return {"ok": False, "error": str(e), "query": query}


def main():
    print("=" * 70)
    print(f"Agent 16 题冒烟测试 | {datetime.now().isoformat()}")
    print(f"Target: {BASE_URL}/api/v1/agent")
    print("=" * 70)

    results = []
    for idx, q in enumerate(QUESTIONS, 1):
        results.append(test_one(idx, q))
        # time.sleep(0.5)  # 并行跑时不需要

    # 汇总统计
    passed_count = sum(1 for r in results if r.get("passed"))
    ok_count = sum(1 for r in results if r.get("ok"))
    error_count = len(results) - ok_count
    confidences = [r.get("confidence", 0) for r in results if r.get("ok")]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0
    llm_unconfigured_count = sum(1 for r in results if r.get("llm_unconfigured"))

    print("\n" + "=" * 70)
    print("汇总")
    print("=" * 70)
    print(f"  总题数:    {len(results)}")
    print(f"  成功响应:  {ok_count}")
    print(f"  报错:      {error_count}")
    print(f"  passed:    {passed_count}")
    print(f"  平均 confidence: {avg_conf:.3f}")
    print(f"  LLM 未配置/错误: {llm_unconfigured_count}")

    # 写 JSON
    output = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total": len(results),
            "ok": ok_count,
            "errors": error_count,
            "passed": passed_count,
            "avg_confidence": avg_conf,
            "llm_unconfigured": llm_unconfigured_count,
        },
        "results": results,
    }

    with open("logs/agent_test_16_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: logs/agent_test_16_results.json")

    return error_count == 0


if __name__ == "__main__":
    import sys
    ok = main()
    sys.exit(0 if ok else 1)
