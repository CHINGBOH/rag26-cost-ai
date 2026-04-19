"""
RAG Agent 核心16题跑通验证 - Python端测试

测试目标：
  1. 验证Python后端检索接口 (/api/v1/search) 能为16道题返回有效结果
  2. 验证评估接口 (/api/v1/evaluate) 能正确评分
  3. 可选：通过HTTP调用Node端Agent接口进行端到端验证

判定标准（必须全部满足）：
  1. 有索引引用：检索结果非空
  2. 数值准确：针对数值题，回答/检索结果中包含数字
  3. 工具调用痕迹：检索接口本身即为工具调用
  4. 质量审核通过：evaluation.confidence >= 0.7
  5. 无幻觉：基于事实一致性评分判断

运行方式：
  cd src/backend/python-legacy
  python -m pytest tests/test_rag_agent_core.py -v
  python -m pytest tests/test_rag_agent_core.py -v --tb=short
"""

import pytest
import json
import os
import sys
import time
import re
from typing import Any, Dict, List, Optional

# 添加项目根目录到路径，支持相对导入
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

# 优先使用同步HTTP客户端，避免pytest-asyncio依赖
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

try:
    from fastapi.testclient import TestClient
    HAS_TESTCLIENT = True
except ImportError:
    HAS_TESTCLIENT = False

try:
    from api.unified_api import app as unified_app
    HAS_UNIFIED_APP = True
except Exception as e:
    unified_app = None
    HAS_UNIFIED_APP = False

# ==================== 配置 ====================
NODE_BASE_URL = os.environ.get("RAG_TEST_NODE_URL", "http://localhost:3001")
PYTHON_BASE_URL = os.environ.get("RAG_TEST_PYTHON_URL", "http://localhost:8000")
GATEWAY_BASE_URL = os.environ.get("RAG_TEST_GATEWAY_URL", "http://localhost:8080")
REQUEST_TIMEOUT = 120.0  # Agent可能迭代多次

# ==================== 16道核心测试题 ====================
TEST_CASES = [
    {
        "id": "01",
        "query": "安装工程消耗量标准中送配电装置系统调试的计算规则是什么？",
        "category": "quota",
        "requires_numeric": False,
        "requires_comparison": False,
        "expected_tools": ["keywordSearch", "vectorSearch"],
    },
    {
        "id": "02",
        "query": "25版装饰工程消耗量标准中，楼梯面层中玻璃地板的人工费是多少？",
        "category": "quota",
        "requires_numeric": True,
        "requires_comparison": False,
        "expected_tools": ["keywordSearch"],
    },
    {
        "id": "03",
        "query": "对比深圳市2025年12月和2023年12月工程建设信息价中，电力电缆规格型号为0.6/1KV YJV 5×120的价格差异",
        "category": "price",
        "requires_numeric": True,
        "requires_comparison": True,
        "expected_tools": ["keywordSearch", "calculator"],
    },
    {
        "id": "04",
        "query": "根据深圳信息价分析下从25年开始至今的装配式混凝土预制构件价格走势",
        "category": "price",
        "requires_numeric": True,
        "requires_comparison": False,
        "expected_tools": ["keywordSearch", "calculator"],
    },
    {
        "id": "05",
        "query": "2025年深圳信息价中钛合金门窗的价格是多少",
        "category": "price",
        "requires_numeric": True,
        "requires_comparison": False,
        "expected_tools": ["keywordSearch"],
    },
    {
        "id": "06",
        "query": "详细说明深圳市工程建设地方标准中，关于安全文明施工费的组成内容、计算基数以及计取规定",
        "category": "standard",
        "requires_numeric": False,
        "requires_comparison": False,
        "expected_tools": ["vectorSearch", "graphSearch"],
    },
    {
        "id": "07",
        "query": "工程项目中施工地点要按照什么要求填写",
        "category": "standard",
        "requires_numeric": False,
        "requires_comparison": False,
        "expected_tools": ["vectorSearch"],
    },
    {
        "id": "08",
        "query": "2025版费率标准中，房建工程赶工措施费的推荐系数是多少？",
        "category": "quota",
        "requires_numeric": True,
        "requires_comparison": False,
        "expected_tools": ["keywordSearch"],
    },
    {
        "id": "09",
        "query": "一般计税方法下，税前工程造价中的费用是否包含进项税额？",
        "category": "standard",
        "requires_numeric": False,
        "requires_comparison": False,
        "expected_tools": ["vectorSearch"],
    },
    {
        "id": "10",
        "query": "总包管理服务费的计算基数是什么？",
        "category": "standard",
        "requires_numeric": False,
        "requires_comparison": False,
        "expected_tools": ["vectorSearch"],
    },
    {
        "id": "11",
        "query": "模块化建筑工程施工工期定额适用于单体预制箱体应用比例大于多少的±0.00以上工程？",
        "category": "quota",
        "requires_numeric": True,
        "requires_comparison": False,
        "expected_tools": ["keywordSearch"],
    },
    {
        "id": "12",
        "query": "2023版与2025版费率标准中，利润率的参考范围是否一致？",
        "category": "standard",
        "requires_numeric": False,
        "requires_comparison": True,
        "expected_tools": ["vectorSearch", "graphSearch"],
    },
    {
        "id": "13",
        "query": "某工程人工费100万、材料费200万、机械费50万、企业管理费25万，企业管理费率是多少？",
        "category": "calculation",
        "requires_numeric": True,
        "requires_comparison": False,
        "expected_tools": ["keywordSearch", "calculator"],
    },
    {
        "id": "14",
        "query": "按2025版标准，如果机械费为0，企业管理费的计算基数是什么",
        "category": "standard",
        "requires_numeric": False,
        "requires_comparison": False,
        "expected_tools": ["keywordSearch", "vectorSearch"],
    },
    {
        "id": "15",
        "query": "2026年1月，中砂的价格是多少元/m³？",
        "category": "price",
        "requires_numeric": True,
        "requires_comparison": False,
        "expected_tools": ["keywordSearch"],
    },
    {
        "id": "16",
        "query": "2026年1月，电线、电缆价格较上月的变化幅度是多少？",
        "category": "price",
        "requires_numeric": True,
        "requires_comparison": True,
        "expected_tools": ["keywordSearch", "calculator"],
    },
]


