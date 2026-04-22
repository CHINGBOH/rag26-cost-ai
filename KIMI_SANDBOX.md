 KIMI_SANDBOX.md
> Copilot（智囊）→ Kimi Code（执行者）Docker Python 沙箱工具指引  
> **规则**：按 Phase 顺序执行。每个 Phase 完成后填报告，等 Copilot 审查再继续。

---

## ⚠️ Kimi 行为准则（每次执行前必读）

### 🧠 举一反三原则

1. **同类问题一起修**（<10 行改动直接改，记录到报告）
2. **卡住不要死磕**——换角度诊断，记录失败原因
3. **安全第一**——沙箱的每一层防线都不能省，宁可限制功能也不能开后门
4. **不要大规模重构现有代码**——只新增文件 + 微调 2 个现有文件

### 本次改动范围

```
新增文件（3个）：
  src/backend/retrieval-service/infrastructure/sandbox.py    ← Docker 沙箱核心
  src/backend/retrieval-service/infrastructure/Dockerfile.sandbox  ← 沙箱容器镜像
  src/backend/retrieval-service/infrastructure/sandbox_entry.py    ← 容器内执行入口

修改文件（2个，每个改动 <15 行）：
  src/backend/retrieval-service/app/agent/tools.py     ← 新增 python_eval 工具
  src/backend/retrieval-service/app/agent/graph.py     ← REACT_TOOLS 加入 python_eval
```

---

## 📐 架构设计

```
  LLM（Qwen3:8b）
    ↓ tool_call: python_eval(code="...")
  tool_node
    ↓ 调用 python_eval()
  sandbox.py
    ↓ docker run --rm --network=none --memory=256m --cpus=1 --timeout=10s
  ┌─────────────────────────────────────────┐
  │  Docker 容器（rag-sandbox:latest）       │
  │  python3 sandbox_entry.py               │
  │  ├─ AST 静态检查（禁 import/exec/eval） │
  │  ├─ 受限 builtins（只有数学函数）       │
  │  └─ 执行代码，输出 JSON 结果            │
  │  无网络 / 无磁盘写入 / 256MB 内存上限   │
  └─────────────────────────────────────────┘
    ↓ stdout JSON: {"status":"success","result":"175000.0","output":"..."}
  tool_node → 回填到 agent state
```

**安全防线（5 层）**：

| # | 防线 | 位置 | 作用 |
|---|------|------|------|
| 1 | AST 静态扫描 | 容器内 `sandbox_entry.py` | 编译前拦截 `import`、`exec`、`eval`、`open`、`os`、`sys`、`__` |
| 2 | 受限 `__builtins__` | 容器内 | 只暴露 `print`、`len`、`range`、`round`、`abs`、`max`、`min`、`sum`、`float`、`int`、`str`、`Decimal` |
| 3 | `--network=none` | Docker 参数 | 容器无法访问任何网络（包括宿主机） |
| 4 | `--memory=256m` | Docker 参数 | 内存上限 256MB，防止内存炸弹 |
| 5 | `--read-only` + 超时 | Docker 参数 | 文件系统只读 + 10 秒强制 kill |

---

## ⏩ Phase 1：构建沙箱镜像

### 1.1 创建 Dockerfile

文件：`src/backend/retrieval-service/infrastructure/Dockerfile.sandbox`

```dockerfile
FROM python:3.10-slim

# 不安装任何额外包——造价计算只需要标准库
# 如果未来需要 numpy/pandas，在这里 pip install

# 复制执行入口
COPY sandbox_entry.py /sandbox/sandbox_entry.py

WORKDIR /sandbox

# 非 root 用户运行（额外安全层）
RUN useradd -r -s /bin/false sandbox && \
    chown -R sandbox:sandbox /sandbox
USER sandbox

ENTRYPOINT ["python3", "/sandbox/sandbox_entry.py"]
```

### 1.2 创建容器内执行入口

文件：`src/backend/retrieval-service/infrastructure/sandbox_entry.py`

```python
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
```

### 1.3 构建镜像

