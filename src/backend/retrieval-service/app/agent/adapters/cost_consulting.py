import re
from typing import Callable, List, Optional

from app.agent.adapters.base import DomainAdapter, Entity, ValidationResult

# Quota number patterns: 定额编号 like A1-1, 010101001, JD01-001
# Use negative lookbehind/lookahead to avoid matching mid-number; avoid \b which
# treats Chinese chars as word chars in Python Unicode mode.
_QUOTA_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"([A-Z]{1,3}\d[-\d]{2,8}|[A-Z]{0,2}\d{1,2}-\d{2,6}|\d{5,10})"
    r"(?![0-9A-Za-z])"
)
# Chapter/section references like 第三章, 3.1.2
_CHAPTER_RE = re.compile(
    r"第[一二三四五六七八九十百千]+章|第\s*\d+\s*章|\d+\.\d+(\.\d+)?"
)
# Price values with units
_PRICE_RE = re.compile(r"[\d,]+\.?\d*\s*(元|万元|元/[^\s，。]{1,10})")
_FORMULA_RE = re.compile(
    r"(?P<expr>(?:\d[\d,]*(?:\.\d+)?|[+\-*/().%\s×÷]){3,})"
    r"[=＝]\s*"
    r"(?P<expected>-?\d[\d,]*(?:\.\d+)?)"
)
# Material names: optional grade prefix (C30, HRB400) + Chinese noun + material suffix
_MATERIAL_RE = re.compile(
    r"(?:[A-Z]\d+[一-龥]{0,3}|[一-龥]{1,6})"
    r"(?:钢管|水泥|混凝土|钢筋|砂浆|砖|角钢|槽钢|工字钢|"
    r"型钢|电缆|导线|管材|板材|石材|砂石|石子|碎石)"
)
# Citation pattern: 《书名》
_CITATION_RE = re.compile(r"《([^《》]{1,80})》")


def _normalize_source_name(name: str) -> str:
    if not name:
        return ""
    s = str(name).strip().strip("《》")
    for ext in (".pdf", ".PDF", ".xlsx", ".XLSX", ".docx", ".DOCX", ".md"):
        if s.endswith(ext):
            s = s[: -len(ext)]
    return s


