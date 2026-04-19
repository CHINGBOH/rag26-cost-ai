# RAG Dashboard 架构治理规则

## 核心原则：有机整体架构

### 1. 文件归属规则

#### 1.1 每个文件必须有明确归属
```
✅ 合法文件位置:
- src/backend/python-legacy/services/*.py  → 业务服务层
- src/backend/python-legacy/infrastructure/adapters/*.py → 适配器层
- config/*.py → 配置层
- tests/**/*.py → 测试层
- scripts/**/*.py → 脚本层

❌ 非法文件位置:
- 根目录直接放 .py 文件 (除入口文件外)
- 无目录归属的孤立文件
- 重复的同名文件分散在不同目录
```

#### 1.2 文件依赖图谱
每个文件头部必须声明其依赖关系:
```python
"""
文件: services/ocr_quality_validator.py
归属: 业务服务层
依赖:
  - config/loader.py (配置加载)
  - domain_models/document.py (数据模型)
被依赖:
  - services/document_processor.py (调用验证)
  - api/routes.py (API调用)
输出协议: OCRQualityReport (dataclass)
"""
```

### 2. 输出标准化规则

#### 2.1 禁止裸 print()
```python
# ❌ 非法
print(f"OCR完成: {result}")

# ✅ 合法
from utils.logging import get_logger
logger = get_logger(__name__)
logger.info("ocr_completed", extra={
    "doc_id": doc_id,
    "page_count": len(pages),
    "confidence": avg_confidence
})
```

#### 2.2 Shell 命令输出必须结构化
```python
# ❌ 非法
os.system("python script.py")

# ✅ 合法
from utils.shell import run_command

result = run_command(
    cmd=["python", "script.py"],
    capture_output=True,
    output_schema={
        "status": "string",  # success | error
        "data": "object",
        "error": "string | null"
    }
)

# result 必须符合定义的 schema
assert validate_output(result, expected_schema)
```

#### 2.3 进程间通信协议
```python
# 所有服务间调用必须通过统一协议
class ServiceCall:
    """标准化服务调用"""
    
    # 输入参数必须来自配置
    input_config: InputSchema = get_config().services.ocr
    
    # 输出必须符合协议
    output_protocol: OutputSchema = OCRResultSchema
    
    def call(self, params: ValidatedParams) -> ValidatedOutput:
        # 参数必须经过验证
        validated = self.validate_params(params, self.input_config)
        
        # 执行
        result = self.execute(validated)
        
        # 输出必须符合协议
        return self.validate_output(result, self.output_protocol)
```

### 3. 参数统一管理规则

#### 3.1 禁止随意函数参数
```python
# ❌ 非法 - 随意参数
def process_ocr(image_path, lang="ch", gpu=False, timeout=30, quality_check=True):
    pass

# ✅ 合法 - 参数来自配置
from config.loader import get_config

class OCRProcessor:
    def __init__(self):
        # 所有参数从配置初始化
        self.config = get_config().services.ocr
        self.quality_config = get_config().ocr_quality
    
    def process(self, image_path: Path) -> OCRResult:
        # 使用配置中的参数，不在函数签名中重复定义
        lang = self.config.language
        gpu = self.config.gpu
        timeout = self.config.timeout
        quality_check = self.quality_config.enabled
        
        # 只有动态变化的参数才在函数签名中
        return self._do_process(image_path, lang, gpu, timeout, quality_check)
```

#### 3.2 参数来源追溯
```python
# 每个参数必须有明确来源注释
def analyze_query(query: str) -> QueryResult:
    """
    参数来源:
    - query: 来自API请求体 (routes.py:47)
    
    配置依赖:
    - analysis_config: config/query_analysis.yaml:15
    - llm_config: config/.env:LLM_API_KEY
    
    输出协议:
    - QueryResult: domain_models/query.py:23
    """
    config = get_config().query_analysis
    
    # 所有子参数从 config 获取，不传参
    intent_threshold = config.intent_thresholds.trend
    max_subqueries = config.max_subqueries
```

### 4. 类型强制规则

