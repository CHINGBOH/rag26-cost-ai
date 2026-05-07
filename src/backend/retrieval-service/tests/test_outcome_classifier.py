def test_classify_chitchat_as_non_task():
    from app.agent.outcome_classifier import classify_interaction_outcome

    outcome = classify_interaction_outcome(
        query_type="chitchat",
        final_answer="您好！",
        evaluation={},
        chunks=[],
    )

    assert outcome.outcome_family == "non_task"
    assert outcome.outcome_code == "EARLY_EXIT_CHITCHAT"
    assert outcome.quality == "non_task"
    assert outcome.learning_eligible is False
    assert outcome.early_exit is True


def test_classify_refusal_with_extended_markers():
    from app.agent.outcome_classifier import classify_interaction_outcome

    outcome = classify_interaction_outcome(
        query_type="comparison",
        final_answer="根据现有资料，当前无法直接计算该问题，暂时无法给出可靠结论。",
        evaluation={"confidence": 0.92, "information_gain": 0.91},
        chunks=[{"id": "c1"}],
    )

    assert outcome.outcome_family == "refused"
    assert outcome.outcome_code == "REFUSED_INSUFFICIENT_EVIDENCE"
    assert outcome.quality == "failure"
    assert outcome.refused is True


def test_classify_weak_answer():
    from app.agent.outcome_classifier import classify_interaction_outcome

    outcome = classify_interaction_outcome(
        query_type="price",
        final_answer="可能是 12 元。",
        evaluation={"confidence": 0.2, "information_gain": 0.1},
        chunks=[{"id": "c1"}],
    )

    assert outcome.outcome_family == "answered"
    assert outcome.outcome_code == "ANSWERED_WEAK_EVIDENCE"
    assert outcome.quality == "weak"
    assert outcome.learning_eligible is True


def test_classify_failed_timeout():
    from app.agent.outcome_classifier import classify_interaction_outcome

    outcome = classify_interaction_outcome(
        query_type="price",
        final_answer="",
        evaluation=None,
        chunks=[],
        error_message="TIMEOUT",
    )

    assert outcome.outcome_family == "failed"
    assert outcome.outcome_code == "FAILED_TIMEOUT"
    assert outcome.quality == "failure"
    assert outcome.status == "error"
