"""
Agent 16 题验证脚本
测试 /api/v1/agent 端点：answer 非空、chunks > 0、confidence >= 0.7
"""

import json
import time
import requests

BASE_URL = "http://localhost:8002"

# 16 个测试问题（覆盖概念、法规、计算、对比、案例等类型）
TEST_QUESTIONS = [
    "什么是工程量清单计价？",
    "建设工程造价咨询企业的资质等级如何划分？",
    "《建设工程工程量清单计价规范》GB50500 中，综合单价包含哪些费用？",
    "固定总价合同和固定单价合同有什么区别？",
    "工程变更估价的原则是什么？",
    "如何计算建筑安装工程费中的措施项目费？",
    "投标报价低于成本价如何认定？",
    "工程结算审计中，材料价差调整的方法有哪些？",
    "EPC 总承包模式下，造价控制的关键点是什么？",
    "BIM 技术在工程造价管理中的应用有哪些？",
    "什么是暂估价？如何结算？",
    "工程索赔的时效和程序要求是什么？",
    "装配式建筑的成本构成与传统建筑有何不同？",
    "全过程工程咨询的服务内容包括哪些？",
    "绿色建筑评价标准中，与造价相关的指标有哪些？",
    "如何编制招标控制价？",
]


def test_agent(query: str, idx: int) -> dict:
    """测试单个问题"""
    print(f"\n[{idx:02d}/16] 测试: {query[:40]}...")
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/agent",
            json={"query": query, "session_id": f"test-{idx}"},
            timeout=120,
        )
        if resp.status_code != 200:
            print(f"  ❌ HTTP {resp.status_code}: {resp.text[:200]}")
            return {"ok": False, "error": f"HTTP {resp.status_code}"}

        data = resp.json()
        answer = data.get("answer", "")
        chunks = data.get("chunks", [])
        evaluation = data.get("evaluation") or {}
        iterations = data.get("iterations", 0)

        # 检查标准
        checks = {
            "answer_non_empty": bool(answer and len(answer) > 10),
            "chunks_present": len(chunks) > 0,
            "confidence_ok": (evaluation.get("confidence") or 0) >= 0.7,
        }
        all_passed = all(checks.values())

        status = "✅" if all_passed else "⚠️"
        print(f"  {status} answer={len(answer)} chars, chunks={len(chunks)}, "
              f"confidence={evaluation.get('confidence', 0):.3f}, iterations={iterations}")

        if not all_passed:
            for k, v in checks.items():
                if not v:
                    print(f"    ❌ {k}")

        return {
            "ok": all_passed,
            "query": query,
            "answer_len": len(answer),
            "chunks_count": len(chunks),
            "confidence": evaluation.get("confidence", 0),
            "iterations": iterations,
            "evaluation": evaluation,
        }
    except Exception as e:
        print(f"  ❌ Exception: {e}")
        return {"ok": False, "error": str(e)}


def main():
    print("=" * 60)
    print("Agent 16 题验证")
    print(f"Target: {BASE_URL}/api/v1/agent")
    print("=" * 60)

    results = []
    for idx, query in enumerate(TEST_QUESTIONS, 1):
        result = test_agent(query, idx)
        results.append(result)
        time.sleep(0.5)  # 避免 rate limit

    # 统计
    passed = sum(1 for r in results if r.get("ok"))
    total = len(results)
    confidences = [r.get("confidence", 0) for r in results if "confidence" in r]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0

    print("\n" + "=" * 60)
    print(f"结果: {passed}/{total} 题通过")
    print(f"平均 confidence: {avg_conf:.3f}")
    print("=" * 60)

    if passed < total:
        print("\n未通过的题目:")
        for r in results:
            if not r.get("ok"):
                print(f"  - {r.get('query', '?')[:50]}")

    return passed == total


if __name__ == "__main__":
    import sys
    ok = main()
    sys.exit(0 if ok else 1)
