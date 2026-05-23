#!/usr/bin/env python3
"""
RAG26 CLI — 全功能命令行入口
直调 retrieval-service HTTP API (默认 :8002)，无需 Web 前端。
每条命令支持 --json 模式，供 Hermes/Agent 编程调用。
"""

import sys
import json
import argparse
import urllib.request
import urllib.error
import os
from pathlib import Path

# ── 配置 ────────────────────────────────────────────────────────────────
_api_url = os.environ.get("RETRIEVAL_API_URL", "http://localhost:8002").rstrip("/")
OCR_URL = os.environ.get("OCR_SERVICE_URL", "http://localhost:8001").rstrip("/")
DEFAULT_TIMEOUT = 60


def _curl(method: str, url: str, data=None, timeout=DEFAULT_TIMEOUT):
    """简易 HTTP 客户端"""
    req = urllib.request.Request(url, method=method)
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    else:
        body = None

    try:
        resp = urllib.request.urlopen(req, data=body, timeout=timeout)
        return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"error": str(e), "status_code": e.code}
    except Exception as e:
        return {"error": str(e)}


def _output(data, args):
    """统一输出：--json 模式输出 JSON，否则 pretty print"""
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _pretty(data)


def _pretty(data):
    """人类可读输出"""
    if isinstance(data, dict):
        if "error" in data:
            print(f"\u274c {data['error']}")
            return
        if "answer" in data:
            print(data["answer"])
            if "chunks" in data:
                chunks = data["chunks"]
                if isinstance(chunks, list):
                    print(f"\n── 检索片段 ({len(chunks)} 条) ──")
                    for i, c in enumerate(chunks[:5]):
                        if isinstance(c, dict):
                            print(f"  [{i+1}] score={c.get('score',0):.3f} | {str(c.get('content',''))[:120]}...")
                        else:
                            print(f"  [{i+1}] {str(c)[:120]}...")
        elif "status" in data:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                print(f"  [{item.get('chunk_id','?')}] score={item.get('score',0):.3f} | {str(item.get('content',''))[:120]}")
            else:
                print(f"  {item}")
    else:
        print(data)


# ── 子命令 ──────────────────────────────────────────────────────────────

def cmd_search(args):
    """混合检索 → /api/v1/search"""
    payload = {"query": args.query, "top_k": args.top_k}
    if args.path:
        payload["path_constraint"] = args.path
    res = _curl("POST", f"{_api_url}/api/v1/search", payload)
    _output(res, args)


def cmd_rag(args):
    """RAG 问答 → /api/v1/rag"""
    payload = {"query": args.query, "top_k": args.top_k}
    res = _curl("POST", f"{_api_url}/api/v1/rag", payload)
    _output(res, args)


def cmd_agent(args):
    """Agent 对话 → /api/v1/agent"""
    payload = {"query": args.query, "max_iterations": args.max_iter}
    res = _curl("POST", f"{_api_url}/api/v1/agent", payload)
    _output(res, args)


def cmd_price(args):
    """查询材料价格 → /api/v1/agent (结构化查询)"""
    query = f"查询{args.material}的价格"
    if args.spec:
        query += f"，规格{args.spec}"
    if args.month:
        query += f"，{args.month}期"
    payload = {"query": query, "max_iterations": 2}
    res = _curl("POST", f"{_api_url}/api/v1/agent", payload)
    _output(res, args)


def cmd_trend(args):
    """价格走势 → /api/v1/agent"""
    query = f"查询{args.material}的价格走势"
    if args.start:
        query += f"，从{args.start}开始"
    if args.end:
        query += f"，到{args.end}结束"
    payload = {"query": query, "max_iterations": 3}
    res = _curl("POST", f"{_api_url}/api/v1/agent", payload)
    _output(res, args)


def cmd_calc(args):
    """造价计算 → /api/v1/sandbox/execute"""
    payload = {"code": args.expression, "timeout": 10}
    res = _curl("POST", f"{_api_url}/api/v1/sandbox/execute", payload)
    _output(res, args)


def cmd_eval(args):
    """Python 表达式求值 → /api/v1/agent (带 sandbox 工具)"""
    payload = {"query": f"用Python计算: {args.code}", "max_iterations": 2}
    res = _curl("POST", f"{_api_url}/api/v1/agent", payload)
    _output(res, args)


def cmd_stats(args):
    """系统统计 → /api/v1/system/kb"""
    res = _curl("GET", f"{_api_url}/api/v1/system/kb")
    _output(res, args)


def cmd_health(args):
    """健康检查 → /health + /api/v1/health/detail"""
    basic = _curl("GET", f"{_api_url}/health")
    detail = _curl("GET", f"{_api_url}/api/v1/health/detail")
    out = {"basic": basic, "detail": detail}
    _output(out, args)


def cmd_version(args):
    """版本信息 → /api/v1/system/version"""
    res = _curl("GET", f"{_api_url}/api/v1/system/version")
    _output(res, args)


def cmd_config(args):
    """运行时配置 → /api/v1/system/config"""
    res = _curl("GET", f"{_api_url}/api/v1/system/config")
    _output(res, args)


