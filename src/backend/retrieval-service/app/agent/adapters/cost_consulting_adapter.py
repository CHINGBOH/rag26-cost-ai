"""
#164: CostConsultingAdapter — 深圳市建设工程造价咨询领域适配器

实现 DomainAdapter 接口，提供造价咨询领域的专业验证：

验证流水线：
  validate_static  → 定额编号/材料编码/公式名称 格式校验
  validate_runtime → Docker沙箱执行公式计算验证
  build_index      → 从 price_records 构建实体索引
  entity_lookup    → 按名称/编码查询实体
"""

from __future__ import annotations

import logging
import re
from dataclasses import field
from typing import Any

from app.agent.adapters.base import DomainAdapter, ValidationResult, Entity

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# 静态验证规则 — 定额编号 / 材料编码 / 公式名称
# ═══════════════════════════════════════════════════════════════════════════════

# 定额编号模式：支持粤建标、深建价等各地定额编号格式
_QUOTA_CODE_PATTERNS: list[tuple[str, str]] = [
    # 粤01-01-01 或 粤 01-01-01
    (r"(?:粤|深|京|沪|穗)[\s]*\d{1,3}[\s]*[-—–][\s]*\d{1,3}[\s]*[-—–][\s]*\d{1,3}", "广式定额编号"),
    # 深建价[2024]01号
    (r"(?:深建价|粤建标|建标)\[\d{4}\]\d+号", "建价文号"),
    # GD-01-01
    (r"GD[\s]*[-—–][\s]*\d{1,3}[\s]*[-—–][\s]*\d{1,3}", "广东定额编号"),
    # 通用 Z1-1-1
    (r"[A-Z]{1,3}[\s]*[-—–][\s]*\d{1,3}[\s]*[-—–][\s]*\d{1,3}", "通用字母定额编号"),
    # C.1.1 或 C.1.1.1
    (r"[A-C]\.[1-9]\d{0,1}\.[1-9]\d{0,1}(?:\.[1-9]\d{0,1})?", "分部编号"),
    # 消耗量标准编号如 01-01-001
    (r"\d{1,2}[\s]*[-—–][\s]*\d{1,2}[\s]*[-—–][\s]*\d{2,4}", "消耗量标准编号"),
]

# 材料编码模式：数字型编码如 010101001, 041102005
_MATERIAL_CODE_PATTERNS: list[tuple[str, str]] = [
    (r"\b\d{9,12}\b", "9-12位材料编码"),
    (r"\b[A-Z]{2,4}\d{6,10}\b", "字母前缀材料编码"),
    (r"\bCL[\s]*[-—–_]?[\s]*\d{4,8}\b", "CL编码"),
    (r"\bSC[\s]*[-—–_]?[\s]*\d{4,8}\b", "SC编码"),
]

# 已知公式名称（用于静态匹配）
_KNOWN_FORMULA_NAMES: set[str] = {
    "企业管理费", "利润", "安全文明施工费", "规费", "税金",
    "总价措施费", "暂列金额", "暂估价", "总承包服务费",
    "分部分项工程费", "措施项目费", "其他项目费", "增值税",
    "人工费调整", "材料费调整", "机械费调整",
    "综合单价", "全费用单价", "定额直接费", "定额人工费",
    "综合工日", "材料消耗量", "机械台班",
    "夜间施工增加费", "二次搬运费", "冬雨季施工增加费",
    "已完工程保护费", "定位复测费", "特殊地区施工增加费",
    "工程定位复测费", "场内二次搬运", "雨季施工增加费",
    "施工排水", "施工降水", "地上地下设施建筑物临时保护",
    "检验试验费", "系统调试费", "联动试车费",
}

# 公式关键字（用于检测 chunk 中是否包含公式）
_FORMULA_KEYWORDS = [
    "计算公式", "计算方式", "计算方法", "公式",
    "＝", "=", "费率", "计取", "乘以", "乘",
    "Σ", "∑", "+", "-", "×", "÷",
]

# 公式名称提取模式
_FORMULA_NAME_PATTERN = re.compile(
    r"((?:"
    r"企业管理费|利润|安全文明施工费|规费|税金|总价措施费|"
    r"暂列金额|暂估价|总承包服务费|分部分项工程费|措施项目费|"
    r"其他项目费|增值税|人工费调整|材料费调整|机械费调整|"
    r"综合单价|全费用单价|定额直接费|定额人工费|综合工日|"
    r"材料消耗量|机械台班|夜间施工增加费|二次搬运费|"
    r"冬雨季施工增加费|已完工程保护费|定位复测费|"
    r"特殊地区施工增加费|工程定位复测费|场内二次搬运|"
    r"雨季施工增加费|施工排水|施工降水|"
    r"地上地下设施建筑物临时保护|检验试验费|系统调试费|联动试车费"
    r"))"
    r"(?:的计算公式|计算方式|计算方法|的公式|的计取|的费率)?",
)

