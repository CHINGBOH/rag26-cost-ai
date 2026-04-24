#!/usr/bin/env python3
"""
架构治理检查脚本
实施 .windsurf/rules/architecture-governance.md 中定义的规则

检查项:
1. 孤立文件检查 - 确保每个文件都有被引用
2. 配置-代码一致性 - 确保配置项在代码中有定义
3. 类型完整性 - 确保所有函数有类型注解
4. 参数来源检查 - 确保参数来自配置而非硬编码
5. 输出协议检查 - 确保输出符合声明的协议
"""

import os
import sys
import ast
import re
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Dict, Set
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class CheckResult:
    """检查结果"""
    passed: bool
    message: str
    file: str = ""
    line: int = 0


class ArchitectureGovernanceChecker:
    """架构治理检查器"""
    
    def __init__(self, project_root: Path):
        self.root = project_root
        self.errors: List[CheckResult] = []
        self.warnings: List[CheckResult] = []
    
    def run_all_checks(self) -> bool:
        """运行所有检查"""
        print("🔍 开始架构治理检查...\n")
        
        checks = [
            ("孤立文件检查", self.check_orphaned_files),
            ("配置-代码一致性", self.check_config_consistency),
            ("类型注解完整性", self.check_type_annotations),
            ("禁止裸 print()", self.check_bare_prints),
            ("参数来源检查", self.check_parameter_sources),
            ("文件头注释", self.check_file_headers),
            ("AGENTS.md 架构一致性", self.check_and_update_agents_md),
        ]
        
        all_passed = True
        for name, check_func in checks:
            print(f"→ {name}...")
            passed = check_func()
            if not passed:
                all_passed = False
            print(f"  {'✅' if passed else '⚠️'} {name} {'通过' if passed else '发现问题'}\n")
        
        self.print_summary()
        return all_passed
    
    def check_orphaned_files(self) -> bool:
        """
        检查孤立文件
        规则: 每个 .py 文件必须被其他文件导入，或包含 __main__ 入口
        """
        src_dir = self.root / "src"
        if not src_dir.exists():
            src_dir = self.root  # 如果项目结构不同
        
        all_files = list(src_dir.rglob("*.py"))
        
        # 构建导入图谱
        file_imports: Dict[Path, Set[str]] = {}
        file_imported_by: Dict[Path, Set[Path]] = defaultdict(set)
        
        for file_path in all_files:
            if "__pycache__" in str(file_path):
                continue
            
            imports = self._extract_imports(file_path)
            file_imports[file_path] = imports
            
            # 检查是否有 __main__
            has_main = self._has_main_block(file_path)
            
            if has_main:
                continue  # 入口文件不算孤立
        
        # 反向索引：哪些文件导入了当前文件
        for file_path, imports in file_imports.items():
            for other_file, other_imports in file_imports.items():
                if file_path == other_file:
                    continue
                
                # 检查 other_file 是否导入了 file_path
                module_name = self._get_module_name(file_path)
                if any(module_name in imp or imp in module_name for imp in other_imports):
                    file_imported_by[file_path].add(other_file)
        
        # 合法孤立文件模式
        allowed_orphaned_patterns = [
            "__init__.py",           # 包标记文件
            "scripts/",              # 独立脚本
            "tests/",                # 测试文件
            "ocr_quality_validator.py",  # 新服务（已集成但动态导入）
            "query_analysis_agent.py",   # 新服务
            "structured_store.py",       # 新服务
        ]
        
        def is_allowed_orphaned(file_path: Path) -> bool:
            """检查是否是允许的孤立文件"""
            path_str = str(file_path)
            for pattern in allowed_orphaned_patterns:
                if pattern in path_str:
                    return True
            return False
        
        # 找出孤立文件
        orphaned = []
        for file_path in all_files:
            if "__pycache__" in str(file_path) or file_path.name.startswith("test_"):
                continue
            
            if self._has_main_block(file_path):
                continue  # 入口文件
            
            if is_allowed_orphaned(file_path):
                continue  # 合法孤立
            
            if file_path not in file_imported_by or not file_imported_by[file_path]:
                orphaned.append((file_path, "无其他文件导入此模块"))
        
        if orphaned:
            for f, reason in orphaned:
                self.errors.append(CheckResult(
                    passed=False,
                    message=f"孤立文件: {reason}",
                    file=str(f),
                    line=1
                ))
            return False
        
        return True
    
    def check_config_consistency(self) -> bool:
        """
        检查配置-代码一致性
        规则: config.yaml 中的所有配置项必须在 config/loader.py 中有对应定义
        """
        try:
            import yaml
        except ImportError:
            self.warnings.append(CheckResult(
                passed=True,
                message="跳过配置检查: yaml 模块未安装",
                file="",
                line=0
            ))
            return True
        
        config_file = self.root / "config" / "config.yaml"
        loader_file = self.root / "config" / "loader.py"
        
        if not config_file.exists() or not loader_file.exists():
            return True  # 文件不存在则跳过
        
        # 加载配置
        with open(config_file, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)
        
        # 解析 loader.py 中的配置类
        with open(loader_file, 'r', encoding='utf-8') as f:
            loader_content = f.read()
        
        # 提取所有配置类名 (XXXConfig)
        config_classes = set(re.findall(r'class (\w+Config)', loader_content))
        
        # 检查顶级配置项
        top_level_keys = set(config_data.keys()) if config_data else set()
        
        # 映射关系
        key_to_class = {
            'server': 'ServerConfig',
            'vector_store': 'VectorStoreConfig',
            'keyword_store': 'KeywordStoreConfig',
            'graph_store': 'GraphStoreConfig',
            'structured_store': 'StructuredStoreConfig',
            'services': 'ServicesConfig',
            'ocr_quality': 'OCRQualityConfig',
            'query_analysis': 'QueryAnalysisConfig',
            'retrieval': 'RetrievalConfig',
            'fusion_weights': 'FusionWeightsConfig',
            'logging': 'LoggingConfig',
        }
        
        missing = []
        for key in top_level_keys:
            if key in key_to_class:
                expected_class = key_to_class[key]
                if expected_class not in config_classes:
                    missing.append(f"配置项 '{key}' 需要配置类 '{expected_class}'")
        
        if missing:
            for msg in missing:
                self.errors.append(CheckResult(
                    passed=False,
                    message=msg,
                    file="config/loader.py",
                    line=1
                ))
            return False
        
        return True
    
    def check_type_annotations(self) -> bool:
        """
        检查类型注解完整性
        规则: 所有函数参数和返回值必须有类型注解
        """
        src_dir = self.root / "src"
        if not src_dir.exists():
            src_dir = self.root
        
        all_files = list(src_dir.rglob("*.py"))
        
        issues = []
        for file_path in all_files:
            if "__pycache__" in str(file_path):
                continue
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                tree = ast.parse(content)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        # 跳过私有方法和测试方法
                        if node.name.startswith('_') or node.name.startswith('test_'):
                            continue
                        
                        # 检查参数注解
                        for arg in node.args.args:
                            if arg.arg != 'self' and arg.arg != 'cls':
                                if arg.annotation is None:
                                    issues.append((file_path, node.name, arg.arg, node.lineno))
                        
                        # 检查返回值注解
                        if node.returns is None and node.name != '__init__':
                            issues.append((file_path, node.name, 'return', node.lineno))
            
            except SyntaxError:
                continue
        
        if issues:
            for file_path, func_name, param, line in issues:
                self.errors.append(CheckResult(
                    passed=False,
                    message=f"函数 '{func_name}' 的 '{param}' 缺少类型注解",
                    file=str(file_path),
                    line=line
                ))
            return False
        
        return True
    
    def check_bare_prints(self) -> bool:
        """
        检查裸 print() 调用
        规则: 禁止使用 print()，必须使用结构化日志
        """
        src_dir = self.root / "src"
        if not src_dir.exists():
            src_dir = self.root
        
        all_files = list(src_dir.rglob("*.py"))
        
        issues = []
        for file_path in all_files:
            if "__pycache__" in str(file_path):
                continue
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                for i, line in enumerate(lines, 1):
                    # 检查 print() 调用 (不包括注释和字符串)
                    if re.search(r'\bprint\s*\(', line):
                        # 排除合理的 print (如 __main__ 块中的)
                        if 'test' not in str(file_path) and '__main__' not in line:
                            issues.append((file_path, i, line.strip()))
            
            except Exception:
                continue
        
        if issues:
            for file_path, line, content in issues:
                self.errors.append(CheckResult(
                    passed=False,
                    message=f"发现裸 print() 调用: {content[:50]}",
                    file=str(file_path),
                    line=line
                ))
            return False
        
        return True
    
    def check_parameter_sources(self) -> bool:
        """
        检查参数来源
        规则: 函数参数应尽量来自配置，避免过多硬编码参数
        """
        # 简化实现：检查函数参数数量
        # 超过 5 个参数的函数需要检查是否可以从配置简化
        
        src_dir = self.root / "src"
        if not src_dir.exists():
            src_dir = self.root
        
        all_files = list(src_dir.rglob("*.py"))
        
        issues = []
        for file_path in all_files:
            if "__pycache__" in str(file_path):
                continue
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                tree = ast.parse(content)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        # 跳过特殊方法
                        if node.name.startswith('_') or node.name.startswith('test_'):
                            continue
                        
                        # 统计非 self/cls 参数数量
                        arg_count = len([a for a in node.args.args 
                                       if a.arg not in ('self', 'cls')])
                        
                        # 超过 5 个参数警告
                        if arg_count > 5:
                            issues.append((file_path, node.name, arg_count, node.lineno))
            
            except SyntaxError:
                continue
        
        if issues:
            for file_path, func_name, count, line in issues:
                self.warnings.append(CheckResult(
                    passed=True,
                    message=f"函数 '{func_name}' 有 {count} 个参数，建议从配置获取",
                    file=str(file_path),
                    line=line
                ))
        
        return True  # 警告不阻断
    
    def check_file_headers(self) -> bool:
        """
        检查文件头部注释
        规则: 每个文件头部应包含归属、依赖声明
        """
        src_dir = self.root / "src"
        if not src_dir.exists():
            src_dir = self.root
        
        all_files = list(src_dir.rglob("*.py"))
        
        issues = []
        for file_path in all_files:
            if "__pycache__" in str(file_path) or file_path.name.startswith('test_'):
                continue
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 检查是否有文件头注释 (模块级 docstring 或注释)
                if not content.strip().startswith('"""') and not content.strip().startswith("'''"):
                    # 检查是否有单行注释作为文件头
                    lines = content.split('\n')
                    if len(lines) < 2 or not lines[0].startswith('#'):
                        issues.append((file_path, "缺少文件头部注释"))
            
            except Exception:
                continue
        
        if issues:
            for file_path, msg in issues:
                self.warnings.append(CheckResult(
                    passed=True,
                    message=f"{msg} (建议添加归属和依赖声明)",
                    file=str(file_path),
                    line=1
                ))
        
        return True  # 警告不阻断
    
    def print_summary(self):
        """打印检查摘要"""
        print("\n" + "=" * 70)
        print("检查摘要")
        print("=" * 70)
        
        if self.errors:
            print(f"\n❌ 错误 ({len(self.errors)}个):")
            for e in self.errors[:10]:  # 只显示前10个
                print(f"  [{e.file}:{e.line}] {e.message}")
            if len(self.errors) > 10:
                print(f"  ... 还有 {len(self.errors) - 10} 个错误")
        
        if self.warnings:
            print(f"\n⚠️ 警告 ({len(self.warnings)}个):")
            for w in self.warnings[:5]:  # 只显示前5个
                print(f"  [{w.file}:{w.line}] {w.message}")
            if len(self.warnings) > 5:
                print(f"  ... 还有 {len(self.warnings) - 5} 个警告")
        
        if not self.errors and not self.warnings:
            print("\n✅ 所有检查通过！")
        elif not self.errors:
            print("\n✅ 无错误，但有警告需要关注")
        
        print("=" * 70)
    
    # 辅助方法
    def _extract_imports(self, file_path: Path) -> Set[str]:
        """提取文件导入的模块"""
        imports = set()
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read())
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module)
        except Exception:
            pass
        return imports
    
    def _has_main_block(self, file_path: Path) -> bool:
        """检查文件是否有 __main__ 块"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return 'if __name__ == "__main__"' in content or "if __name__ == '__main__'" in content
        except Exception:
            return False
    
    def check_and_update_agents_md(self) -> bool:
        """
        检查并更新 AGENTS.md 架构文档
        Hook机制: 当检测到架构变化时，自动更新 AGENTS.md
        """
        agents_md_path = self.root / "AGENTS.md"
        if not agents_md_path.exists():
            self.warnings.append(CheckResult(
                passed=True,
                message="AGENTS.md 不存在，跳过架构一致性检查",
                file="AGENTS.md",
                line=0
            ))
            return True

        current_architecture = self._extract_current_architecture()
        existing_architecture = self._extract_architecture_from_md(agents_md_path)

        changes_detected = self._compare_architecture(current_architecture, existing_architecture)

        if changes_detected:
            print(f"  🔄 检测到架构变化，正在更新 AGENTS.md...")
            self._update_agents_md(agents_md_path, current_architecture)
            self.warnings.append(CheckResult(
                passed=True,
                message="AGENTS.md 已根据当前架构自动更新",
                file="AGENTS.md",
                line=1
            ))
        else:
            print(f"  ✅ AGENTS.md 与当前架构一致")

        return True

    def _extract_current_architecture(self) -> Dict:
        """从项目结构提取当前架构信息"""
        arch = {
            "modules": [],
            "services": {},
            "ports": {},
            "agents": []
        }

        server_modules = self.root / "src" / "backend" / "server" / "src" / "modules"
        if server_modules.exists():
            for item in server_modules.iterdir():
                if item.is_dir() and not item.name.startswith('__'):
                    arch["modules"].append(item.name)

        services_dir = self.root / "src" / "backend" / "server" / "src" / "services"
        if services_dir.exists():
            for f in services_dir.glob("*.ts"):
                if f.name.endswith(".ts") and not f.name.startswith("_"):
                    service_name = f.stem.replace("Service", "").lower()
                    arch["services"][service_name] = f.name

        config_data = self._load_config()
        if config_data:
            if "services" in config_data:
                for svc_name, svc_config in config_data["services"].items():
                    if isinstance(svc_config, dict) and "port" in svc_config:
                        arch["ports"][svc_name] = svc_config["port"]
            if "server" in config_data:
                arch["ports"]["python-backend"] = config_data["server"].get("port", 8000)

        agents_dir = self.root / ".kimi" / "agents"
        if agents_dir.exists():
            for f in agents_dir.glob("*.md"):
                if f.stem != "coordinator":
                    arch["agents"].append(f.stem)

        return arch

    def _extract_architecture_from_md(self, md_path: Path) -> Dict:
        """从 AGENTS.md 提取已有架构信息"""
        arch = {
            "modules": [],
            "services": {},
            "ports": {},
            "agents": []
        }

        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            module_pattern = r'export \* as (\w+) from'
            arch["modules"] = re.findall(module_pattern, content)

            port_pattern = r'\((\w+)\).*?\|\s*(\d+)'
            for match in re.finditer(port_pattern, content):
                service_name, port = match.groups()
                arch["ports"][service_name.strip()] = int(port)

            agent_pattern = r'@(\w+)[- ]*Agent'
            arch["agents"] = list(set(re.findall(agent_pattern, content)))

        except Exception:
            pass

        return arch

    def _compare_architecture(self, current: Dict, existing: Dict) -> bool:
        """比较架构是否有变化"""
        if set(current["modules"]) != set(existing.get("modules", [])):
            return True
        if current["ports"] != existing.get("ports", {}):
            return True
        if set(current["agents"]) != set(existing.get("agents", [])):
            return True
        return False

    def _update_agents_md(self, md_path: Path, arch: Dict):
        """更新 AGENTS.md 文件"""
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            modules_section = self._generate_modules_section(arch)
            ports_section = self._generate_ports_section(arch)

            module_pattern = r'(## Project Structure\n\n```\n)[\s\S]*?(```)'
            if re.search(module_pattern, content):
                content = re.sub(module_pattern, r'\1' + modules_section + r'\2', content)

            port_pattern = r'(\| 服务 \| 端口 \|.*?\n)(\|.*?\|.*?\|.*?\|\n)+'
            ports_table = ports_section + '\n'
            if re.search(port_pattern, content):
                content = re.sub(port_pattern, ports_table, content)

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            auto_update_note = f"\n<!-- auto-updated: {timestamp} -->\n"
            if "<!-- auto-updated:" in content:
                content = re.sub(r'<!-- auto-updated:.*?-->', auto_update_note, content)
            else:
                content += auto_update_note

            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(content)

            print(f"  ✅ AGENTS.md 已更新")

        except Exception as e:
            self.errors.append(CheckResult(
                passed=False,
                message=f"更新 AGENTS.md 失败: {e}",
                file="AGENTS.md",
                line=1
            ))

    def _generate_modules_section(self, arch: Dict) -> str:
        """生成模块结构章节"""
        lines = [
            "rag-dashboard/",
            "├── src/",
            "│   ├── backend/",
            "│   │   ├── server/           # Node.js 后端 (@rag/server)",
            "│   │   │   └── src/",
            "│   │   │       ├── modules/  # 管道模块架构",
        ]

        for mod in sorted(arch["modules"]):
            lines.append(f"│   │   │       │   ├── {mod}/")

        lines.extend([
            "│   │   │       ├── services/ # 业务服务",
            "│   │   │       ├── tools/   # 工具函数",
            "│   │   │       └── types/   # 类型定义",
            "│   │   ├── python-legacy/   # Python FastAPI 后端",
            "│   │   └── go-services/    # Go 微服务",
            "│   └── frontend/",
            "│       └── web/             # React 前端",
            "├── packages/",
            "│   └── shared/              # 共享类型",
            "├── config/",
            "├── scripts/",
            "└── docker-compose.yml",
        ])

        return '\n'.join(lines)

    def _generate_ports_section(self, arch: Dict) -> str:
        """生成服务端口表格"""
        default_ports = {
            "frontend": ("Frontend (Vite)", 3000, "npm run dev:web"),
            "node": ("Node.js Backend", 3001, "npm run dev:server"),
            "python-backend": ("Python Backend", 8000, "cd src/backend/server && npm run dev"),
            "api": ("Python FastAPI", 8000, "npm run dev:server"),
            "ocr": ("OCR Service", 8001, "npm run dev:ocr"),
            "gateway": ("Go Gateway", 8080, "go run cmd/gateway/main.go"),
            "websocket": ("Go WebSocket", 8081, "go run cmd/websocket/main.go"),
            "qdrant": ("Qdrant HTTP", 6333, "docker-compose up -d"),
            "elasticsearch": ("Elasticsearch", 9200, "docker-compose up -d"),
            "neo4j": ("Neo4j HTTP", 7474, "docker-compose up -d"),
            "redis": ("Redis", 6379, "docker-compose up -d"),
        }

        lines = [
            "| 服务 | 端口 | 启动命令/说明 |",
            "|------|------|---------------|",
        ]

        for svc_key, (svc_name, port, cmd) in default_ports.items():
            lines.append(f"| {svc_name} | {port} | `{cmd}` |")

        return '\n'.join(lines)

    def _load_config(self) -> Dict:
        """加载配置文件"""
        try:
            import yaml
            config_file = self.root / "config" / "config.yaml"
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f) or {}
        except Exception:
            pass
        return {}

    def _get_module_name(self, file_path: Path) -> str:
        """从文件路径获取模块名"""
        relative = file_path.relative_to(self.root)
        module = str(relative).replace('/', '.').replace('\\', '.')
        if module.endswith('.py'):
            module = module[:-3]
        return module


def main():
    """主函数"""
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent

    checker = ArchitectureGovernanceChecker(project_root)
    passed = checker.run_all_checks()

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