def cmd_rerank(args):
    """精排测试 → /api/v1/rerank"""
    payload = {
        "query": args.query,
        "documents": [{"content": args.query, "chunk_id": "test_0"}],
        "top_k": args.top_k,
    }
    if args.documents:
        docs = json.loads(args.documents)
        payload["documents"] = docs
    res = _curl("POST", f"{_api_url}/api/v1/rerank", payload)
    _output(res, args)


def cmd_decompose(args):
    """查询分解 → /api/v1/decompose"""
    payload = {"query": args.query}
    res = _curl("POST", f"{_api_url}/api/v1/decompose", payload)
    _output(res, args)


def cmd_learn_runs(args):
    """学习运行记录 → /api/v1/learning/runs"""
    res = _curl("GET", f"{_api_url}/api/v1/learning/runs")
    _output(res, args)


def cmd_learn_gaps(args):
    """知识缺口 → /api/v1/learning/gaps"""
    params = {}
    if args.status:
        params["status"] = args.status
    url = f"{_api_url}/api/v1/learning/gaps"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    res = _curl("GET", url)
    _output(res, args)


def cmd_learn_summary(args):
    """学习摘要 → /api/v1/learning/summary"""
    res = _curl("GET", f"{_api_url}/api/v1/learning/summary")
    _output(res, args)


def cmd_ops(args):
    """运维指标 → /api/v1/ops/metrics"""
    res = _curl("GET", f"{_api_url}/api/v1/ops/metrics")
    _output(res, args)


def cmd_metrics(args):
    """LLM 指标 → /api/v1/metrics/llm"""
    res = _curl("GET", f"{_api_url}/api/v1/metrics/llm")
    _output(res, args)


def cmd_feedback(args):
    """提交反馈 → /api/v1/feedback"""
    payload = {
        "query": args.query,
        "answer": args.answer or "",
        "rating": args.rating,
        "comment": args.comment or "",
    }
    res = _curl("POST", f"{_api_url}/api/v1/feedback", payload)
    _output(res, args)


def cmd_sandbox(args):
    """沙箱执行 → /api/v1/sandbox/execute"""
    payload = {"code": args.code, "timeout": args.timeout}
    res = _curl("POST", f"{_api_url}/api/v1/sandbox/execute", payload)
    _output(res, args)


def cmd_upload(args):
    """PDF → OCR → 导入"""
    path = Path(args.path)
    if not path.exists():
        print(f"\u274c File not found: {path}")
        return 1

    files = sorted(path.glob("*.pdf")) if path.is_dir() else [path]
    for pdf in files:
        print(f"\n\U0001f4c4 {pdf.name}")
        boundary = "----RAGBoundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{pdf.name}"\r\n'
            f"Content-Type: application/pdf\r\n\r\n"
        ).encode("utf-8") + pdf.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")

        req = urllib.request.Request(
            f"{_api_url}/api/v1/pipeline/upload",
            data=body,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=120)
            result = json.loads(resp.read().decode("utf-8"))
            print(f"  \u2705 {json.dumps(result, ensure_ascii=False)[:200]}")
        except Exception as e:
            print(f"  \u274c {e}")
    return 0


def cmd_tool(args):
    """直接调用 RAG26 tool → /api/v1/tools/<name>"""
    payload = {"kwargs": json.loads(args.kwargs) if args.kwargs else {}}
    res = _curl("POST", f"{_api_url}/api/v1/tools/{args.tool_name}", payload)
    _output(res, args)


def cmd_tool_list(args):
    """列出所有可用 tool → /api/v1/tools/list"""
    res = _curl("GET", f"{_api_url}/api/v1/tools/list")
    if not args.json:
        tools = res.get("tools", [])
        print(f"共 {len(tools)} 个工具:\n")
        for t in tools:
            required = ", ".join(t.get("required", []))
            req_str = f" [必填: {required}]" if required else ""
            print(f"  {t['name']:<25s} {t['description'][:60]}{req_str}")
    else:
        print(json.dumps(res, ensure_ascii=False, indent=2))


def cmd_chat(args):
    """交互式对话"""
    import readline  # noqa

    print("\U0001f9e0 RAG26 Chat (输入 exit 退出)")
    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if q.lower() in ("exit", "quit", "q"):
            break
        if not q:
            continue
        res = _curl("POST", f"{_api_url}/api/v1/agent", {"query": q, "max_iterations": 3})
        if isinstance(res, dict):
            answer = res.get("answer", "无回答")
            print(answer)
            chunks = res.get("chunks", [])
            if chunks:
                print(f"\n── 参考 ({len(chunks)} 条) ──")
                for c in chunks[:3]:
                    if isinstance(c, dict):
                        print(f"  [{c.get('score',0):.3f}] {str(c.get('content',''))[:100]}...")
        else:
            print(res)
        print()
    return 0


