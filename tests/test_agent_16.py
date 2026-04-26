"""
Agent 16 题冒烟测试
逐条发 POST 到 /api/v1/agent，记录结构化响应
"""

import json
import time
import requests
from datetime import datetime

BASE_URL = "http://localhost:8002"
QUESTIONS = [
    "01. 安装工程消耗量标准中送配电装置系统调试的计算规则是什么？",
    "02. 25版装饰工程消耗量标准中，楼梯面层中玻璃地板的人工费是多少？",
    "03. 对比深圳市2025年12月和2023年12月工程建设信息价中，电力电缆规格型号为0.6/1KV YJV 5×120的价格差异",
    "04. 根据深圳信息价分析下从25年开始至今的装配式混凝土预制构件价格走势",
    "05. 2025年深圳信息价中钛合金门窗的价格是多少",
    "06. 详细说明深圳市工程建设地方标准中，关于安全文明施工费的组成内容、计算基数以及计取规定",
    "07. 工程项目中施工地点要按照什么要求填写",
    "08. 2025版费率标准中，房建工程赶工措施费的推荐系数是多少？",
    "09. 一般计税方法下，税前工程造价中的费用是否包含进项税额？",
    "10. 总包管理服务费的计算基数是什么？",
    "11. 模块化建筑工程施工工期定额适用于单体预制箱体应用比例大于多少的±0.00以上工程？",
    "12. 2023版与2025版费率标准中，利润率的参考范围是否一致？",
    "13. 某工程人工费100万、材料费200万、机械费50万、企业管理费25万，企业管理费率是多少？",
    "14. 按2025版标准，如果机械费为0，企业管理费的计算基数是什么",
    "15. 2026年1月，中砂的价格是多少元/m³？",
    "16. 2026年1月，电线、电缆价格较上月的变化幅度是多少？",
]


def test_one(idx: int, query: str) -> dict:
    print(f"\n[{idx:02d}/16] {query[:60]}...")
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/agent",
            json={"query": query, "session_id": f"test-{idx:02d}", "max_iterations": 3},
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

        # 检查 LLM 未配置情况
        llm_unconfigured = "[检索结果摘要，未配置 LLM]" in answer or "[Agent 执行错误" in answer

        # 强化 passed 判断：必须有 chunks 且 confidence > 0.4
        has_chunks = len(chunks) > 0
        high_conf = evaluation.get("confidence", 0) > 0.4
        real_passed = has_chunks and high_conf and not llm_unconfigured

        result = {
            "ok": True,
            "query": query,
            "answer_preview": answer[:200],
            "answer_len": len(answer),
            "chunks_count": len(chunks),
            "confidence": evaluation.get("confidence", 0),
            "passed": real_passed,
            "api_passed": evaluation.get("passed", False),
            "iterations": iterations,
            "llm_unconfigured": llm_unconfigured,
            "evaluation": evaluation,
        }

        status = "✅" if result["passed"] else ("⚠️" if result["api_passed"] else "❌")
        print(f"  {status} chunks={result['chunks_count']}, confidence={result['confidence']:.3f}, passed={result['passed']}, iters={result['iterations']}")
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
