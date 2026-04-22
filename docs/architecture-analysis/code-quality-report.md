# 代码质量扫描报告

> 生成时间: 2026-04-19
> 扫描工具: SonarScanner 4.3.6, Qlty 0.622.0, ruff, gofmt, tsc, madge

---

## 工具配置

### SonarScanner
- **版本**: 4.3.6
- **限制**: 需要 SonarQube 服务器，无法独立运行
- **建议**: 部署 SonarQube 容器后使用 `sonar-scanner -Dsonar.host.url=http://localhost:9000`

### Qlty
- **版本**: 0.622.0
- **安装**: `curl https://qlty.sh | sh`
- **初始化**: `qlty init` (生成 `.qlty/qlty.toml`)
- **扫描**: `qlty check`
- **限制**: 大型项目首次扫描可能较慢；非交互模式需配置 `qlty.toml`

### 项目中已有工具
| 工具 | 范围 | 状态 |
|------|------|------|
| ruff | Python | ✅ 已安装，快速 |
| mypy | Python | ⚠️ 严格模式，有历史遗留问题 |
| gofmt | Go | ✅ Go 内置 |
| golangci-lint | Go | ⚠️ 需 Go 1.26+，当前环境不兼容 |
| tsc | TypeScript | ✅ 已配置 |

---

## 修复记录

| # | 问题 | 文件 | 修复方式 | 检测工具 |
|---|------|------|----------|----------|
| 1 | `embedding_model` 赋值未使用 (F841) | `api/routes.py` | 移除未使用变量 | ruff |
| 2 | `proxy.go` 格式不符合 gofmt | `proxy.go` | `gofmt -w` 自动格式化 | gofmt |

---

## 已知设计限制（无需修复）

| 问题 | 文件 | 原因 |
|------|------|------|
| E402 模块导入不在顶部 | `api/unified_api.py` 等 | `sys.path.insert(0, project_root)` hack 必须在导入前执行 |
| mypy 重复模块名 | `types/retrieval.py` | 与 `retrieval/__init__.py` 同名，遗留结构问题 |
| golangci-lint 崩溃 | 所有 `.go` | 工具需要 Go 1.26+，系统为 Go 1.21 |

---

## 最终检测汇总

| 检测项 | 工具 | 结果 |
|--------|------|------|
| Python 代码风格 | ruff | ✅ All checks passed |
| Go 代码格式 | gofmt | ✅ 全部文件格式正确 |
| Go 编译 | go build | ✅ 编译通过 |
| TypeScript 类型 | tsc --noEmit | ✅ 类型检查通过 |
| 前端循环依赖 | madge | ✅ 无循环依赖 |
| 后端循环依赖 | madge | ✅ 无循环依赖 |
| API 代理一致性 | 手动验证 | ✅ 所有路径已覆盖 |
| Gateway 路由完整性 | 手动验证 | ✅ 所有前端 API 均有映射 |

---

## 工具已写入 AGENTS.md

位置: `/home/l/rag-dashboard/AGENTS.md` — `## Code quality scanning tools` 章节

包含:
- Qlty 安装和配置说明
- SonarScanner 使用限制说明
- ruff / mypy / golangci-lint / tsc 等已有工具的命令
- 已知设计限制说明（E402、重复模块等）