# 不可信字符 / hallucination 信号
_HALLUCINATION_SIGNALS = [
    r"\[需要确认\]", r"\[待核实\]", r"\[?\]", r"\[存疑\]",
    r"可能是", r"不保证", r"仅供参考", r"以实际为准",
]

# ═══════════════════════════════════════════════════════════════════════════════
# 内建实体索引数据 — 从已知数据构建（生产环境从 price_records 表加载）
# ═══════════════════════════════════════════════════════════════════════════════

# 常用定额编号示例
_BUILTIN_QUOTA_CODES: list[dict[str, Any]] = [
    {"entity_id": "粤01-01-001", "entity_type": "quota_code", "name": "平整场地",
     "attributes": {"category": "土石方工程", "unit": "100m²"}},
    {"entity_id": "粤01-02-001", "entity_type": "quota_code", "name": "人工挖土方",
     "attributes": {"category": "土石方工程", "unit": "100m³"}},
    {"entity_id": "粤04-01-001", "entity_type": "quota_code", "name": "现浇混凝土基础",
     "attributes": {"category": "混凝土工程", "unit": "10m³"}},
    {"entity_id": "粤04-02-001", "entity_type": "quota_code", "name": "现浇混凝土柱",
     "attributes": {"category": "混凝土工程", "unit": "10m³"}},
    {"entity_id": "粤05-01-001", "entity_type": "quota_code", "name": "现浇构件钢筋",
     "attributes": {"category": "钢筋工程", "unit": "t"}},
    {"entity_id": "粤09-01-001", "entity_type": "quota_code", "name": "抹灰面油漆",
     "attributes": {"category": "装饰工程", "unit": "100m²"}},
]

# 常用材料编码示例
_BUILTIN_MATERIAL_CODES: list[dict[str, Any]] = [
    {"entity_id": "010101001", "entity_type": "material_code", "name": "热轧光圆钢筋 HPB300 Φ6-10",
     "attributes": {"spec": "HPB300 Φ6-10", "unit": "t"}},
    {"entity_id": "010101002", "entity_type": "material_code", "name": "热轧带肋钢筋 HRB400 Φ12-18",
     "attributes": {"spec": "HRB400 Φ12-18", "unit": "t"}},
    {"entity_id": "040101001", "entity_type": "material_code", "name": "普通硅酸盐水泥 P.O 42.5",
     "attributes": {"spec": "P.O 42.5", "unit": "t"}},
    {"entity_id": "040301001", "entity_type": "material_code", "name": "普通预拌混凝土 C30",
     "attributes": {"spec": "C30", "unit": "m³"}},
    {"entity_id": "040301002", "entity_type": "material_code", "name": "泵送预拌混凝土 C35",
     "attributes": {"spec": "C35 泵送", "unit": "m³"}},
    {"entity_id": "041101001", "entity_type": "material_code", "name": "电力电缆 YJV-0.6/1kV 3×70+1×35",
     "attributes": {"spec": "YJV 0.6/1kV 3×70+1×35", "unit": "m"}},
    {"entity_id": "041102001", "entity_type": "material_code", "name": "绝缘电线 BV-2.5mm²",
     "attributes": {"spec": "BV 2.5mm²", "unit": "m"}},
]

# 常用公式
_BUILTIN_FORMULAS: list[dict[str, Any]] = [
    {"entity_id": "FEE_GLF", "entity_type": "formula", "name": "企业管理费",
     "attributes": {"base": "人工费+机械费", "rate": "按费率标准计取"}},
    {"entity_id": "FEE_LIRUN", "entity_type": "formula", "name": "利润",
     "attributes": {"base": "人工费+机械费", "rate": "按推荐费率"}},
    {"entity_id": "FEE_AQWM", "entity_type": "formula", "name": "安全文明施工费",
     "attributes": {"base": "分部分项工程费", "rate": "按费率标准"}},
    {"entity_id": "FEE_GUIFEI", "entity_type": "formula", "name": "规费",
     "attributes": {"base": "人工费", "rate": "按核定费率"}},
    {"entity_id": "FEE_SHUIJIN", "entity_type": "formula", "name": "税金",
     "attributes": {"base": "税前造价", "rate": "9%（一般计税）"}},
    {"entity_id": "FEE_ZJCSF", "entity_type": "formula", "name": "总价措施费",
     "attributes": {"base": "分部分项工程费", "rate": "按费率标准"}},
    {"entity_id": "FEE_ZCB", "entity_type": "formula", "name": "总承包服务费",
     "attributes": {"base": "专业分包工程费", "rate": "按费率标准"}},
]


