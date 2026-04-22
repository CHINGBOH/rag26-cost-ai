#!/usr/bin/env python3
"""
Docker 沙箱内的 Python 代码执行入口
从 stdin 读取 JSON {"code": "..."} → 执行 → stdout 输出 JSON 结果

安全机制：
1. AST 静态检查：禁止 import/exec/eval/open/__dunder__
2. 受限 builtins：只暴露数学相关函数
3. 执行超时由外部 Docker --stop-timeout 控制
"""

import ast
import io
import json
import sys
import traceback
from decimal import Decimal, ROUND_HALF_UP


# ── 安全检查 ────────────────────────────────────────────────────────────────

FORBIDDEN_NODES = (
    ast.Import, ast.ImportFrom,   # 禁止 import
)

FORBIDDEN_NAMES = {
    "exec", "eval", "compile", "execfile",
    "open", "file", "input",
    "os", "sys", "subprocess", "shutil",
    "globals", "locals", "vars", "dir",
    "getattr", "setattr", "delattr",
    "breakpoint", "exit", "quit",
    "__import__", "__builtins__", "__loader__",
    "__spec__", "__name__", "__file__",
}


def check_ast_safety(code: str) -> str | None:
    """AST 静态检查，返回 None 表示安全，返回错误信息表示拒绝"""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"语法错误: {e}"

    for node in ast.walk(tree):
        # 禁止 import 语句
        if isinstance(node, FORBIDDEN_NODES):
            return f"安全限制: 不允许使用 import 语句"

        # 禁止调用危险函数
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_NAMES:
                return f"安全限制: 不允许调用 {func.id}()"
            if isinstance(func, ast.Attribute) and func.attr.startswith("__"):
                return f"安全限制: 不允许访问双下划线属性 __{func.attr}__"

        # 禁止访问双下划线属性
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return f"安全限制: 不允许访问 __{node.attr}__"

        # 禁止危险变量名
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            return f"安全限制: 不允许使用 {node.id}"

    return None


# ── 受限执行环境 ────────────────────────────────────────────────────────────

SAFE_BUILTINS = {
    # 类型
    "int": int, "float": float, "str": str, "bool": bool,
    "list": list, "dict": dict, "tuple": tuple, "set": set,
    # 数学
    "abs": abs, "round": round, "max": max, "min": min, "sum": sum,
    "pow": pow, "divmod": divmod,
    # 迭代
    "len": len, "range": range, "enumerate": enumerate, "zip": zip,
    "sorted": sorted, "reversed": reversed, "map": map, "filter": filter,
    # 输出
    "print": print,
    # 精确计算
    "Decimal": Decimal, "ROUND_HALF_UP": ROUND_HALF_UP,
    # 布尔
    "True": True, "False": False, "None": None,
    # 类型检查
    "isinstance": isinstance, "type": type,
}


def execute_code(code: str) -> dict:
    """在受限环境中执行代码"""

    # 1. AST 安全检查
    error = check_ast_safety(code)
    if error:
        return {"status": "error", "error": error, "output": ""}

    # 2. 捕获 print 输出
    old_stdout = sys.stdout
    sys.stdout = captured = io.StringIO()

    # 3. 执行
    local_vars = {}
    try:
        compiled = compile(code, "<sandbox>", "exec")
        exec(compiled, {"__builtins__": SAFE_BUILTINS}, local_vars)

        output = captured.getvalue()

        # 获取 result 变量（如果有）
        result = local_vars.get("result", None)
        if result is not None:
            result_str = str(result)
        elif output.strip():
            result_str = output.strip().split("\n")[-1]  # 取最后一行 print
        else:
            result_str = "代码执行完毕，无输出。请用 result = ... 或 print() 返回结果。"

        return {
            "status": "success",
            "result": result_str,
            "output": output[:2000],  # 截断防止输出爆炸
        }

    except Exception as e:
        output = captured.getvalue()
        return {
            "status": "error",
            "error": f"{type(e).__name__}: {e}",
            "output": output[:1000],
            "traceback": traceback.format_exc()[-500:],
        }
    finally:
        sys.stdout = old_stdout


# ── 主入口 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        input_data = json.loads(sys.stdin.read())
        code = input_data.get("code", "")

        if not code.strip():
            result = {"status": "error", "error": "代码为空", "output": ""}
        else:
            result = execute_code(code)

        print(json.dumps(result, ensure_ascii=False))

    except json.JSONDecodeError:
        print(json.dumps({"status": "error", "error": "输入不是合法JSON", "output": ""}))
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e), "output": ""}))
