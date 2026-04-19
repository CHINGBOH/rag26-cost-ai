#!/usr/bin/env python3
"""
完整OCR + RAG测试流程
1. OCR处理PDF文档
2. 索引到四库系统
3. 执行RAG查询测试
"""

import requests
import json
import time
import sys
from pathlib import Path

# API endpoints
PYTHON_API = "http://localhost:8000"
NODE_API = "http://localhost:3001"
OCR_API = "http://localhost:8001"


class Colors:
    GREEN = "\033[92m"
    BLUE = "\033[94m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    END = "\033[0m"


def log(step, message):
    print(f"\n{Colors.BLUE}[{step}]{Colors.END} {message}")


def success(message):
    print(f"{Colors.GREEN}✅ {message}{Colors.END}")


def error(message):
    print(f"{Colors.RED}❌ {message}{Colors.END}")


def warn(message):
    print(f"{Colors.YELLOW}⚠️ {message}{Colors.END}")


def check_services():
    """检查所有服务是否运行"""
    log("1", "检查服务状态")

    services = {"Python后端": f"{PYTHON_API}/health", "OCR服务": f"{OCR_API}/health"}

    all_ready = True
    for name, url in services.items():
        try:
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                success(f"{name} 运行中")
            else:
                error(f"{name} 返回状态 {resp.status_code}")
                all_ready = False
        except Exception as e:
            error(f"{name} 未启动: {e}")
            all_ready = False

    return all_ready


def ocr_pdf(pdf_path):
    """OCR处理PDF文件"""
    log("2", f"OCR处理PDF: {pdf_path}")

    try:
        # 使用同步处理接口
        with open(pdf_path, "rb") as f:
            files = {"file": f}
            data = {"title": Path(pdf_path).stem}

            resp = requests.post(
                f"{PYTHON_API}/api/documents/process-sync", files=files, data=data, timeout=120
            )

        if resp.status_code == 200:
            result = resp.json()
            success(f"OCR完成: {result.get('chunks_count', 0)} 个文本块")
            return result
        else:
            error(f"OCR失败: {resp.text}")
            return None
    except Exception as e:
        error(f"OCR处理异常: {e}")
        return None


def search_documents(query, top_k=5):
    """搜索文档"""
    log("3", f"搜索: {query}")

    try:
        resp = requests.post(
            f"{PYTHON_API}/api/search",
            json={"query": query, "top_k": top_k, "mode": "hybrid"},
            timeout=10,
        )

        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                results = data["data"]["results"]
                success(f"找到 {len(results)} 条结果")

                print("\n搜索结果:")
                for i, r in enumerate(results[:3], 1):
                    content = r.get("content", "")[:100]
                    print(f"  {i}. [{r.get('score', 0):.3f}] {content}...")

                return results
            else:
                warn(f"搜索返回: {data.get('message')}")
                return []
        else:
            error(f"搜索请求失败: {resp.status_code}")
            return []
    except Exception as e:
        error(f"搜索异常: {e}")
        return []


def generate_answer(query, context_chunks):
    """生成回答（模拟LLM）"""
    log("4", "生成RAG回答")

    # 构建上下文
    context = "\n\n".join(
        [
            f"[文档{i + 1}] {chunk.get('content', '')[:200]}"
            for i, chunk in enumerate(context_chunks[:3])
        ]
    )

    # 模拟生成回答（实际应调用LLM）
    answer = f"""基于检索到的{len(context_chunks)}条相关资料，关于"{query}"的回答如下：

根据文档内容，主要信息包括：
{context[:500]}...

建议您查阅相关文档获取更详细的信息。"""

    success("回答生成完成")
    return answer


def test_rag_queries():
    """测试RAG查询"""
    log("5", "执行RAG查询测试")

    # 基于深圳市建设工程文档的测试问题
    test_cases = [
        {
            "question": "深圳市建设工程计价费率标准是什么？",
            "expected_topics": ["费率", "计价", "深圳"],
        },
        {
            "question": "房屋建筑工程的分部分项如何划分？",
            "expected_topics": ["分部分项", "房屋建筑", "划分"],
        },
        {"question": "市政工程包括哪些内容？", "expected_topics": ["市政", "工程", "内容"]},
        {
            "question": "装饰工程消耗量标准包含哪些项目？",
            "expected_topics": ["装饰", "消耗量", "标准"],
        },
    ]

    results = []
    for case in test_cases:
        print(f"\n{'=' * 60}")
        print(f"问题: {case['question']}")
        print("=" * 60)

        # 1. 检索相关文档
        chunks = search_documents(case["question"], top_k=5)

        if chunks:
            # 2. 生成回答
            answer = generate_answer(case["question"], chunks)
            print(f"\n回答:\n{answer}")
            results.append(
                {"question": case["question"], "status": "success", "chunks": len(chunks)}
            )
        else:
            warn("未找到相关文档")
            results.append({"question": case["question"], "status": "no_results", "chunks": 0})

        time.sleep(1)

    return results


def main():
    print("\n" + "=" * 60)
    print("完整OCR + RAG测试流程")
    print("=" * 60)

    # 1. 检查服务
    if not check_services():
        error("服务未完全启动，请先运行 ./start_all.sh")
        return 1

    # 2. 要处理的PDF文件
    pdf_files = [
        "/home/l/rag-dashboard/文档资料和别的ai写的后端代码参考/深圳市建设工程计价费率标准（2025）.pdf",
        "/home/l/rag-dashboard/文档资料和别的ai写的后端代码参考/深圳市建设工程地方标准/《房屋建筑工程造价文件分部分项和措施项目划分标准》.pdf",
    ]

    # 3. 处理PDF文件
    processed = []
    for pdf in pdf_files[:1]:  # 先处理第一个文件测试
        if Path(pdf).exists():
            result = ocr_pdf(pdf)
            if result:
                processed.append(result)
        else:
            warn(f"文件不存在: {pdf}")

    if not processed:
        error("没有成功处理任何PDF文件")
        # 继续测试已有索引的文档
        warn("尝试搜索已有索引的文档...")

    # 4. 执行RAG测试
    results = test_rag_queries()

    # 5. 汇总报告
    print("\n" + "=" * 60)
    print("测试报告")
    print("=" * 60)

    success_count = sum(1 for r in results if r["status"] == "success")
    print(f"成功查询: {success_count}/{len(results)}")

    for r in results:
        icon = "✅" if r["status"] == "success" else "❌"
        print(f"{icon} {r['question'][:40]}... ({r['chunks']} chunks)")

    print("\n" + "=" * 60)
    if success_count > 0:
        success("RAG测试流程完成！")
        return 0
    else:
        error("RAG测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
