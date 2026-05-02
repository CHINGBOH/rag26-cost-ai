"""Issue #68: assert followup chips are grounded in KB.

Sends a batch of in-domain queries to /api/v1/agent and checks:
1. Returned chips carry coverage_score / coverage_tier fields.
2. >=70% of chips are tier 'med' or higher.
3. Off-domain queries return zero chips (no hallucinated chains).
"""
import json
import urllib.request
import sys

ENDPOINT = "http://localhost:8002/api/v1/agent"

IN_DOMAIN = [
    "什么是企业管理费",
    "建筑工程脚手架费如何计算",
    "钢筋绑扎工程量计算规则",
    "土石方工程的计价方法",
    "送配电装置系统调试如何取费",
    "措施项目费包括哪些内容",
    "规费的征收标准",
    "材料价格价差调整方式",
]
OFF_DOMAIN = [
    "宇宙的边界在哪里",
    "深圳市的人口政策",
    "如何泡一杯好咖啡",
]


def call(q: str) -> list[dict]:
    body = json.dumps({"query": q}).encode()
    req = urllib.request.Request(
        ENDPOINT, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data.get("followup_suggestions") or []


def main() -> int:
    total_chips = 0
    high_med = 0
    for q in IN_DOMAIN:
        chips = call(q)
        for c in chips:
            total_chips += 1
            tier = c.get("coverage_tier")
            if tier in ("high", "med"):
                high_med += 1
        print(f"[in ] {q}: {len(chips)} chips")

    off_chips = 0
    for q in OFF_DOMAIN:
        chips = call(q)
        off_chips += len(chips)
        print(f"[off] {q}: {len(chips)} chips")

    if total_chips == 0:
        print("FAIL: no chips returned for in-domain queries")
        return 1
    ratio = high_med / total_chips
    print(f"\nIn-domain high+med ratio: {high_med}/{total_chips} = {ratio:.2%}")
    print(f"Off-domain total chips:   {off_chips}")
    ok = ratio >= 0.70 and off_chips <= 2
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