```bash
cd /home/l/rag-dashboard/src/backend/retrieval-service/infrastructure

# 构建（约 30 秒，python:3.10-slim ~150MB）
docker build -t rag-sandbox:latest -f Dockerfile.sandbox .

# 验证镜像
docker images rag-sandbox
# 期望：rag-sandbox  latest  约 150-200MB
```

### 1.4 测试沙箱（不涉及 Agent，纯验证沙箱安全性）

```bash
# ✅ 测试 1：正常计算
echo '{"code": "result = 500 * 10000 * 0.035\nprint(f\"企业管理费: {result}元\")"}' | \
  docker run --rm -i --network=none --memory=256m --cpus=1 rag-sandbox:latest

# 期望输出：{"status": "success", "result": "175000.0", "output": "企业管理费: 175000.0元\n"}

# ✅ 测试 2：Decimal 精确计算
echo '{"code": "from decimal import Decimal\nresult = Decimal(\"500\") * Decimal(\"0.035\")\nprint(result)"}' | \
  docker run --rm -i --network=none --memory=256m --cpus=1 rag-sandbox:latest

# ⚠️ 注意：这个会被 AST 拦截（有 from decimal import），因为 Decimal 已经在 builtins 里了
# 期望输出：{"status": "error", "error": "安全限制: 不允许使用 import 语句", ...}

# ✅ 测试 3：用内置 Decimal
echo '{"code": "result = Decimal(\"500\") * Decimal(\"0.035\")"}' | \
  docker run --rm -i --network=none --memory=256m --cpus=1 rag-sandbox:latest

# 期望输出：{"status": "success", "result": "17.500", ...}

# 🔒 测试 4：安全拦截 - import os
echo '{"code": "import os\nos.system(\"ls\")"}' | \
  docker run --rm -i --network=none --memory=256m --cpus=1 rag-sandbox:latest

# 期望输出：{"status": "error", "error": "安全限制: 不允许使用 import 语句", ...}

# 🔒 测试 5：安全拦截 - 读文件
echo '{"code": "f = open(\"/etc/passwd\")\nprint(f.read())"}' | \
  docker run --rm -i --network=none --memory=256m --cpus=1 rag-sandbox:latest

# 期望输出：{"status": "error", "error": "安全限制: 不允许调用 open()", ...}

# 🔒 测试 6：安全拦截 - __builtins__ 逃逸
echo '{"code": "x = __builtins__"}' | \
  docker run --rm -i --network=none --memory=256m --cpus=1 rag-sandbox:latest

# 期望输出：{"status": "error", "error": "安全限制: 不允许使用 __builtins__", ...}

# ⏱️ 测试 7：超时（while True 死循环）
timeout 15 bash -c 'echo "{\"code\": \"while True: pass\"}" | \
  docker run --rm -i --network=none --memory=256m --cpus=1 --stop-timeout=10 rag-sandbox:latest'
echo "exit code: $?"

# 期望：10秒后被 kill，exit code 非 0

# 🔒 测试 8：网络隔离验证
echo '{"code": "import socket"}' | \
  docker run --rm -i --network=none --memory=256m --cpus=1 rag-sandbox:latest

# 期望：被 AST 拦截（import）

# ✅ 测试 9：多步造价计算（真实场景）
cat << 'EOF' | docker run --rm -i --network=none --memory=256m --cpus=1 rag-sandbox:latest
{"code": "# 某工程造价计算\n人工费 = Decimal('5000000')\n材料费 = Decimal('12000000')\n\n# 企业管理费 = 人工费 × 费率\n企业管理费率 = Decimal('0.035')\n企业管理费 = 人工费 * 企业管理费率\n\n# 利润 = 人工费 × 利润率\n利润率 = Decimal('0.04')\n利润 = 人工费 * 利润率\n\n# 汇总\n合计 = 企业管理费 + 利润\nresult = f'企业管理费={企业管理费}元, 利润={利润}元, 合计={合计}元'"}
EOF

# 期望：success，输出造价计算结果
```

---

### 📋 Phase 1 报告