# ── 入口 ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="rag", description="RAG26 CLI — 造价知识检索与计算命令行工具"
    )
    parser.add_argument("--json", action="store_true", help="JSON 输出模式")
    parser.add_argument("--api-url", default=_api_url, help=f"检索服务地址 (默认: {_api_url})")

    sub = parser.add_subparsers(dest="cmd")

    # 检索
    p = sub.add_parser("search", help="混合检索 (向量+全文+结构化)")
    p.add_argument("query", help="查询文本")
    p.add_argument("-k", "--top-k", type=int, default=8, help="返回数量 (默认 8)")
    p.add_argument("-p", "--path", help="检索路径约束 (database/vector/graph)")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("rag", help="RAG 问答 (检索+生成)")
    p.add_argument("query", help="问题")
    p.add_argument("-k", "--top-k", type=int, default=5, help="检索片段数")
    p.set_defaults(func=cmd_rag)

    p = sub.add_parser("agent", help="Agent 对话 (ReAct 多步推理)")
    p.add_argument("query", help="问题")
    p.add_argument("-n", "--max-iter", type=int, default=3, help="最大迭代 (默认 3)")
    p.set_defaults(func=cmd_agent)

    p = sub.add_parser("chat", help="交互式对话")
    p.set_defaults(func=cmd_chat)

    # 造价
    p = sub.add_parser("price", help="查询材料价格")
    p.add_argument("material", help="材料名称 (如 混凝土C30)")
    p.add_argument("-s", "--spec", help="规格")
    p.add_argument("-m", "--month", help="期次 (如 202512)")
    p.set_defaults(func=cmd_price)

    p = sub.add_parser("trend", help="价格走势")
    p.add_argument("material", help="材料名称")
    p.add_argument("--start", help="起始月份 (如 202501)")
    p.add_argument("--end", help="结束月份 (如 202512)")
    p.set_defaults(func=cmd_trend)

    p = sub.add_parser("calc", help="造价公式计算")
    p.add_argument("expression", help="Python 表达式")
    p.set_defaults(func=cmd_calc)

    p = sub.add_parser("eval", help="Python 代码执行 (带沙箱)")
    p.add_argument("code", help="Python 代码")
    p.set_defaults(func=cmd_eval)

    # 分析
    p = sub.add_parser("rerank", help="精排测试")
    p.add_argument("query", help="查询")
    p.add_argument("-d", "--documents", help="候选文档 JSON 数组")
    p.add_argument("-k", "--top-k", type=int, default=5)
    p.set_defaults(func=cmd_rerank)

    p = sub.add_parser("decompose", help="查询分解")
    p.add_argument("query", help="复杂查询")
    p.set_defaults(func=cmd_decompose)

    # 学习
    p = sub.add_parser("learn-runs", help="学习运行记录")
    p.set_defaults(func=cmd_learn_runs)

    p = sub.add_parser("learn-gaps", help="知识缺口列表")
    p.add_argument("-s", "--status", help="过滤状态 (open/resolved)")
    p.set_defaults(func=cmd_learn_gaps)

    p = sub.add_parser("learn-summary", help="学习摘要")
    p.set_defaults(func=cmd_learn_summary)

    # 运维
    p = sub.add_parser("stats", help="系统统计")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("health", help="健康检查")
    p.set_defaults(func=cmd_health)

    p = sub.add_parser("version", help="版本信息")
    p.set_defaults(func=cmd_version)

    p = sub.add_parser("config", help="运行时配置")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("ops", help="运维指标")
    p.set_defaults(func=cmd_ops)

    p = sub.add_parser("metrics", help="LLM 调用指标")
    p.set_defaults(func=cmd_metrics)

    # 工具
    p = sub.add_parser("sandbox", help="Python 沙箱执行")
    p.add_argument("code", help="Python 代码")
    p.add_argument("-t", "--timeout", type=int, default=30, help="超时秒数")
    p.set_defaults(func=cmd_sandbox)

    p = sub.add_parser("feedback", help="提交用户反馈")
    p.add_argument("query", help="原始查询")
    p.add_argument("-a", "--answer", help="系统回答")
    p.add_argument("-r", "--rating", type=int, choices=[1, 2, 3, 4, 5], required=True, help="评分 1-5")
    p.add_argument("-c", "--comment", help="评语")
    p.set_defaults(func=cmd_feedback)

    p = sub.add_parser("upload", help="上传 PDF 文档")
    p.add_argument("path", help="PDF 文件或目录")
    p.set_defaults(func=cmd_upload)

    # Tool 直接调用
    p = sub.add_parser("tool", help="直接调用指定 RAG26 tool")
    p.add_argument("tool_name", help="工具名 (如 price_query, vector_search)")
    p.add_argument("-k", "--kwargs", default="{}", help="JSON 格式的参数 (如 '{\"material_name\":\"C30\",\"year_month\":\"202512\"}')")
    p.set_defaults(func=cmd_tool)

    p = sub.add_parser("tools", help="列出所有可用 RAG26 tool")
    p.set_defaults(func=cmd_tool_list)

    # 处理 --api-url 覆盖
    ns, remaining = parser.parse_known_args()
    if ns.api_url and ns.api_url != _api_url:
        import rag_cli as _self
        _self._api_url = ns.api_url.rstrip("/")

    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