#### 4.1 所有类型必须显式声明
```python
# ❌ 非法
def process(data, options=None):
    result = some_operation(data)
    return result

# ✅ 合法
from typing import Optional, Dict, Any
from dataclasses import dataclass
from pydantic import BaseModel

class ProcessInput(BaseModel):
    """输入类型 - 必须定义"""
    data: str
    options: Optional[Dict[str, Any]] = None

class ProcessOutput(BaseModel):
    """输出类型 - 必须定义"""
    success: bool
    result: str
    metadata: Dict[str, Any]

def process(input_data: ProcessInput) -> ProcessOutput:
    """函数签名必须完整类型注解"""
    result = some_operation(input_data.data)
    return ProcessOutput(
        success=True,
        result=result,
        metadata={}
    )
```

#### 4.2 类型检查强制执行
```python
# 运行时类型检查装饰器
from utils.typing import strict_types

@strict_types
def calculate_fusion_score(
    vector_score: float,  # 必须: 0.0-1.0
    keyword_score: float,
    rerank_score: float
) -> FusionResult:
    """
    类型检查:
    - 输入: 所有参数必须是 float
    - 范围: 0.0 <= score <= 1.0
    - 输出: 必须是 FusionResult 类型
    """
    pass
```

### 5. 配置-代码映射规则

#### 5.1 配置即 API 契约
```yaml
# config/config.yaml
retrieval:
  vector_top_k: 30    # ← 这个值自动成为代码中的类型约束
  score_threshold: 0.6  # ← float in [0.0, 1.0]
  enable_rerank: true   # ← bool
```

```python
# config/loader.py 自动生成类型
class RetrievalConfig(BaseSettings):
    """Pydantic 自动从配置生成类型约束"""
    
    vector_top_k: int = Field(default=30, ge=1, le=100)
    score_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    enable_rerank: bool = True
```

#### 5.2 配置变更影响分析
```python
# 配置变更时自动检查影响范围
class ConfigRegistry:
    """配置注册表 - 追踪配置使用情况"""
    
    registry = {
        "retrieval.vector_top_k": [
            "retrieval/multi_stage_retriever.py:45",
            "retrieval/vector_store.py:78",
            "api/routes.py:156"
        ],
        "ocr_quality.confidence_threshold": [
            "services/ocr_quality_validator.py:89"
        ]
    }
    
    @classmethod
    def check_impact(cls, config_key: str) -> List[str]:
        """返回所有受影响的代码位置"""
        return cls.registry.get(config_key, [])
```

### 6. 验证与检查规则

#### 6.1 提交前检查清单
```bash
#!/bin/bash
# scripts/check-governance.sh

echo "🔍 架构治理检查..."

# 1. 孤立文件检查
echo "→ 检查孤立文件..."
python scripts/check_orphaned_files.py

# 2. 类型完整性检查
echo "→ 检查类型注解..."
mypy src/backend/python-legacy/ --strict

# 3. 配置-代码一致性检查
echo "→ 检查配置一致性..."
python scripts/check_config_consistency.py

# 4. 输出协议检查
echo "→ 检查输出协议..."
python scripts/check_output_protocols.py

# 5. 参数来源检查
echo "→ 检查参数管理..."
python scripts/check_parameter_governance.py

echo "✅ 所有检查通过"
```

#### 6.2 运行时验证
```python
# 启动时验证整个系统
class SystemValidator:
    """系统启动验证器"""
    
    def validate(self) -> ValidationReport:
        checks = [
            self._check_file_integrity(),      # 文件依赖图谱完整
            self._check_config_loading(),      # 配置能正确加载
            self._check_type_consistency(),    # 类型一致
            self._check_output_protocols(),    # 输出协议合规
            self._check_service_connectivity(),  # 服务连通性
        ]
        
        return ValidationReport(
            all_passed=all(c.passed for c in checks),
            checks=checks
        )
```

### 7. 文件关系图谱

```yaml
# .windsurf/dependency-graph.yaml
# 人工维护的依赖关系图谱

files:
  config/loader.py:
    type: "config"
    provides:
      - "RAGConfig"
      - "get_config()"
    used_by:
      - "services/ocr_quality_validator.py"
      - "services/query_analysis_agent.py"
      - "infrastructure/adapters/structured_store.py"
    
  services/ocr_quality_validator.py:
    type: "service"
    depends_on:
      - "config/loader.py"
      - "domain_models/document.py"
    provides:
      - "OCRQualityValidator"
      - "OCRQualityReport"
    used_by:
      - "services/document_processor.py"
    
  api/unified_api.py:
    type: "api"
    depends_on:
      - "retrieval/unified_pipeline.py"
      - "services/document_processor.py"
    provides:
      - "FastAPI app"

# 禁止的依赖 (循环依赖、跨层依赖)
forbidden_dependencies:
  - from: "services/*"
    to: "api/*"  # 服务层不能依赖API层
  
  - from: "config/*"
    to: "services/*"  # 配置层不能依赖服务层
```

