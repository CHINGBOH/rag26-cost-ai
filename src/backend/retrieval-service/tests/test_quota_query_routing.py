import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.agent import query_analyzer, tools


def test_extract_quota_search_term_keeps_core_rule_subject() -> None:
    term = query_analyzer.extract_quota_search_term(
        "安装工程消耗量标准中送配电装置系统调试的计算规则是什么？"
    )

    assert term == "送配电装置系统调试"


def test_extract_quota_search_term_prefers_material_name() -> None:
    term = query_analyzer.extract_quota_search_term(
        "25版装饰工程消耗量标准中，楼梯面层中玻璃地板的人工费是多少？"
    )

    assert term == "玻璃地板"


def test_should_include_structured_tables_only_for_fee_queries() -> None:
    assert tools._should_include_structured_tables("企业管理费推荐费率是多少")
    assert not tools._should_include_structured_tables("送配电装置系统调试的计算规则是什么")
    assert not tools._should_include_structured_tables("玻璃地板人工费是多少")


def test_fee_formula_queries_are_classified_as_standard_refs() -> None:
    analysis = query_analyzer.QueryAnalyzer().analyze("2025版费率标准中，企业管理费的计算方法是什么？")

    assert analysis["intent"] == "standard_ref"


def test_fee_standard_comparison_queries_use_comparison_intent() -> None:
    query = "2023版与2025版费率标准中，利润率的参考范围是否一致？"
    analysis = query_analyzer.QueryAnalyzer().analyze(query)

    assert analysis["intent"] == "comparison"
    assert query_analyzer.is_fee_standard_comparison_query(query)
    assert query_analyzer.extract_fee_standard_comparison_queries(query) == [
        "2023 利润率 参考范围",
        "2025 利润率 参考范围",
    ]


def test_annual_material_price_queries_keep_compound_material_and_year() -> None:
    analysis = query_analyzer.QueryAnalyzer().analyze("2025 年深圳信息价中钛合金门窗的价格是多少")

    assert analysis["intent"] == "price"
    assert analysis["entities"]["year_month"] == "2025"
    assert analysis["entities"]["material_name"] == "钛合金门窗"


def test_fill_requirement_queries_are_detected_and_keep_field_name() -> None:
    analysis = query_analyzer.QueryAnalyzer().analyze("工程项目中施工地点要按照什么要求填写")

    assert analysis["intent"] == "standard_ref"
    assert query_analyzer.is_fill_requirement_query("工程项目中施工地点要按照什么要求填写")
    assert query_analyzer.extract_fill_requirement_search_term("工程项目中施工地点要按照什么要求填写") == "施工地点"


def test_appendix_standard_queries_extract_title_and_clause_terms() -> None:
    query = "模块化建筑工程施工工期定额适用于单体预制箱体应用比例大于多少的 ±0.00 以上工程？"
    analysis = query_analyzer.QueryAnalyzer().analyze(query)

    assert analysis["intent"] == "standard_ref"
    assert query_analyzer.is_appendix_standard_query(query)
    assert query_analyzer.extract_appendix_standard_title(query) == "模块化建筑工程施工工期定额"
    terms = query_analyzer.extract_appendix_standard_terms(query)
    assert "预制箱体应用比例" in terms


def test_extract_fee_formula_search_term_keeps_year_and_fee_item() -> None:
    term = query_analyzer.extract_fee_formula_search_term("2025版费率标准中，企业管理费的计算方法是什么？")

    assert term == "2025 企业管理费 计算公式"


def test_structured_table_query_extracts_requested_standard_year() -> None:
    assert tools._extract_requested_standard_year("2025版费率标准中，利润的计算方法是什么？") == "2025"
    assert tools._extract_requested_standard_year("企业管理费的计算公式是什么？") == ""


def test_structured_table_query_extracts_all_requested_standard_years() -> None:
    assert tools._extract_requested_standard_years("2023版与2025版费率标准中，利润率的参考范围是否一致？") == [
        "2023",
        "2025",
    ]


def test_fee_formula_query_detection_matches_formula_questions() -> None:
    assert tools._is_fee_formula_query("2025版费率标准中，企业管理费的计算方法是什么？")
    assert tools._is_fee_formula_query("2025版费率标准中，安全文明施工费费率部分的计算公式是什么？")
    assert not tools._is_fee_formula_query("2025版费率标准中，企业管理费推荐费率是多少？")