#### 1.1 Dockerfile 创建

- [ ] `Dockerfile.sandbox` 已创建
- [ ] `sandbox_entry.py` 已创建

#### 1.2 镜像构建

```
（粘贴 docker build 输出最后 5 行）
```

- 镜像大小：

#### 1.3 安全测试结果

| 测试 | 预期 | 实际 | ✅/❌ |
|------|------|------|-------|
| 正常计算 | success, 175000.0 | | |
| Decimal 精确 | success | | |
| import os 拦截 | error, 安全限制 | | |
| open() 拦截 | error, 安全限制 | | |
| __builtins__ 拦截 | error, 安全限制 | | |
| 死循环超时 | 被 kill | | |
| 多步造价 | success | | |

#### 额外发现

```
（测试过程中发现的问题和修复）
```

---

## Phase 2：创建 sandbox.py 调用模块

> ⚠️ **等 Phase 1 审查通过后再执行**

### 目标

创建 Python 模块，封装 Docker 沙箱调用逻辑，供 Agent tool 使用。

### 2.1 创建 sandbox.py

文件：`src/backend/retrieval-service/infrastructure/sandbox.py`

```python
"""
Docker Python 沙箱 — 安全执行 Agent 生成的 Python 代码

安全防线：
  1. AST 静态检查（容器内 sandbox_entry.py）
  2. 受限 builtins（容器内）
  3. --network=none（无网络）
  4. --memory=256m（内存上限）
  5. --read-only + 超时 10s（只读文件系统 + 强杀）
"""

import json
import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

SANDBOX_IMAGE = "rag-sandbox:latest"
SANDBOX_TIMEOUT = 15  # 秒（Docker stop-timeout=10，留 5s buffer）
SANDBOX_MEMORY = "256m"
SANDBOX_CPUS = "1"


def _check_image_exists() -> bool:
    """检查沙箱镜像是否存在"""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", SANDBOX_IMAGE],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def execute_python(code: str) -> dict:
    """
    在 Docker 沙箱中执行 Python 代码

    Args:
        code: Python 代码字符串

    Returns:
        dict: {"status": "success"|"error", "result": str, "output": str, ...}
    """
    if not code or not code.strip():
        return {"status": "error", "error": "代码为空", "output": ""}

    # 检查镜像
    if not _check_image_exists():
        logger.error(f"沙箱镜像 {SANDBOX_IMAGE} 不存在，请先构建")
        return {
            "status": "error",
            "error": f"沙箱镜像 {SANDBOX_IMAGE} 不存在。请运行: "
                     f"cd src/backend/retrieval-service/infrastructure && "
                     f"docker build -t rag-sandbox:latest -f Dockerfile.sandbox .",
            "output": "",
        }

    # 构建 Docker 命令
    docker_cmd = [
        "docker", "run",
        "--rm",                       # 执行完自动删除容器
        "-i",                         # 从 stdin 读取输入
        "--network=none",             # 🔒 无网络
        f"--memory={SANDBOX_MEMORY}", # 🔒 内存限制
        f"--cpus={SANDBOX_CPUS}",     # 🔒 CPU 限制
        "--read-only",                # 🔒 只读文件系统
        "--tmpfs=/tmp:size=10m",      # 给 /tmp 一点临时空间（Python 需要）
        "--stop-timeout=10",          # 10 秒后强杀
        "--pids-limit=50",            # 🔒 限制进程数（防 fork bomb）
        "--security-opt=no-new-privileges",  # 🔒 禁止提权
        SANDBOX_IMAGE,
    ]

    input_json = json.dumps({"code": code}, ensure_ascii=False)

    try:
        logger.info(f"[sandbox] executing code ({len(code)} chars)")
        result = subprocess.run(
            docker_cmd,
            input=input_json,
            capture_output=True,
            text=True,
            timeout=SANDBOX_TIMEOUT,
        )

        if result.returncode != 0 and not result.stdout.strip():
            stderr = result.stderr.strip()[-300:]
            logger.warning(f"[sandbox] container exited with code {result.returncode}: {stderr}")
            return {
                "status": "error",
                "error": f"容器执行失败 (exit={result.returncode}): {stderr}",
                "output": "",
            }

        # 解析容器输出
        try:
            output = json.loads(result.stdout)
            log_result = output.get("result", "")[:80]
            logger.info(f"[sandbox] {output['status']}: {log_result}")
            return output
        except json.JSONDecodeError:
            # 容器输出不是 JSON（可能被 OOM kill 等异常中断）
            stdout_tail = result.stdout.strip()[-200:]
            return {
                "status": "error",
                "error": f"容器输出无法解析: {stdout_tail}",
                "output": result.stdout[:500],
            }

    except subprocess.TimeoutExpired:
        logger.warning("[sandbox] execution timed out")
        return {
            "status": "error",
            "error": f"执行超时（{SANDBOX_TIMEOUT}秒），可能有死循环",
            "output": "",
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "error": "docker 命令不可用，请确认 Docker 已安装",
            "output": "",
        }
    except Exception as e:
        logger.error(f"[sandbox] unexpected error: {e}")
        return {
            "status": "error",
            "error": f"沙箱异常: {type(e).__name__}: {e}",
            "output": "",
        }
```

