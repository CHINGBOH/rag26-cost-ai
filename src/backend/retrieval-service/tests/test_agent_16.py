"""
Agent 16 题验证脚本 — 深圳工程造价知识库
来源: data/knowledge_base/智能体问答.md
测试 /api/v1/agent 端点：结构检查 + 语义验证（ground_truth）
"""

import re
import time
import requests
from pathlib import Path
from datetime import datetime

BASE_URL = "http://localhost:8002"
QUESTION_FILE = Path(__file__).resolve().parents[4] / "data" / "knowledge_base" / "智能体问答.md"
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

# ── 测试用例（query + 语义验证规则）────────────────────────────────────────
# query_type: price | calculation | comparison | fact | trend
# expected_keywords: answer 中至少命中一个关键词（OR 逻辑）
# required_pattern: answer 必须匹配此正则（None 表示不检查）
# forbidden_pattern: answer 不得匹配此正则（None 表示不检查）
TEST_CASES = [
    {
        "query": "安装工程消耗量标准中送配电装置系统调试的计算规则是什么?",
        "query_type": "fact",
        "expected_keywords": ["系统", "调试", "计算", "消耗量", "安装"],
        "required_pattern": None,
        "forbidden_pattern": None,
    },
    {
        "query": "25 版装饰工程消耗量标准中，楼梯面层中玻璃地板的人工费是多少？",
        "query_type": "price",
        "expected_keywords": ["人工费", "工日", "元"],
        "required_pattern": r"\d+\.?\d*",  # 必须含数字
        "forbidden_pattern": None,
    },
    {
        "query": "对比深圳市2025年12月和2023年12月工程建设信息价中，电力电缆规格型号为0.6/1KV YJV 5×120的价格差异",
        "query_type": "comparison",
        "expected_keywords": ["2025", "2023", "电力电缆"],
        "required_pattern": None,  # 该规格在2025-12/2023-12无数据，正确答案是说明数据缺失
        "forbidden_pattern": None,
    },
    {
        "query": "根据深圳信息价分析下从25年开始至今的装配式混凝土预制构件价格走势",
        "query_type": "trend",
        "expected_keywords": ["装配式", "预制", "价格", "走势", "元"],
        "required_pattern": r"\d+\.?\d*",
        "forbidden_pattern": None,
    },
    {
        "query": "",
        "query_type": "price",
        "expected_keywords": ["铝合金门窗", "工日", "元", "371"],
        "required_pattern": r"\d+\.?\d*",
        "forbidden_pattern": None,
    },
    {
        "query": "详细说明深圳市工程建设地方标准中，关于安全文明施工费的组成内容、计算基数以及计取规定",
        "query_type": "fact",
        "expected_keywords": ["安全文明施工费", "计算基数", "组成", "计取"],
        "required_pattern": None,
        "forbidden_pattern": None,
    },
    {
        "query": "工程项目中施工地点要按照什么要求填写",
        "query_type": "fact",
        "expected_keywords": ["施工地点", "填写", "要求"],
        "required_pattern": None,
        "forbidden_pattern": None,
    },
    {
        "query": "2025版费率标准中，房建工程赶工措施费的推荐系数是多少？",
        "query_type": "price",
        "expected_keywords": ["赶工措施费", "推荐", "系数", "%"],
        "required_pattern": r"\d+\.?\d*\s*%",  # 必须含百分比数字
        "forbidden_pattern": None,
    },
    {
        "query": "一般计税方法下，税前工程造价中的费用是否包含进项税额？",
        "query_type": "fact",
        "expected_keywords": ["进项税", "税前", "包含", "不包含"],
        "required_pattern": None,
        "forbidden_pattern": None,
    },
    {
        "query": "总包管理服务费的计算基数是什么？",
        "query_type": "fact",
        "expected_keywords": ["总包管理服务费", "计算基数", "分包"],
        "required_pattern": None,
        "forbidden_pattern": None,
    },
    {
        "query": "模块化建筑工程施工工期定额适用于单体预制箱体应用比例大于多少的 ±0.00 以上工程？",
        "query_type": "fact",
        "expected_keywords": ["模块化", "预制箱体", "%", "比例"],
        "required_pattern": r"\d+\s*%",  # 必须给出百分比数值
        "forbidden_pattern": None,
    },
    {
        "query": "2023版与2025版费率标准中，利润率的参考范围是否一致？",
        "query_type": "comparison",
        "expected_keywords": ["利润率", "2023", "2025"],
        # 必须给出明确结论：一致 or 不一致
        "required_pattern": r"(一致|不一致|相同|不同|差异)",
        "forbidden_pattern": None,
    },
    {
        "query": "某工程人工费100万、材料费200万、机械费50万、企业管理费按推荐费率计算，按2025版推荐利润率计算，利润为多少？",
        "query_type": "calculation",
        "expected_keywords": ["利润", "万", "元"],
        "required_pattern": r"\d+\.?\d*\s*万",  # 必须给出带「万」单位的数值结果
        "forbidden_pattern": None,
    },
    {
        "query": "按2025版标准，如果机械费为0，企业管理费的计算基数是什么？",
        "query_type": "fact",
        "expected_keywords": ["企业管理费", "计算基数", "人工费", "机械费"],
        "required_pattern": None,
        "forbidden_pattern": None,
    },
    {
        "query": "2026年1月，中砂的价格是多少元/m³？",
        "query_type": "price",
        "expected_keywords": ["中砂", "元", "m³"],
        "required_pattern": r"\d+\.?\d*\s*元",
        "forbidden_pattern": None,
    },
    {
        "query": "2026年1月，电线、电缆价格较上月的变化幅度是多少？",
        "query_type": "price",
        "expected_keywords": ["电线", "电缆", "变化", "%", "元"],
        "required_pattern": r"\d+\.?\d*",
        "forbidden_pattern": None,
    },
]