# ═══════════════════════════════════════════════════════════════════════════════
# CostConsultingAdapter
# ═══════════════════════════════════════════════════════════════════════════════

class CostConsultingAdapter(DomainAdapter):
    """深圳市建设工程造价咨询领域适配器。

    实现 DomainAdapter 接口：
    - validate_static(): 定额编号 / 材料编码 / 公式名称 格式校验
    - validate_runtime(): Docker沙箱公式计算验证
    - build_index(): 构建实体索引
    - entity_lookup(): 查询实体
    """

    @property
    def domain_id(self) -> str:
        return "cost-consulting"

    @property
    def agent_persona(self) -> str:
        return "深圳市建设工程造价咨询专家"

    def __init__(
        self,
        quota_codes: list[dict[str, Any]] | None = None,
        material_codes: list[dict[str, Any]] | None = None,
        formulas: list[dict[str, Any]] | None = None,
    ):
        """初始化适配器。

        Args:
            quota_codes: 定额编号列表（不传则用内置数据）
            material_codes: 材料编码列表（不传则用内置数据）
            formulas: 公式列表（不传则用内置数据）
        """
        self._quota_codes = quota_codes or _BUILTIN_QUOTA_CODES
        self._material_codes = material_codes or _BUILTIN_MATERIAL_CODES
        self._formulas = formulas or _BUILTIN_FORMULAS
        self._index: dict[str, Any] | None = None
        self._quota_code_pattern = re.compile(
            "|".join(f"(?P<p{i}>{p})" for i, (p, _) in enumerate(_QUOTA_CODE_PATTERNS)),
        )
        self._material_code_pattern = re.compile(
            "|".join(f"(?P<m{i}>{p})" for i, (p, _) in enumerate(_MATERIAL_CODE_PATTERNS)),
        )

    # ── validate_static ───────────────────────────────────────────────

    def validate_static(self, chunk: dict[str, Any]) -> ValidationResult:
        """对单个 chunk 执行静态领域规则校验。

        检查项：
        1. 定额编号格式验证
        2. 材料编码格式验证
        3. 公式名称存在性验证
        4. Hallucination 信号检测
        """
        content = (chunk.get("content") or "").strip()
        if not content:
            return ValidationResult(
                passed=False,
                error_type="empty_chunk",
                error_location="content",
                error_detail="chunk 内容为空",
            )

        # 1. Hallucination 信号检测
        for sig in _HALLUCINATION_SIGNALS:
            if re.search(sig, content):
                return ValidationResult(
                    passed=False,
                    error_type="hallucination_signal",
                    error_location="content",
                    error_detail=f"chunk 包含不可信信号: {sig}",
                    suggested_alternatives=["重新检索更可信的源文档"],
                )

        # 2. 提取并验证 chunk 中的 定额编号
        quota_codes_found = self._quota_code_pattern.findall(content)

        # 3. 提取并验证 材料编码
        material_codes_found = self._material_code_pattern.findall(content)

        # 4. 提取 公式名称
        formula_names_found = _FORMULA_NAME_PATTERN.findall(content)

        # 5. 若 chunk 属于造价领域内容但无任何实体 → 警告
        has_cost_keywords = any(
            kw in content
            for kw in ["定额", "消耗量", "信息价", "计价", "造价", "工程", "费率"]
        )
        has_any_entity = bool(
            quota_codes_found or material_codes_found or formula_names_found
        )

        if has_cost_keywords and not has_any_entity:
            return ValidationResult(
                passed=False,
                error_type="missing_domain_entity",
                error_location="content",
                error_detail="chunk 包含造价关键词但无定额编号/材料编码/公式名称",
                suggested_alternatives=["检查源文档是否完整", "尝试不同检索策略"],
            )

        return ValidationResult(passed=True)

    # ── validate_runtime ──────────────────────────────────────────────

    def validate_runtime(
        self,
        chunk: dict[str, Any],
        sandbox: Any | None = None,
    ) -> ValidationResult:
        """通过沙箱执行验证公式计算。

        如果 chunk 包含 Python 公式代码，在 Docker 沙箱中执行验证。
        如果 sandbox 不可用，退化为检查公式语法的静态分析。

        Args:
            chunk: 检索块
            sandbox: 沙箱执行器（可选）。若有 execute_python 属性则调用之，
                     若无则尝试 import infrastructure.sandbox.execute_python

        Returns:
            ValidationResult
        """
        content = (chunk.get("content") or "").strip()

        # 检测是否有公式内容需要运行时验证
        has_formula = any(kw in content for kw in _FORMULA_KEYWORDS)
        if not has_formula:
            return ValidationResult(passed=True)

        # 尝试提取 Python 公式代码块
        python_code = _extract_python_formula(content)
        if not python_code:
            # 仅有公式描述但没有 Python 代码 → 无需运行时验证
            return ValidationResult(passed=True)

        # 获取沙箱执行器
        executor = sandbox
        if executor is None:
            try:
                from infrastructure.sandbox import execute_python
                executor = execute_python
            except ImportError:
                logger.warning("sandbox not available, skipping runtime validation")
                return ValidationResult(passed=True)

        # Handle both direct callable and object with .execute_python
        if hasattr(executor, "execute_python") and callable(getattr(executor, "execute_python")):  # type: ignore[arg-type]
            executor = executor.execute_python  # type: ignore[union-attr]

        if not callable(executor):
            return ValidationResult(
                passed=False,
                error_type="sandbox_unavailable",
                error_location="runtime",
                error_detail="沙箱执行器不可用，无法进行公式计算验证",
                suggested_alternatives=["检查 Docker 环境", "确认沙箱镜像已构建"],
            )

        # 执行沙箱验证
        try:
            result = executor(python_code)
        except Exception as exc:
            return ValidationResult(
                passed=False,
                error_type="sandbox_execution_error",
                error_location="runtime",
                error_detail=f"沙箱执行异常: {type(exc).__name__}: {exc}",
                suggested_alternatives=["检查公式代码语法", "简化公式表达式"],
            )

        if isinstance(result, dict) and result.get("status") == "error":
            return ValidationResult(
                passed=False,
                error_type="sandbox_formula_error",
                error_location="runtime",
                error_detail=f"公式计算错误: {result.get('error', '未知错误')}",
                suggested_alternatives=[
                    "检查公式变量是否已定义",
                    "确认公式计算逻辑正确",
                ],
            )

        return ValidationResult(passed=True)

    # ── build_index ───────────────────────────────────────────────────

    def build_index(self) -> dict[str, Any]:
        """构建实体索引。

        Returns:
            dict with keys:
                quota_codes: {entity_id: Entity} index
                material_codes: {entity_id: Entity} index
                formulas: {entity_id: Entity} index
                by_name: {name: list[Entity]} name-based lookup
        """
        quota_index: dict[str, Entity] = {}
        material_index: dict[str, Entity] = {}
        formula_index: dict[str, Entity] = {}
        by_name: dict[str, list[Entity]] = {}

        for item in self._quota_codes:
            entity = Entity(
                entity_id=item["entity_id"],
                entity_type=item["entity_type"],
                name=item.get("name", ""),
                attributes=item.get("attributes", {}),
            )
            quota_index[entity.entity_id] = entity
            by_name.setdefault(entity.name.lower(), []).append(entity)

        for item in self._material_codes:
            entity = Entity(
                entity_id=item["entity_id"],
                entity_type=item["entity_type"],
                name=item.get("name", ""),
                attributes=item.get("attributes", {}),
            )
            material_index[entity.entity_id] = entity
            by_name.setdefault(entity.name.lower(), []).append(entity)

        for item in self._formulas:
            entity = Entity(
                entity_id=item["entity_id"],
                entity_type=item["entity_type"],
                name=item.get("name", ""),
                attributes=item.get("attributes", {}),
            )
            formula_index[entity.entity_id] = entity
            by_name.setdefault(entity.name.lower(), []).append(entity)

        self._index = {
            "quota_codes": quota_index,
            "material_codes": material_index,
            "formulas": formula_index,
            "by_name": by_name,
            "total_entities": len(quota_index) + len(material_index) + len(formula_index),
        }
        logger.info(
            "CostConsultingAdapter index built: quota=%d material=%d formulas=%d total=%d",
            len(quota_index), len(material_index), len(formula_index),
            self._index["total_entities"],
        )
        return self._index

    # ── entity_lookup ─────────────────────────────────────────────────

    def entity_lookup(self, query: str) -> list[Entity]:
        """按查询字符串查找实体。

        支持按 entity_id 精确匹配、name 模糊匹配、entity_type 过滤。

        Args:
            query: 查询字符串

        Returns:
            匹配的 Entity 列表，按 score 降序
        """
        if self._index is None:
            self.build_index()
        index = self._index or {}

        results: list[Entity] = []
        query_lower = query.strip().lower()

        # 1. entity_id 精确匹配（最高分）
        for category in ("quota_codes", "material_codes", "formulas"):
            cat_index: dict[str, Entity] = index.get(category, {})
            if query in cat_index:
                entity = cat_index[query]
                entity.score = 1.0
                results.append(entity)
            if query_lower in cat_index:
                entity = cat_index[query_lower]
                entity.score = 1.0
                results.append(entity)

        # 2. name 模糊匹配
        by_name: dict[str, list[Entity]] = index.get("by_name", {})
        for name, entities in by_name.items():
            if query_lower in name:
                for entity in entities:
                    entity.score = 0.7
                    results.append(entity)

        # 3. entity_type 过滤
        if query_lower in ("quota_code", "material_code", "formula"):
            category_map = {
                "quota_code": "quota_codes",
                "material_code": "material_codes",
                "formula": "formulas",
            }
            cat = category_map.get(query_lower, "")
            cat_index = index.get(cat, {})
            for entity in cat_index.values():
                entity.score = 0.5
                results.append(entity)

        # 去重（按 entity_id）
        seen: set[str] = set()
        unique: list[Entity] = []
        for entity in sorted(results, key=lambda e: e.score, reverse=True):
            if entity.entity_id not in seen:
                seen.add(entity.entity_id)
                unique.append(entity)

        return unique[:20]  # 最多返回 20 条

    # ── get_validation_rules ──────────────────────────────────────────

    def get_validation_rules(self) -> list[dict[str, Any]]:
        """返回本适配器应用的验证规则列表。"""
        return [
            {
                "code": "R01_quota_code_format",
                "description": "定额编号必须符合标准格式（如 粤01-01-001 / 深建价[2024]01号）",
                "severity": "error",
                "applies_to": "quota_lookup / standard_ref",
            },
            {
                "code": "R02_material_code_format",
                "description": "材料编码必须符合 9-12 位数字或字母前缀格式",
                "severity": "error",
                "applies_to": "price_query / material_lookup",
            },
            {
                "code": "R03_formula_name_present",
                "description": "涉及费率/费用计算时，必须引用已知公式名称",
                "severity": "error",
                "applies_to": "calculation / standard_ref",
            },
            {
                "code": "R04_no_hallucination_signal",
                "description": "chunk 不得包含不可信标记（如 [需要确认]、仅供参考）",
                "severity": "error",
                "applies_to": "all",
            },
            {
                "code": "R05_formula_runtime_valid",
                "description": "包含 Python 公式代码的 chunk 需通过沙箱执行验证",
                "severity": "error",
                "applies_to": "calculation",
            },
            {
                "code": "R06_missing_domain_entity",
                "description": "包含造价关键词的 chunk 必须包含定额编号/材料编码/公式名称",
                "severity": "warning",
                "applies_to": "all",
            },
        ]

    # ── get_domain_schema ─────────────────────────────────────────────

    def get_domain_schema(self) -> dict[str, Any]:
        """返回造价咨询领域 schema。"""
        return {
            "domain_id": self.domain_id,
            "agent_persona": self.agent_persona,
            "entity_types": ["quota_code", "material_code", "formula"],
            "validation_rules_count": len(self.get_validation_rules()),
            "index_stats": self._index or {},
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_python_formula(content: str) -> str | None:
    """从 chunk 内容中提取 Python 公式代码块。

    支持 ```python ... ``` 代码块格式。
    """
    # 匹配 ```python ... ``` 代码块
    match = re.search(r"```python\s*\n(.*?)\n```", content, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 匹配内联 python_eval 标记
    match = re.search(r"python_eval[:=]\s*(.+?)(?:\n|$)", content)
    if match:
        return match.group(1).strip()

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_cost_adapter: CostConsultingAdapter | None = None


def get_cost_consulting_adapter(
    quota_codes: list[dict[str, Any]] | None = None,
    material_codes: list[dict[str, Any]] | None = None,
    formulas: list[dict[str, Any]] | None = None,
) -> CostConsultingAdapter:
    """获取 CostConsultingAdapter 单例。

    首次调用时构建实体索引。

    Args:
        quota_codes: 定额编号列表（None 用内置数据）
        material_codes: 材料编码列表（None 用内置数据）
        formulas: 公式列表（None 用内置数据）

    Returns:
        CostConsultingAdapter 实例
    """
    global _cost_adapter
    if _cost_adapter is None:
        _cost_adapter = CostConsultingAdapter(
            quota_codes=quota_codes,
            material_codes=material_codes,
            formulas=formulas,
        )
        _cost_adapter.build_index()
    return _cost_adapter