### 2.2 验证 sandbox.py

```bash
cd /home/l/rag-dashboard/src/backend/retrieval-service
source /home/l/rag-dashboard/venv/bin/activate

python3 -c "
import sys
sys.path.insert(0, '.')
from infrastructure.sandbox import execute_python

# 测试 1: 正常计算
r = execute_python('result = 500 * 10000 * 0.035')
print('Test1:', r)

# 测试 2: import 拦截
r = execute_python('import os')
print('Test2:', r)

# 测试 3: 空代码
r = execute_python('')
print('Test3:', r)

# 测试 4: Decimal 造价计算
code = '''
人工费 = Decimal('5000000')
费率 = Decimal('0.035')
result = 人工费 * 费率
print(f'企业管理费: {result}元')
'''
r = execute_python(code)
print('Test4:', r)
"
```

---

### 📋 Phase 2 报告

#### sandbox.py 创建

- [ ] `sandbox.py` 已创建

#### 验证结果

```
（粘贴 4 个测试的输出）
```

| 测试 | 预期 | 实际 | ✅/❌ |
|------|------|------|-------|
| 正常计算 | success | | |
| import 拦截 | error | | |
| 空代码 | error | | |
| Decimal 造价 | success | | |

#### 额外发现

```
```

---

## Phase 3：新增 python_eval 工具 + 接入 Agent

> ⚠️ **等 Phase 2 审查通过后再执行**

### 目标

1. 在 `tools.py` 新增 `python_eval` 工具
2. 在 `graph.py` 把它加入 `REACT_TOOLS`
3. 全量回测确认不退化

### 3.1 修改 tools.py — 新增 python_eval 工具

文件：`src/backend/retrieval-service/app/agent/tools.py`

**在文件末尾（`calculator` 函数之后）追加**：

```python
@tool
def python_eval(code: str) -> str:
    """Python 代码执行器：在安全沙箱中运行 Python 代码，适合复杂造价计算。

    支持功能：
    - 四则运算、百分比计算、条件判断、循环汇总
    - Decimal 精确计算（已内置，不需要 import）
    - 中文变量名（如 人工费 = 5000000）
    - 多步计算和中间变量

    使用规则：
    - 用 result = ... 返回最终结果，或用 print() 输出
    - 不能 import 任何模块（Decimal 等常用功能已内置）
    - 不能访问文件、网络

    示例：
    - 简单费率: result = 5000000 * 0.035
    - 精确计算: result = Decimal('5000000') * Decimal('0.035')
    - 条件取费:
        if amount > 5000000:
            rate = Decimal('0.035')
        else:
            rate = Decimal('0.04')
        result = amount * rate
    - 多项汇总:
        items = {'企业管理费': 175000, '利润': 200000, '规费': 85000}
        result = f"合计: {sum(items.values())}元"
    """
    try:
        from infrastructure.sandbox import execute_python

        output = execute_python(code)

        if output["status"] == "success":
            result_text = output.get("result", "")
            printed = output.get("output", "").strip()
            if printed:
                return f"计算结果: {result_text}\n输出:\n{printed}"
            return f"计算结果: {result_text}"
        else:
            error = output.get("error", "未知错误")
            return f"[代码执行失败: {error}]"

    except Exception as e:
        logger.error(f"[python_eval] error: {e}")
        return f"[沙箱调用失败: {e}]"
```

