"""Tender / commercial risk review APIs.

This module is intentionally rule-first. It provides an immediately usable
preview endpoint for hard-risk scanning before a full LLM review workflow is
wired into the existing retrieval and agent stack.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/commercial", tags=["commercial-tender-review"])


class RiskSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RiskCategory(str, Enum):
    REJECTION = "rejection_or_invalid_bid"
    SIGNATURE_SEAL = "signature_and_seal"
    QUALIFICATION = "qualification"
    REQUIRED_ATTACHMENT = "required_attachment"
    DEADLINE = "deadline"
    GUARANTEE = "bid_bond_or_guarantee"
    FORMAT_SUBMISSION = "format_and_submission"
    CLARIFICATION = "clarification_needed"


class ReviewTextRequest(BaseModel):
    text: str = Field(..., min_length=1, description="已解析的招标文件文本")
    document_name: Optional[str] = Field(default=None, description="文档名，仅用于回显")
    max_hits_per_rule: int = Field(default=4, ge=1, le=20)


class EvidenceSpan(BaseModel):
    excerpt: str
    line_start: int
    line_end: int
    matched_pattern: str


class TenderRiskItem(BaseModel):
    category: RiskCategory
    severity: RiskSeverity
    title: str
    requirement: str
    evidence: EvidenceSpan
    why_it_matters: str
    recommended_action: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    needs_human_review: bool = True
    rule_id: str


class ReviewPreviewResponse(BaseModel):
    document_name: Optional[str]
    total_rules_scanned: int
    total_risks: int
    critical_count: int
    high_count: int
    risks: List[TenderRiskItem]
    summary: Dict[str, Any]


class RuleDefinition(BaseModel):
    rule_id: str
    category: RiskCategory
    severity: RiskSeverity
    title: str
    patterns: List[str]
    requirement: str
    why_it_matters: str
    recommended_action: str
    confidence: float = 0.86


RULES: List[RuleDefinition] = [
    RuleDefinition(
        rule_id="TENDER-REJECT-001",
        category=RiskCategory.REJECTION,
        severity=RiskSeverity.CRITICAL,
        title="发现否决投标 / 无效投标硬性表述",
        patterns=[
            r"(?:否则|未按|不符合).{0,24}(?:按无效投标处理|作无效投标处理|否决其投标|投标无效)",
            r"(?:有下列情形之一|出现下列情形).{0,18}(?:否决|无效)",
            r"(?:资格审查|符合性审查).{0,18}(?:不通过|不合格).{0,18}(?:否决|无效)",
        ],
        requirement="该段通常定义了一票否决或直接导致投标失效的条件。",
        why_it_matters="此类条款与中标概率无关，一旦触发，项目通常直接出局。",
        recommended_action="逐条转成内部核对清单，并在正式投标前由商务负责人二次确认。",
        confidence=0.94,
    ),
    RuleDefinition(
        rule_id="TENDER-SIGN-001",
        category=RiskCategory.SIGNATURE_SEAL,
        severity=RiskSeverity.CRITICAL,
        title="发现法定代表人 / 董事长 / 授权代表签署要求",
        patterns=[
            r"(?:法定代表人|董事长|授权代表).{0,18}(?:亲笔签字|签字|签署)",
            r"(?:不得|不能).{0,12}(?:以盖章代替签字|用盖章代替签字)",
            r"(?:签字并盖章|签字和盖章|签署并加盖公章)",
        ],
        requirement="招标文件对签署主体和签章形式有明确要求。",
        why_it_matters="签字、盖章、签署主体错一个，极易构成格式性废标。",
        recommended_action="单独生成《签字盖章审查表》，将签署人、签字/盖章动作和页码逐项核对。",
        confidence=0.96,
    ),
    RuleDefinition(
        rule_id="TENDER-QUAL-001",
        category=RiskCategory.QUALIFICATION,
        severity=RiskSeverity.HIGH,
        title="发现资格条件 / 业绩 / 人员 / 证照硬要求",
        patterns=[
            r"(?:投标人|供应商).{0,18}(?:须具备|必须具备|应具备).{0,36}(?:资质|资格|许可证|等级)",
            r"(?:项目负责人|项目经理|技术负责人).{0,24}(?:须|必须|应).{0,24}(?:证书|职称|注册|社保)",
            r"(?:近[一二三四五六七八九十\d]+年).{0,32}(?:类似业绩|合同业绩|项目业绩)",
        ],
        requirement="该段通常决定企业是否具备入围资格。",
        why_it_matters="资质、人员、业绩、社保等材料缺失或不匹配，会导致资格审查失败。",
        recommended_action="建立《资格响应矩阵》，逐项对应公司材料、有效期和证明文件。",
        confidence=0.88,
    ),
    RuleDefinition(
        rule_id="TENDER-ATTACH-001",
        category=RiskCategory.REQUIRED_ATTACHMENT,
        severity=RiskSeverity.HIGH,
        title="发现必须提交的附件 / 证明材料",
        patterns=[
            r"(?:须提供|必须提供|应提供).{0,42}(?:复印件|扫描件|原件|证明|承诺函|授权委托书|营业执照|财务报表)",
            r"(?:附件|格式).{0,16}(?:不得修改|须按|必须按).{0,20}(?:编制|填写|提交)",
        ],
        requirement="招标文件要求提交特定格式或特定证明材料。",
        why_it_matters="附件遗漏、格式误用、模板改写，是最常见的低级废标原因之一。",
        recommended_action="将命中的材料全部转成可勾选附件清单，并指定责任人。",
        confidence=0.9,
    ),
    RuleDefinition(
        rule_id="TENDER-DEADLINE-001",
        category=RiskCategory.DEADLINE,
        severity=RiskSeverity.HIGH,
        title="发现关键时间节点",
        patterns=[
            r"(?:投标截止时间|递交截止时间|开标时间|答疑截止时间|保证金截止时间).{0,32}",
            r"(?:不得迟于|应于).{0,18}(?:前|之前).{0,18}(?:递交|到账|提交)",
        ],
        requirement="该段定义报名、递交、答疑、保证金、开标等关键节点。",
        why_it_matters="过时即失效，尤其是保证金到账时间和文件递交截止时间。",
        recommended_action="抽取到项目时间轴，并设置商务、财务、用印三方提醒。",
        confidence=0.89,
    ),
    RuleDefinition(
        rule_id="TENDER-BOND-001",
        category=RiskCategory.GUARANTEE,
        severity=RiskSeverity.HIGH,
        title="发现投标保证金 / 保函要求",
        patterns=[
            r"(?:投标保证金|保证金|投标保函).{0,36}(?:金额|到账|形式|银行|保函|缴纳)",
            r"(?:未提交|未缴纳|未按要求提交).{0,24}(?:保证金|保函).{0,18}(?:无效|否决)",
        ],
        requirement="招标文件对保证金、保函、到账或提交形式有要求。",
        why_it_matters="保证金金额、账户、到账时间、保函格式任一错误，都会直接影响投标有效性。",
        recommended_action="单列财务动作清单，标注金额、账户、截止时间、凭证要求。",
        confidence=0.92,
    ),
    RuleDefinition(
        rule_id="TENDER-FORMAT-001",
        category=RiskCategory.FORMAT_SUBMISSION,
        severity=RiskSeverity.HIGH,
        title="发现份数 / 密封 / 装订 / 电子签章要求",
        patterns=[
            r"(?:正本|副本).{0,24}(?:份|册)",
            r"(?:密封|封套|骑缝章|逐页盖章|电子签章|CA锁|上传).{0,28}",
            r"(?:未按要求密封|未按规定装订|未按规定签章).{0,18}(?:无效|否决)",
        ],
        requirement="该段控制投标文件的物理或电子提交合规性。",
        why_it_matters="份数、密封、装订、电子签章和上传路径经常是现场/系统废标点。",
        recommended_action="生成《递交前最终检查单》，作为出门前和上传前的最后门禁。",
        confidence=0.9,
    ),
]


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。；;！？!?])\s*|\n+")


def _iter_segments(text: str) -> Iterable[tuple[int, str]]:
    line_no = 1
    for raw_line in text.splitlines() or [text]:
        stripped = raw_line.strip()
        if not stripped:
            line_no += 1
            continue
        for segment in _SENTENCE_SPLIT_RE.split(stripped):
            seg = segment.strip()
            if seg:
                yield line_no, seg
        line_no += 1


def _make_excerpt(segment: str, limit: int = 220) -> str:
    return segment if len(segment) <= limit else segment[: limit - 1] + "…"


def scan_tender_text(text: str, max_hits_per_rule: int) -> List[TenderRiskItem]:
    risks: List[TenderRiskItem] = []
    segments = list(_iter_segments(text))

    for rule in RULES:
        hits = 0
        for line_no, segment in segments:
            if hits >= max_hits_per_rule:
                break
            for pattern in rule.patterns:
                if re.search(pattern, segment):
                    risks.append(
                        TenderRiskItem(
                            category=rule.category,
                            severity=rule.severity,
                            title=rule.title,
                            requirement=rule.requirement,
                            evidence=EvidenceSpan(
                                excerpt=_make_excerpt(segment),
                                line_start=line_no,
                                line_end=line_no,
                                matched_pattern=pattern,
                            ),
                            why_it_matters=rule.why_it_matters,
                            recommended_action=rule.recommended_action,
                            confidence=rule.confidence,
                            needs_human_review=True,
                            rule_id=rule.rule_id,
                        )
                    )
                    hits += 1
                    break
    return risks


@router.get("/tender/rule-catalog")
async def tender_rule_catalog() -> Dict[str, Any]:
    return {
        "count": len(RULES),
        "rules": [rule.model_dump() for rule in RULES],
        "note": "规则库用于高召回预扫，不替代人工终审。",
    }


@router.post("/tender/review-preview", response_model=ReviewPreviewResponse)
async def tender_review_preview(request: ReviewTextRequest) -> ReviewPreviewResponse:
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空")

    risks = scan_tender_text(text, request.max_hits_per_rule)
    critical_count = sum(1 for item in risks if item.severity == RiskSeverity.CRITICAL)
    high_count = sum(1 for item in risks if item.severity == RiskSeverity.HIGH)

    by_category: Dict[str, int] = {}
    for item in risks:
        by_category[item.category.value] = by_category.get(item.category.value, 0) + 1

    return ReviewPreviewResponse(
        document_name=request.document_name,
        total_rules_scanned=len(RULES),
        total_risks=len(risks),
        critical_count=critical_count,
        high_count=high_count,
        risks=risks,
        summary={
            "by_category": by_category,
            "deployment_positioning": "private-first commercial tender review",
            "recommended_next_step": "将高危命中项转为项目级商务核对清单，并结合 RAG/LLM 进行二次语义审查。",
        },
    )
