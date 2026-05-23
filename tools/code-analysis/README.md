# RAG 代码分析工具仓库

这个目录把仓库级代码分析工具集中到一个可复用入口，覆盖架构依赖、函数调用流、语义规则扫描和项目本地质量工具。

## 工具矩阵

| 工具 | 作用 | 入口 |
| --- | --- | --- |
| Code2Flow | Python 业务逻辑调用流，输出 DOT 图 | `python3 run_analysis.py flows` |
| pydeps | Python 模块依赖清单，输出 JSON；SVG 需要额外安装 Graphviz | `python3 run_analysis.py deps` |
| Dependency-Cruiser | TS/JS 模块依赖 JSON，可进一步生成图 | `python3 run_analysis.py deps` |
| Madge | 前端和 Node 后端循环依赖检查 | `python3 run_analysis.py deps` |
| Semgrep | 语义规则扫描：配置入口、类型安全、金额精度 | `python3 run_analysis.py security` |
| Pyan3 | Python 静态调用图，追踪函数级关系 | `python3 run_analysis.py flows` |
| PyCG | 精确 Python 调用图；当前 runner 仅在 `python3.10` 可用时执行 | `python3 run_analysis.py flows` |

## 安装

从本目录执行：

```bash
npm install
npm run install:python
```

如果不想污染系统 Python，先创建虚拟环境：

```bash
python3 -m venv .venv
. .venv/bin/activate
npm run install:python
```

## 使用

```bash
# 查看将运行哪些命令
python3 run_analysis.py list

# 跑全部分析
npm run analyze

# 只跑依赖/架构分析
npm run analyze:deps

# 只跑函数调用流分析
npm run analyze:flows

# 只跑 Semgrep 语义规则
npm run analyze:security
```

输出统一写到 `tools/code-analysis/reports/`，包括：

- `dependency-cruiser.json`
- `frontend-madge-circular.txt`
- `server-madge-circular.txt`
- `retrieval-pydeps.json`
- `python-code2flow.dot`
- `retrieval-pyan3.dot`
- `retrieval-pycg.json`（可选，需 `python3.10` + PyCG）
- `semgrep.json`
- `manifest.json`

## 本地工具配合方式

这个工具箱不替代项目已有质量门禁。完整检查时建议按下面顺序：

```bash
python3 tools/code-analysis/run_analysis.py all --keep-going
npm run typecheck
npm run test:node
npm run test:python
```

其中 `run_analysis.py` 负责结构和调用关系，`typecheck` / 测试负责行为正确性。

## 约束

- `reports/` 是生成物，不应提交。
- 新增规则优先放到 `semgrep-rules/`，不要把可变扫描策略硬编码进业务代码。
- 新增工具必须接入 `run_analysis.py`，避免出现无人调用的孤立配置。