def test_text_search_rolls_back_after_vector_error(monkeypatch) -> None:
    class FakeCursor:
        def __init__(self, conn, mode: str) -> None:
            self.conn = conn
            self.mode = mode

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params) -> None:
            if self.mode == "vector":
                raise RuntimeError("different vector dimensions 1024 and 768")

        def fetchall(self):
            return []

    class FakeConn:
        def __init__(self) -> None:
            self.cursor_calls = 0
            self.rollback_called = False

        def cursor(self):
            self.cursor_calls += 1
            mode = "fulltext" if self.cursor_calls == 1 else "vector"
            return FakeCursor(self, mode)

        def rollback(self) -> None:
            self.rollback_called = True

    fake_conn = FakeConn()
    literal_chunk = {
        "chunk_id": "tc_literal",
        "doc_id": "doc-1",
        "page_number": 314,
        "source_db": "literal_text",
        "content": "送配电装置系统调试 按系统调试说明执行",
        "score": 0.77,
        "metadata": {},
    }

    monkeypatch.setattr(tools, "_get_pg_conn", lambda: fake_conn)
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)
    monkeypatch.setattr(tools, "_get_embedding", lambda query: [0.1, 0.2, 0.3])
    monkeypatch.setattr(tools, "_query_text_chunks_literal", lambda conn, query, top_k=10: [literal_chunk])

    result = json.loads(tools.text_search.func("送配电装置系统调试", top_k=3))

    assert fake_conn.rollback_called is True
    assert result[0]["chunk_id"] == "tc_literal"


def test_query_fill_requirement_text_chunks_returns_exact_clause() -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params) -> None:
            self.query = query
            self.params = params

        def fetchall(self):
            return [
                (
                    42,
                    "doc_fill",
                    5,
                    "4.2.5施工地点应按招标文件或合同约定工程地点填写。",
                )
            ]

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    result = tools._query_fill_requirement_text_chunks(
        FakeConn(),
        "工程项目中施工地点要按照什么要求填写",
        top_k=3,
    )

    assert len(result) == 1
    assert result[0]["source_db"] == "fill_requirement_text"
    assert "施工地点应按招标文件或合同约定工程地点填写" in result[0]["content"]


def test_query_appendix_standard_text_chunks_returns_exact_clause() -> None:
    class FakeCursor:
        def __init__(self) -> None:
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params) -> None:
            self.calls += 1
            self.query = query
            self.params = params

        def fetchall(self):
            if self.calls == 1:
                return [("doc_appendix",)]
            return [
                (
                    73,
                    "doc_appendix",
                    12,
                    "3.0.1本定额工期适用于单体（栋）预制箱体应用比例大于50%的土0.00以上模块化建筑工程。",
                )
            ]

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    result = tools._query_appendix_standard_text_chunks(
        FakeConn(),
        "模块化建筑工程施工工期定额适用于单体预制箱体应用比例大于多少的 ±0.00 以上工程？",
        top_k=3,
    )

    assert len(result) == 1
    assert result[0]["source_db"] == "appendix_standard_text"
    assert "预制箱体应用比例大于50%" in result[0]["content"]


def test_query_fee_comparison_text_chunks_returns_both_years() -> None:
    class FakeCursor:
        def __init__(self) -> None:
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params) -> None:
            self.calls += 1
            self.query = query
            self.params = params

        def fetchall(self):
            if self.calls == 1:
                return [(11, "fee_rate_2023", 2, "利润率参考范围为3%～7%，推荐费率为5%。")]
            if self.calls == 2:
                return [(12, "fee_rate_2025", 1, "利润率参考范围为3%～7%，推荐费率为5%。")]
            return []

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    result = tools._query_fee_comparison_text_chunks(
        FakeConn(),
        "2023版与2025版费率标准中，利润率的参考范围是否一致？",
        top_k=4,
    )

    assert len(result) == 2
    assert {chunk["metadata"]["year"] for chunk in result} == {"2023", "2025"}
    assert all("3%～7%" in chunk["content"] for chunk in result)
