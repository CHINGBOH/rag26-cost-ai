import importlib.util
from pathlib import Path


MODULE_PATH = Path("/home/l/rag-dashboard/src/database/scripts/import_fee_rates.py")
SPEC = importlib.util.spec_from_file_location("import_fee_rates_script", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
import_fee_rates = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(import_fee_rates)


def test_parse_fee_text_extracts_profit_and_management_from_clean_text() -> None:
    text = """
    （一）企业管理费
    1.综合单价构成中的企业管理费计算公式如下：
    企业管理费=（人工费+机械费×0.1）×企业管理费费率
    2.根据目前本市建筑施工企业管理水平的实际情况，不区分专业工程，企业管理费费率参考范围为14%～26%，推荐费率为20.44%。
    （二）利润
    1.综合单价构成中的利润计算公式如下：
    利润=（人工费+材料费+机械费+企业管理费）×利润率
    2.根据国家公布的行业利润率水平和目前本市建筑施工企业的实际盈利情况，不区分专业工程，利润率参考范围为3%～7%，推荐费率为5%。
    """

    records = import_fee_rates.parse_fee_text(text, "2025")
    by_name = {record["fee_name"]: record for record in records}

    assert by_name["企业管理费"]["rate_min"] == 14.0
    assert by_name["企业管理费"]["rate_max"] == 26.0
    assert by_name["利润"]["rate_min"] == 3.0
    assert by_name["利润"]["rate_max"] == 7.0
    assert "利润率" in (by_name["利润"].get("base_formula") or "")


def test_parse_fee_text_normalizes_broken_fee_names() -> None:
    text = """
    2.根据目前本市建筑施工企业管理水平的实际情况，不区分专业工
    程，企业管理费费率参考范围为9%～25%，推荐费率为16.2%。
    （二）利润
    1.综合单价构成中的利润计算公式如下：
    利润：F=（人工费A+材料费B+机械费C+企业管理费E）×利润率b
    2.根据国家公布的行业利润率水平和目前本市建筑施工企业的实际赢利情况，不区分专业工程，利润率参考范围为3%～7%，推荐费率为5%。
    """

    records = import_fee_rates.parse_fee_text(text, "2023")
    names = {record["fee_name"] for record in records}

    assert "企业管理费" in names
    assert "利润" in names
    assert "程，企业管理费" not in names