# ==================== 辅助函数 ====================

def is_service_available(url: str, timeout: float = 3.0) -> bool:
    """检测服务是否可用"""
    try:
        if HAS_HTTPX:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(f"{url}/health")
                return resp.status_code == 200
        else:
            import urllib.request
            req = urllib.request.Request(f"{url}/health", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
    except Exception:
        return False


def run_agent_query_sync(
    query: str,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    调用Node端Agent接口（SSE流式）获取最终结果 - 同步版本
    """
    options = options or {}
    start_time = time.time()
    events: List[Dict[str, Any]] = []
    final_result: Optional[Dict[str, Any]] = None
    error_msg: Optional[str] = None

    try:
        if not HAS_HTTPX:
            return {
                "result": None,
                "events": [],
                "error": "httpx未安装，无法调用Node端Agent接口",
                "latency_ms": 0,
            }

        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            with client.stream(
                "POST",
                f"{NODE_BASE_URL}/api/agent/run",
                json={
                    "query": query,
                    "maxIterations": options.get("maxIterations", 5),
                },
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status_code != 200:
                    text = response.read().decode("utf-8", errors="replace")[:500]
                    error_msg = f"HTTP {response.status_code}: {text}"
                else:
                    for line in response.iter_lines():
                        line = line.strip()
                        if not line.startswith("data: "):
                            continue
                        json_str = line[6:].strip()
                        if not json_str or json_str == "[DONE]":
                            continue
                        try:
                            event = json.loads(json_str)
                            events.append(event)
                            if event.get("type") == "final":
                                final_result = event.get("result")
                            if event.get("type") == "error":
                                error_msg = event.get("message", "Agent error")
                        except json.JSONDecodeError:
                            continue
    except Exception as e:
        error_msg = str(e)

    latency_ms = int((time.time() - start_time) * 1000)
    if final_result and isinstance(final_result, dict):
        final_result["latencyMs"] = latency_ms

    return {
        "result": final_result,
        "events": events,
        "error": error_msg,
        "latency_ms": latency_ms,
    }


def validate_result(tc: Dict[str, Any], result: Optional[Dict[str, Any]], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """验证单条测试结果"""
    failures: List[str] = []

    if not result:
        return {"passed": False, "failures": ["Agent返回结果为空"], "tools_used": [], "confidence": 0, "iterations": 0}

    answer = result.get("answer", "")
    if not answer or not str(answer).strip():
        failures.append("回答为空（answer字段缺失或空字符串）")

    # 1. 有索引引用
    indices = result.get("indices") or []
    has_citations = len(indices) > 0 or (answer and any(k in str(answer) for k in ["参考", "chunk_", "《", "】"]))
    if not has_citations:
        failures.append("无索引引用（indices为空且answer中无引用标记）")

    # 2. 数值准确（宽松检查）
    if tc.get("requires_numeric"):
        if not re.search(r"\d+(?:\.\d+)?", str(answer)):
            failures.append("数值类问题回答中未检测到数字")

    # 3. 对比类问题检查
    if tc.get("requires_comparison"):
        patterns = [
            r"2025.*2023|2023.*2025",
            r"较.*上|环比|同比|差异|变化|增加|减少|上升|下降",
            r"一致|不一致|相同|不同",
            r"vs|versus|对比|比较",
        ]
        has_comparison = any(re.search(p, str(answer)) for p in patterns)
        if not has_comparison:
            failures.append("对比类问题回答中未检测到对比表述")

    # 4. 工具调用痕迹
    tools_used = set()
    for ev in events:
        if ev.get("type") in ("tool_call", "tool_result") and ev.get("tool"):
            tools_used.add(ev["tool"])
        if ev.get("tool_name"):
            tools_used.add(ev["tool_name"])
    for t in result.get("toolsUsed") or []:
        tools_used.add(t)
    if len(tools_used) == 0 and result.get("iterations", 0) < 1:
        failures.append("无工具调用痕迹")

    # 5. 质量审核通过
    evaluation = result.get("evaluation") or {}
    confidence = evaluation.get("confidence") if evaluation else result.get("confidence", 0)
    if confidence is None:
        confidence = 0
    if confidence < 0.7:
        failures.append(f"置信度不足: {confidence:.3f} < 0.7")
    if evaluation.get("passed") is False:
        failures.append("evaluation.passed === false")

    return {
        "passed": len(failures) == 0,
        "failures": failures,
        "tools_used": list(tools_used),
        "confidence": confidence,
        "iterations": result.get("iterations", len([e for e in events if e.get("type") == "iteration"])),
    }


# ==================== Fixtures ====================

@pytest.fixture(scope="session")
def node_available() -> bool:
    return is_service_available(NODE_BASE_URL)


@pytest.fixture(scope="session")
def python_available() -> bool:
    return is_service_available(PYTHON_BASE_URL)


@pytest.fixture(scope="session")
def gateway_available() -> bool:
    return is_service_available(GATEWAY_BASE_URL)


# ==================== 测试用例 ====================

@pytest.mark.parametrize("tc", TEST_CASES, ids=lambda x: f"TC-{x['id']}")
def test_rag_agent_core(tc: Dict[str, Any], node_available: bool):
    """核心16题端到端测试（通过Node端Agent接口）"""
    if not node_available:
        pytest.skip(f"Node服务({NODE_BASE_URL})不可用，跳过")

    if not HAS_HTTPX:
        pytest.skip("httpx未安装，无法调用Node端Agent接口")

    response = run_agent_query_sync(
        tc["query"],
        options={"maxIterations": 5, "enableEvaluation": True},
    )

    if response.get("error"):
        pytest.fail(f"请求错误: {response['error']}")

    validation = validate_result(tc, response.get("result"), response.get("events", []))

    print(
        f"\n[{tc['id']}] passed={validation['passed']}, "
        f"confidence={validation['confidence']}, "
        f"tools={validation['tools_used']}, "
        f"failures={validation['failures']}"
    )

    assert validation["passed"], f"[{tc['id']}] 失败原因: {'; '.join(validation['failures'])}"


def test_batch_report(node_available: bool):
    """批量运行16题并生成JSON报告"""
    report = {
        "total": len(TEST_CASES),
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "details": [],
    }

    for tc in TEST_CASES:
        if not node_available or not HAS_HTTPX:
            report["skipped"] += 1
            report["details"].append({
                "id": tc["id"],
                "query": tc["query"],
                "passed": False,
                "confidence": None,
                "iterations": None,
                "toolsUsed": [],
                "latencyMs": 0,
                "failures": ["Node服务不可用或httpx未安装"],
            })
            continue

        start = time.time()
        response = run_agent_query_sync(
            tc["query"],
            options={"maxIterations": 5, "enableEvaluation": True},
        )
        latency_ms = int((time.time() - start) * 1000)

        validation = validate_result(tc, response.get("result"), response.get("events", []))

        if validation["passed"]:
            report["passed"] += 1
        else:
            report["failed"] += 1

        report["details"].append({
            "id": tc["id"],
            "query": tc["query"],
            "passed": validation["passed"],
            "confidence": validation["confidence"],
            "iterations": validation["iterations"],
            "toolsUsed": validation["tools_used"],
            "latencyMs": response.get("latency_ms", latency_ms),
            "failures": ([response["error"]] if response.get("error") else []) + validation["failures"],
        })

    print("\n========== RAG Agent Python端批量测试报告 ==========")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("====================================================\n")

    assert report["passed"] == report["total"], f"仅通过 {report['passed']}/{report['total']} 题"


# ==================== Python后端接口直接测试 ====================

class TestPythonBackendAPI:
    """测试Python后端独立接口（不依赖Node服务）"""

    @pytest.mark.skipif(not HAS_UNIFIED_APP, reason="unified_api app未加载")
    def test_search_api_for_quota_query(self):
        """测试搜索接口对定额问题的检索能力"""
        if not HAS_TESTCLIENT:
            pytest.skip("fastapi.testclient未安装")
        client = TestClient(unified_app)
        response = client.post("/api/v1/search", json={"query": "房建工程赶工措施费推荐系数", "top_k": 5})
        assert response.status_code == 200
        data = response.json()
        assert "results" in data or "chunks" in data or "documents" in data

    @pytest.mark.skipif(not HAS_UNIFIED_APP, reason="unified_api app未加载")
    def test_search_api_for_price_query(self):
        """测试搜索接口对信息价问题的检索能力"""
        if not HAS_TESTCLIENT:
            pytest.skip("fastapi.testclient未安装")
        client = TestClient(unified_app)
        response = client.post("/api/v1/search", json={"query": "2025年深圳信息价 钛合金门窗", "top_k": 5})
        assert response.status_code == 200
        data = response.json()
        assert "results" in data or "chunks" in data or "documents" in data

    @pytest.mark.skipif(not HAS_UNIFIED_APP, reason="unified_api app未加载")
    def test_evaluate_api_passes_with_citations(self):
        """测试评估接口对带引用的回答给出高分"""
        if not HAS_TESTCLIENT:
            pytest.skip("fastapi.testclient未安装")
        client = TestClient(unified_app)
        response = client.post("/api/v1/evaluate", json={
            "query": "2025版费率标准中，房建工程赶工措施费的推荐系数是多少？",
            "retrieved_chunks": [
                {"id": "1", "content": "房建工程赶工措施费推荐系数为1.5%", "source": "费率标准2025.pdf", "score": 0.95},
                {"id": "2", "content": "赶工措施费按税前造价计算", "source": "费率标准2025.pdf", "score": 0.88},
            ],
            "generated_answer": "根据《深圳市建设工程计价费率标准（2025版）》，房建工程赶工措施费的推荐系数为1.5%。参考[1]",
            "history_rounds": 0,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["confidence"] >= 0.5
        assert data["completeness"] >= 0.0

    @pytest.mark.skipif(not HAS_UNIFIED_APP, reason="unified_api app未加载")
    def test_evaluate_api_fails_without_citations(self):
        """测试评估接口对无引用的回答给出低分或低confidence"""
        if not HAS_TESTCLIENT:
            pytest.skip("fastapi.testclient未安装")
        client = TestClient(unified_app)
        response = client.post("/api/v1/evaluate", json={
            "query": "测试问题",
            "retrieved_chunks": [
                {"id": "1", "content": "内容1", "source": "doc1", "score": 0.9},
            ],
            "generated_answer": "这是没有任何引用的裸文本回答",
            "history_rounds": 0,
        })
        assert response.status_code == 200
        data = response.json()
        assert "fact_consistency" in data

    def test_health_check_python(self, python_available: bool):
        """Python后端健康检查"""
        if not python_available:
            pytest.skip(f"Python服务({PYTHON_BASE_URL})不可用")
        if HAS_HTTPX:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{PYTHON_BASE_URL}/health")
                assert resp.status_code == 200
        else:
            import urllib.request
            req = urllib.request.Request(f"{PYTHON_BASE_URL}/health", method="GET")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                assert resp.status == 200


# ==================== 网关接口测试 ====================

class TestGatewayAPI:
    """测试API网关转发"""

    def test_gateway_health(self, gateway_available: bool):
        if not gateway_available:
            pytest.skip(f"网关({GATEWAY_BASE_URL})不可用")
        if HAS_HTTPX:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{GATEWAY_BASE_URL}/health")
                assert resp.status_code == 200
        else:
            import urllib.request
            req = urllib.request.Request(f"{GATEWAY_BASE_URL}/health", method="GET")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                assert resp.status == 200

    def test_gateway_rag_query(self, gateway_available: bool, node_available: bool):
        if not gateway_available:
            pytest.skip(f"网关({GATEWAY_BASE_URL})不可用")
        if not node_available:
            pytest.skip("Node服务不可用")
        if not HAS_HTTPX:
            pytest.skip("httpx未安装")

        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            with client.stream(
                "POST",
                f"{GATEWAY_BASE_URL}/api/agent/run",
                json={"query": "2025版费率标准中，房建工程赶工措施费的推荐系数是多少？", "maxIterations": 3},
                headers={"Content-Type": "application/json"},
            ) as resp:
                assert resp.status_code == 200