class CostConsultingAdapter(DomainAdapter):
    """Domain adapter for Chinese construction cost consulting (建设工程造价咨询)."""

    domain_id = "construction-cost"
    agent_persona = "建设工程造价咨询 Agent，专注定额查询、费率计算和合规核验"

    def __init__(
        self,
        entity_store: Optional[Callable[[str], bool]] = None,
        sandbox_client=None,
    ):
        """
        entity_store: callable(quota_number: str) -> bool
            Returns True if the quota number exists in the knowledge base.
            Default (None) skips the existence check — safe for environments
            without a live index.
        sandbox_client: callable with .execute(code, timeout) -> SandboxResult
        """
        self._entity_store = entity_store
        self._sandbox_client = sandbox_client

    # ── validate_static ────────────────────────────────────────────────────────

    def validate_static(self, chunk: str) -> ValidationResult:
        """Check quota number existence and chapter reference format."""
        quota_numbers = _QUOTA_RE.findall(chunk)
        # findall returns tuples when groups present; unwrap
        quota_numbers = [q[0] if isinstance(q, tuple) else q for q in quota_numbers]

        if self._entity_store and quota_numbers:
            for qn in quota_numbers:
                if not self._entity_store(qn):
                    return ValidationResult(
                        passed=False,
                        error_type="SYMBOL_HALLUCINATION",
                        error_location=f"quota:{qn}",
                        error_detail=f"定额编号 {qn!r} 在知识库中不存在",
                        suggested_alternatives=self._suggest_quota_alternatives(qn),
                    )

        return ValidationResult(passed=True)

    def _suggest_quota_alternatives(self, quota: str) -> List[str]:
        # In production this would query the index for similar codes.
        return []

    # ── validate_runtime ───────────────────────────────────────────────────────

    def validate_runtime(self, chunk: str, sandbox) -> ValidationResult:
        """Execute formula expressions in sandbox and verify against stated values."""
        sandbox = sandbox or self._sandbox_client
        if sandbox is None:
            return ValidationResult(passed=True)

        checks = self._extract_formula_checks(chunk)
        if not checks:
            return ValidationResult(passed=True)

        for expression, expected_value in checks:
            result = self._execute_formula_check(sandbox, expression, expected_value)
            if not result.passed:
                return result

        return ValidationResult(passed=True)

    def _execute_formula_check(
        self,
        sandbox,
        expression: str,
        expected_value: float,
    ) -> ValidationResult:
        try:
            result = sandbox.execute(f"result = {expression}", timeout=30)
        except Exception as exc:
            return ValidationResult(
                passed=False,
                error_type="RUNTIME_ERROR",
                error_detail=f"Sandbox execution failed: {exc}",
            )

        if result.exit_code != 0:
            return ValidationResult(
                passed=False,
                error_type="RUNTIME_ERROR",
                error_location=result.stderr[:200] if result.stderr else "",
                error_detail=f"Formula execution exited with code {result.exit_code}",
            )

        computed_value = self._extract_computed_value(result)
        if computed_value is None:
            return ValidationResult(
                passed=False,
                error_type="RUNTIME_ERROR",
                error_detail="Sandbox did not return a numeric formula result",
            )
        return self._compare_formula_values(computed_value, expected_value)

    def _compare_formula_values(
        self,
        computed_value: float,
        expected_value: float,
    ) -> ValidationResult:
        diff = abs(computed_value - expected_value)
        tolerance = max(abs(expected_value) * 0.001, 1e-9)
        if diff <= tolerance:
            return ValidationResult(passed=True)

        deviation = (
            f"{diff / abs(expected_value):.2%}"
            if expected_value != 0
            else f"absolute diff {diff:g}"
        )
        return ValidationResult(
            passed=False,
            error_type="RUNTIME_ERROR",
            error_detail=(
                f"公式计算结果 {computed_value} 与文档值 {expected_value} "
                f"偏差 {deviation}，超过 0.1% 阈值"
            ),
        )

    def _extract_formula_checks(self, chunk: str) -> List[tuple[str, float]]:
        checks: List[tuple[str, float]] = []
        for match in _FORMULA_RE.finditer(chunk):
            expression = self._normalize_formula_expression(match.group("expr"))
            if expression is None:
                continue
            expected = float(match.group("expected").replace(",", ""))
            checks.append((expression, expected))
        return checks

    def _normalize_formula_expression(self, expression: str) -> Optional[str]:
        expr = expression.replace(",", "").replace("×", "*").replace("÷", "/").strip()
        expr = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", expr)
        if not re.fullmatch(r"[\d+\-*/().\s]+", expr):
            return None
        return expr

    def _extract_computed_value(self, result) -> Optional[float]:
        if hasattr(result, "computed_value"):
            return float(result.computed_value)

        candidates = [
            getattr(result, "result", None),
            getattr(result, "stdout", None),
            getattr(result, "output", None),
        ]
        for candidate in candidates:
            if candidate is None:
                continue
            match = re.search(r"-?\d+(?:\.\d+)?", str(candidate).replace(",", ""))
            if match:
                return float(match.group(0))
        return None

    # ── validate_factual ───────────────────────────────────────────────────────

    def validate_factual(self, chunk: str, kb) -> ValidationResult:
        """Check that cited sources and chapter references exist in retrieved chunks (kb)."""
        if not kb:
            return ValidationResult(passed=True)

        chunks = kb if isinstance(kb, list) else []
        cited = {
            _normalize_source_name(m)
            for m in _CITATION_RE.findall(chunk)
            if 2 < len(m) <= 60
        }
        if not cited:
            return ValidationResult(passed=True)

        available: set = set()
        for c in chunks:
            for key in ("doc_filename", "source", "file_name"):
                v = c.get(key)
                if v:
                    available.add(_normalize_source_name(v))
            meta = c.get("metadata") or {}
            for key in ("doc_filename", "source", "file_name", "book"):
                v = meta.get(key)
                if v:
                    available.add(_normalize_source_name(v))

        violations = [
            c for c in cited
            if not any(c in a or a in c for a in available if a)
        ]
        if violations:
            return ValidationResult(
                passed=False,
                error_type="FACTUAL_CONTRADICTION",
                error_location="citation",
                error_detail=f"引用来源不在检索结果中: {', '.join(violations[:3])}",
                suggested_alternatives=list(available)[:3],
            )

        return ValidationResult(passed=True)

    # ── extract_entities ───────────────────────────────────────────────────────

    def extract_entities(self, chunk: str) -> List[Entity]:
        entities: List[Entity] = []

        for match in _QUOTA_RE.finditer(chunk):
            qn = match.group(0)
            entities.append(Entity(name=qn, entity_type="quota_number", source="chunk"))

        for match in _MATERIAL_RE.finditer(chunk):
            entities.append(
                Entity(name=match.group(0), entity_type="material", source="chunk")
            )

        for match in _PRICE_RE.finditer(chunk):
            entities.append(
                Entity(name=match.group(0), entity_type="price_value", source="chunk")
            )

        return entities

    # ── seed_skills ────────────────────────────────────────────────────────────

    def seed_skills(self) -> List[dict]:
        return [
            {
                "name": "quota-lookup",
                "description": "按定额编号查询定额单价及工程量规则",
                "content": (
                    "## quota-lookup\n"
                    "用途: 根据定额编号（如 010101001）精确查询定额名称、单价、计量单位。\n"
                    "调用: quota_search(number='<编号>')\n"
                    "注意: 编号必须完整，不可缩写；结果需附来源页码。"
                ),
            },
            {
                "name": "formula-verify",
                "description": "验证造价公式计算结果与定额文档数值一致性",
                "content": (
                    "## formula-verify\n"
                    "用途: 对含数值公式的 chunk 进行沙箱执行，验证结果与文档值偏差 < 0.1%。\n"
                    "调用: sandbox_execute(code='<python表达式>')\n"
                    "注意: 超时 30s；结果包含 exit_code 和 stdout。"
                ),
            },
            {
                "name": "chapter-navigate",
                "description": "在定额文档目录中定位章节和条款",
                "content": (
                    "## chapter-navigate\n"
                    "用途: 给定章节号（如 3.1.2）或关键词，返回对应文档路径和页范围。\n"
                    "调用: chapter_search(query='<章节号或关键词>')\n"
                    "注意: 只引用已检索到的文档，不得引用未检索文档。"
                ),
            },
        ]

    # ── classify_hallucination ─────────────────────────────────────────────────

    def classify_hallucination(self, error: ValidationResult) -> str:
        mapping = {
            "SYMBOL_HALLUCINATION": "定额编号不存在",
            "RUNTIME_ERROR": "公式计算结果偏差",
            "FACTUAL_CONTRADICTION": "引用章节或文档不存在",
        }
        return mapping.get(error.error_type or "", "UNKNOWN")