### 3.2 修改 graph.py — 加入 REACT_TOOLS

文件：`src/backend/retrieval-service/app/agent/graph.py`

**找到 import 区**（约第 18-22 行）：
```python
from app.agent.tools import (
    vector_search,
    keyword_search,
    graph_search,
    hybrid_search,
    calculator,
)
```

**改为**：
```python
from app.agent.tools import (
    vector_search,
    keyword_search,
    graph_search,
    hybrid_search,
    calculator,
    python_eval,
)
```

**找到 REACT_TOOLS**（约第 33 行）：
```python
REACT_TOOLS = [vector_search, keyword_search, graph_search, calculator]
```

**改为**：
```python
REACT_TOOLS = [vector_search, keyword_search, graph_search, calculator, python_eval]
```

### 3.3 验证 — 单独测试 python_eval

```bash
# 重启 retrieval-service
pkill -f "uvicorn.*8002" || true
sleep 3
cd /home/l/rag-dashboard/src/backend/retrieval-service
source /home/l/rag-dashboard/venv/bin/activate
nohup python -m uvicorn main:app --host 0.0.0.0 --port 8002 > /tmp/retrieval.log 2>&1 &
sleep 15

curl -s http://localhost:8002/health | python3 -m json.tool

# 直接测试 python_eval 工具
cd /home/l/rag-dashboard/src/backend/retrieval-service
python3 -c "
import sys
sys.path.insert(0, '.')
from app.agent.tools import python_eval

# 造价计算
r = python_eval.invoke({'code': '''
人工费 = Decimal(\"5000000\")
材料费 = Decimal(\"12000000\")
企业管理费率 = Decimal(\"0.035\")
result = 人工费 * 企业管理费率
print(f\"企业管理费 = {result} 元\")
'''})
print(r)
"
```

### 3.4 全量 16 题回测

```bash
questions=(
  "安装工程消耗量定额中，电气设备安装的人工费单价标准是多少？"
  "25版装饰工程消耗量定额与23版相比，新增了哪些工程项目？"
  "对比深圳市2025版建筑工程消耗量定额与2023版在混凝土工程中的主要变化"
  "根据深圳信息价2026年1月数据，普通硅酸盐水泥P.O 42.5的含税价格是多少？"
  "2025年深圳信息价中，商品混凝土C30的市场指导价范围是多少？"
  "详细说明深圳市建设工程计价费率2025版中安全文明施工费的计算方法"
  "工程项目中施工图预算审核的主要流程和关键节点有哪些？"
  "2025版费率标准中，一般计税与简易计税的适用条件分别是什么？"
  "一般计税方法下，建筑安装工程费的增值税税率和计算基数是什么？"
  "总包管理服务费的计算基数和费率范围是什么？"
  "模块化建筑工程施工工期定额与传统建筑相比有何差异？"
  "2023版与2025版定额在脚手架工程量计算规则上有何区别？"
  "某工程人工费为500万，材料费为1200万，按2025版费率计算企业管理费是多少？"
  "按2025版标准，规费中社会保险费包含哪几项？各自的计算基础是什么？"
  "2026年1月中砂（河砂，中）的信息指导价是多少？与去年同期相比变化趋势如何？"
  "2026年1月电线电缆（BV 2.5mm²铜芯）的信息指导价是多少？"
)

echo "===== 全量回测（沙箱接入后）====="
passed=0
failed_list=""
for i in "${!questions[@]}"; do
  n=$((i + 1))
  q="${questions[$i]}"
  printf "Q%02d: %s... " "$n" "${q:0:25}"
  result=$(curl -s --max-time 60 -X POST http://localhost:8002/api/v1/agent \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"$q\", \"max_iterations\": 3}")

  p=$(echo "$result" | python3 -c "
import sys,json
r=json.load(sys.stdin)
ev=r.get('evaluation',{})
print(f'{ev.get(\"passed\",False)} conf={ev.get(\"confidence\",0):.3f} chunks={len(r.get(\"chunks\",[]))}')
" 2>/dev/null)
  echo "$p"

  if echo "$p" | grep -q "^True"; then
    passed=$((passed + 1))
  else
    failed_list="$failed_list Q$(printf '%02d' $n)"
  fi
done

echo "===== 结果: ${passed}/16 ====="
echo "失败题目:${failed_list:-无}"
```