### 8. 实施检查清单

#### 新文件创建检查清单
```markdown
□ 文件头部注释包含归属、依赖、输出协议声明
□ 所有参数来自 config/，无硬编码
□ 所有类型显式注解，使用 Pydantic 或 dataclass
□ 无裸 print()，使用结构化日志
□ shell 调用使用封装工具，输出被验证
□ 在 dependency-graph.yaml 中注册
□ 通过 mypy --strict 检查
□ 通过 check_orphaned_files.py 检查
```

#### 代码审查检查清单
```markdown
□ 函数参数是否都来自配置？
□ 是否有随意添加的默认参数？
□ 输出是否符合声明的协议？
□ 是否有孤立的类型定义？
□ 配置变更是否影响其他文件？
□ 类型检查是否完整？
```

---

## 附：自动化检查脚本

### check_orphaned_files.py
```python
#!/usr/bin/env python3
"""检查孤立文件"""

import os
import ast
from pathlib import Path
from collections import defaultdict

def find_python_files(root: Path) -> list:
    return list(root.rglob("*.py"))

def extract_imports(file_path: Path) -> tuple:
    """提取文件的导入和被导入关系"""
    imports = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read())
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.append(module)
    except:
        pass
    
    return file_path, imports

def build_dependency_graph(files: list) -> dict:
    """构建依赖图谱"""
    graph = defaultdict(list)
    
    for file_path in files:
        _, imports = extract_imports(file_path)
        graph[file_path].extend(imports)
    
    return graph

def find_orphaned_files(files: list, graph: dict) -> list:
    """找出孤立文件"""
    orphaned = []
    
    for file_path in files:
        # 检查是否有文件导入它
        imported_by = []
        for other_file, imports in graph.items():
            if other_file == file_path:
                continue
            
            file_module = str(file_path).replace('/', '.').replace('.py', '')
            for imp in imports:
                if file_module.endswith(imp) or imp in file_module:
                    imported_by.append(other_file)
        
        # 如果没有被导入，可能是孤立文件
        if not imported_by and not file_path.name.startswith('test_'):
            # 检查是否是入口文件
            content = file_path.read_text()
            if 'if __name__ == "__main__"' not in content:
                orphaned.append((file_path, "无文件导入此模块"))
    
    return orphaned

if __name__ == "__main__":
    root = Path("src")
    files = find_python_files(root)
    graph = build_dependency_graph(files)
    orphaned = find_orphaned_files(files, graph)
    
    if orphaned:
        print("⚠️ 发现孤立文件:")
        for f, reason in orphaned:
            print(f"  - {f}: {reason}")
        exit(1)
    else:
        print("✅ 无孤立文件")
        exit(0)
```

### check_config_consistency.py
```python
#!/usr/bin/env python3
"""检查配置-代码一致性"""

import ast
import yaml
from pathlib import Path

def load_config_schema() -> dict:
    """从 config/loader.py 加载配置 schema"""
    # 解析 RAGConfig 类定义
    loader_file = Path("config/loader.py")
    with open(loader_file, 'r') as f:
        tree = ast.parse(f.read())
    
    # 提取所有配置字段
    schemas = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and item.target:
                    field_name = item.target.id if isinstance(item.target, ast.Name) else None
                    if field_name:
                        schemas[field_name] = ast.unparse(item.annotation) if item.annotation else "Any"
    
    return schemas

def check_config_yaml():
    """检查 config.yaml 与代码一致"""
    config_file = Path("config/config.yaml")
    config_data = yaml.safe_load(config_file.read_text())
    
    schema = load_config_schema()
    errors = []
    
    # 检查 config.yaml 中的每个字段是否在 schema 中
    def check_dict(d, prefix=""):
        for key, value in d.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if full_key not in schema:
                errors.append(f"配置项 '{full_key}' 在配置类中未定义")
            
            if isinstance(value, dict):
                check_dict(value, full_key)
    
    check_dict(config_data)
    
    return errors

if __name__ == "__main__":
    errors = check_config_yaml()
    
    if errors:
        print("⚠️ 配置不一致:")
        for e in errors:
            print(f"  - {e}")
        exit(1)
    else:
        print("✅ 配置一致性检查通过")
        exit(0)
```