def semantic_pass(answer: str, case: dict) -> tuple[bool, list[str]]:
    """语义验证：关键词命中 + 正则检查。返回 (passed, failures)"""
    failures = []

    # 1. 关键词：至少命中一个
    keywords = case.get("expected_keywords") or []
    if keywords and not any(kw in answer for kw in keywords):
        failures.append(f"关键词未命中（期望含其中之一：{keywords}）")

    # 2. 必须匹配正则
    req = case.get("required_pattern")
    if req and not re.search(req, answer):
        failures.append(f"required_pattern 未匹配：{req}")

    # 3. 禁止匹配正则
    forb = case.get("forbidden_pattern")
    if forb and re.search(forb, answer):
        failures.append(f"forbidden_pattern 命中：{forb}")

    return len(failures) == 0, failures


for index, question in enumerate(_load_questions()):
    TEST_CASES[index]["query"] = question


def test_case(case: dict, idx: int) -> dict:
    """测试单题"""
    query = case["query"]
    print(f"\n[{idx:02d}/16] [{case['query_type'].upper()}] {query[:45]}...")
    try:
        resp = requests.post(
            f"{BASE_URL}/api/v1/agent",
            json={"query": query, "session_id": f"eval-{RUN_ID}-{idx}"},
            timeout=300,
        )
        if resp.status_code != 200:
            print(f"  ❌ HTTP {resp.status_code}: {resp.text[:200]}")
            return {"ok": False, "error": f"HTTP {resp.status_code}", "query": query}

        data = resp.json()
        answer = data.get("answer", "")
        chunks = data.get("chunks", [])
        evaluation = data.get("evaluation") or {}
        iterations = data.get("iterations", 0)
        confidence = evaluation.get("confidence", 0) or 0

        # ── 结构检查 ──
        struct_checks = {
            "answer_non_empty": bool(answer and len(answer) > 10),
            "chunks_present": len(chunks) > 0,
            "evaluation_passed": bool(evaluation.get("passed", False)),
        }
        struct_ok = all(struct_checks.values())

        # ── 语义检查 ──
        sem_ok, sem_failures = semantic_pass(answer, case)

        all_passed = struct_ok and sem_ok
        status = "✅" if all_passed else ("⚠️ struct" if not struct_ok else "⚠️ semantic")

        print(f"  {status} | chars={len(answer)} chunks={len(chunks)} "
              f"conf={confidence:.3f} iters={iterations}")

        if not struct_ok:
            for k, v in struct_checks.items():
                if not v:
                    print(f"    ❌ {k}")
        if not sem_ok:
            for f in sem_failures:
                print(f"    ❌ {f}")
            # 打印 answer 前 200 字供调试
            print(f"    → answer[:200]: {answer[:200]!r}")

        return {
            "ok": all_passed,
            "query": query,
            "query_type": case["query_type"],
            "answer_len": len(answer),
            "chunks_count": len(chunks),
            "confidence": confidence,
            "iterations": iterations,
            "sem_failures": sem_failures,
        }
    except Exception as e:
        print(f"  ❌ Exception: {e}")
        return {"ok": False, "error": str(e), "query": query}


def main():
    print("=" * 60)
    print("Agent 16 题语义验证")
    print(f"Target: {BASE_URL}/api/v1/agent")
    print("=" * 60)

    results = []
    for idx, case in enumerate(TEST_CASES, 1):
        result = test_case(case, idx)
        results.append(result)
        time.sleep(0.5)

    # ── 汇总 ──
    passed = sum(1 for r in results if r.get("ok"))
    total = len(results)
    confidences = [r["confidence"] for r in results if "confidence" in r]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0

    # 按 query_type 统计
    from collections import defaultdict
    by_type: dict = defaultdict(lambda: {"pass": 0, "fail": 0})
    for r in results:
        qt = r.get("query_type", "unknown")
        if r.get("ok"):
            by_type[qt]["pass"] += 1
        else:
            by_type[qt]["fail"] += 1

    print("\n" + "=" * 60)
    print(f"总结果: {passed}/{total} 题通过")
    print(f"平均 confidence: {avg_conf:.3f}")
    print("\n按题型:")
    for qt, counts in sorted(by_type.items()):
        total_qt = counts["pass"] + counts["fail"]
        print(f"  {qt:<12} {counts['pass']}/{total_qt}")
    print("=" * 60)

    if passed < total:
        print("\n未通过题目:")
        for r in results:
            if not r.get("ok"):
                sem = r.get("sem_failures", [])
                hint = sem[0] if sem else r.get("error", "struct_fail")
                print(f"  - [{r.get('query_type','?')}] {r.get('query','?')[:50]}")
                print(f"    → {hint}")

    return passed == total


if __name__ == "__main__":
    import sys
    ok = main()
    sys.exit(0 if ok else 1)