### 3.5 专门测试 Q13（计算题）

Q13 是 "某工程人工费为500万，材料费为1200万，按2025版费率计算企业管理费是多少？"

**验证 Agent 是否使用了 python_eval**：

```bash
# 看 retrieval-service 日志中 Q13 的执行记录
curl -s --max-time 60 -X POST http://localhost:8002/api/v1/agent \
  -H "Content-Type: application/json" \
  -d '{"query": "某工程人工费为500万，材料费为1200万，按2025版费率计算企业管理费是多少？", "max_iterations": 3}' \
  | python3 -m json.tool

# 同时查日志，看是否调用了 python_eval 或 calculator
grep -i "python_eval\|calculator\|sandbox" /tmp/retrieval.log | tail -20
```

---

### 📋 Phase 3 报告

#### 3.1 tools.py 修改

- [ ] `python_eval` 工具已添加

#### 3.2 graph.py 修改

- [ ] import 已添加 `python_eval`
- [ ] `REACT_TOOLS` 已包含 `python_eval`

#### 3.3 python_eval 单独测试

```
（粘贴造价计算测试结果）
```

#### 3.4 全量回测

| # | passed | confidence | chunks |
|---|--------|------------|--------|
| 01 | | | |
| 02 | | | |
| 03 | | | |
| 04 | | | |
| 05 | | | |
| 06 | | | |
| 07 | | | |
| 08 | | | |
| 09 | | | |
| 10 | | | |
| 11 | | | |
| 12 | | | |
| 13 | | | |
| 14 | | | |
| 15 | | | |
| 16 | | | |

**汇总：** /16 passed

#### 3.5 Q13 计算题分析

- Agent 是否调用了 python_eval：
- Agent 是否调用了 calculator：
- 计算结果是否正确：

```
（粘贴 Q13 的完整 agent 响应 + 日志中的工具调用记录）
```

#### 与基线对比

| 指标 | 上一轮基线 | 沙箱接入后 | 变化 |
|------|-----------|-----------|------|
| Passed | 16/16 | /16 | |
| Q13 使用工具 | calculator / 心算 | | |

#### 结果判定

- [ ] ≥16/16 → ✅ 沙箱接入成功
- [ ] 15/16 且仅 Q13 变化 → ⚠️ 检查 python_eval 是否干扰了 LLM 决策
- [ ] <15/16 退化 → ❌ 回退 graph.py 和 tools.py（移除 python_eval），保留沙箱基建

---

## 执行总览

```
Phase 1 (构建沙箱镜像)
├─ 1.1 创建 Dockerfile + sandbox_entry.py
├─ 1.2 docker build
└─ 1.3 安全测试（7 项）
          ↓
Phase 2 (sandbox.py 调用模块)
├─ 2.1 创建 sandbox.py
└─ 2.2 Python 测试
          ↓
Phase 3 (接入 Agent)
├─ 3.1 tools.py 新增 python_eval
├─ 3.2 graph.py 加入 REACT_TOOLS
├─ 3.3 单独测试
├─ 3.4 全量回测 16 题
└─ 3.5 Q13 计算题分析
```

**新增文件 3 个，修改文件 2 个（每个 <15 行改动）。每个 Phase 完成后等 Copilot 审查再继续。**
