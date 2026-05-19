from app.tender_review import RiskCategory, RiskSeverity, scan_tender_text


def test_scan_tender_text_detects_signature_and_rejection_risks():
    text = (
        "投标文件须由法定代表人签字并加盖公章，否则作无效投标处理。\n"
        "投标保证金须在递交截止时间前到账。"
    )

    risks = scan_tender_text(text, max_hits_per_rule=4)

    assert risks
    assert any(item.category == RiskCategory.SIGNATURE_SEAL for item in risks)
    assert any(item.category == RiskCategory.REJECTION for item in risks)
    assert any(item.category == RiskCategory.GUARANTEE for item in risks)
    assert any(item.severity == RiskSeverity.CRITICAL for item in risks)


def test_scan_tender_text_limits_hits_per_rule():
    text = "\n".join(
        [
            "投标文件须由法定代表人签字。",
            "授权代表须签字。",
            "签字并盖章。",
            "法定代表人须亲笔签字。",
        ]
    )

    risks = scan_tender_text(text, max_hits_per_rule=2)
    signature_hits = [item for item in risks if item.rule_id == "TENDER-SIGN-001"]

    assert len(signature_hits) == 2
