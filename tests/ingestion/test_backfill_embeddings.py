from importlib import util
from pathlib import Path


MODULE_PATH = Path("/home/l/rag-dashboard/src/database/scripts/backfill_embeddings.py")
SPEC = util.spec_from_file_location("backfill_embeddings_script", MODULE_PATH)
backfill_embeddings = util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(backfill_embeddings)


def test_fee_rate_projection_includes_semantic_fields():
    row = (
        7,
        "2025",
        "安全文明施工费",
        "措施费",
        "按分部分项工程费计取",
        "分部分项工程费",
        "房屋建筑工程",
        "1.5",
        "3.5",
        "2.8",
        "安全文明施工费包括环境保护、文明施工、安全施工和临时设施。",
    )

    text = backfill_embeddings._build_fee_rate_text(row)

    assert "安全文明施工费" in text
    assert "措施费" in text
    assert "standard_year=2025" in text
    assert "base_formula=按分部分项工程费计取" in text
    assert "calc_base=分部分项工程费" in text
    assert "applicable_scope=房屋建筑工程" in text
    assert "rate_recommended=2.8" in text
    assert "环境保护" in text


def test_fee_rates_table_is_supported_for_backfill():
    assert "fee_rates" in backfill_embeddings.TABLE_CONFIG
