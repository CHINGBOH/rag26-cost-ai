import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.agent import tools


def test_build_query_concepts_prefers_concept_then_trend_for_multi_material_change() -> None:
    concepts = tools._build_query_concepts("2026年1月，电线、电缆价格较上月的变化幅度是多少？")

    assert [item["concept_name"] for item in concepts[:2]] == ["电线", "电缆"]
    assert all(item["preferred_tool"] == "price_trend" for item in concepts[:2])


def test_concept_search_returns_drilldown_concepts(monkeypatch) -> None:
    class FakeConn:
        pass

    monkeypatch.setattr(tools, "_get_pg_conn", lambda: FakeConn())
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)
    monkeypatch.setattr(tools, "_expand_concept_hits", lambda conn, query, concept_hits, top_k=3: [])
    monkeypatch.setattr(
        tools,
        "_load_concept_hits",
        lambda conn, query, top_k=6: [
            {
                "chunk_id": "concept_1_material_电缆",
                "doc_id": "doc_price_202601",
                "page_number": 12,
                "source_db": "concept_search",
                "content": "概念:电缆 类型:material 结构化命中:8 文本命中:1 建议下钻:price_trend",
                "score": 0.91,
                "metadata": {
                    "concept_name": "电缆",
                    "concept_type": "material",
                    "structured_hits": 8,
                    "text_hits": 1,
                    "preferred_tool": "price_trend",
                    "retrieval_path": "database",
                },
                "retrieval_path": "database",
            }
        ],
    )

    result = json.loads(tools.concept_search.func("2026年1月，电缆价格较上月的变化幅度是多少？", top_k=3))

    assert len(result) == 1
    assert result[0]["source_db"] == "concept_search"
    assert result[0]["metadata"]["preferred_tool"] == "price_trend"


def test_concept_search_includes_recursive_evidence(monkeypatch) -> None:
    class FakeConn:
        pass

    monkeypatch.setattr(tools, "_get_pg_conn", lambda: FakeConn())
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)
    monkeypatch.setattr(
        tools,
        "_load_concept_hits",
        lambda conn, query, top_k=6: [
            {
                "chunk_id": "concept_1_material_电缆",
                "doc_id": "doc_price_202601",
                "page_number": 12,
                "source_db": "concept_search",
                "content": "概念:电缆",
                "score": 0.91,
                "metadata": {
                    "concept_name": "电缆",
                    "concept_type": "material",
                    "preferred_tool": "price_query",
                    "concept_terms": ["电缆"],
                },
                "retrieval_path": "database",
            }
        ],
    )
    monkeypatch.setattr(
        tools,
        "_expand_concept_hits",
        lambda conn, query, concept_hits, top_k=2: [
            {
                "chunk_id": "concept_price_101",
                "doc_id": "doc_price_202601",
                "page_number": 18,
                "source_db": "price_records",
                "content": "电缆 单位:m 价格:605.73元 期间:2026-01",
                "score": 0.88,
                "metadata": {
                    "parent_concept_id": "concept_1_material_电缆",
                    "parent_concept_name": "电缆",
                    "relation_kind": "concept_to_evidence",
                },
                "retrieval_path": "database",
            }
        ],
    )

    result = json.loads(
        tools.concept_search.func(
            "2026年1月，电缆价格较上月的变化幅度是多少？",
            top_k=3,
            include_evidence=True,
        )
    )

    assert len(result) == 2
    assert any(item["source_db"] == "concept_search" for item in result)
    assert any(item["metadata"].get("relation_kind") == "concept_to_evidence" for item in result)


def test_rrf_fuse_chunks_boosts_cross_route_hits() -> None:
    vector_hits = [
        {"chunk_id": "tc_1", "score": 0.61, "metadata": {}, "source_db": "hybrid_vector"},
        {"chunk_id": "tc_2", "score": 0.58, "metadata": {}, "source_db": "hybrid_vector"},
    ]
    text_hits = [
        {"chunk_id": "tc_2", "score": 0.09, "metadata": {}, "source_db": "hybrid_text"},
        {"chunk_id": "tc_3", "score": 0.08, "metadata": {}, "source_db": "hybrid_text"},
    ]

    fused = tools._rrf_fuse_chunks([vector_hits, text_hits], rank_constant=60)

    tc2 = next(item for item in fused if item["chunk_id"] == "tc_2")
    assert tc2["metadata"]["fusion_method"] == "rrf"
    assert tc2["metadata"]["rrf_hit_count"] == 2
    assert tc2["score"] > 0.58


def test_hybrid_runtime_config_reads_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("HYBRID_VECTOR_MIN_SCORE", "0.55")
    monkeypatch.setenv("HYBRID_VECTOR_FETCH_MULTIPLIER", "3")
    monkeypatch.setenv("HYBRID_TEXT_FETCH_MULTIPLIER", "2")
    monkeypatch.setenv("HYBRID_RRF_RANK_CONSTANT", "42")
    monkeypatch.setenv("HYBRID_STRUCTURED_TOP_K", "7")
    monkeypatch.setenv("HYBRID_LITERAL_TOP_K", "6")

    cfg = tools._get_hybrid_runtime_config(top_k=4)

    assert cfg["vector_min_score"] == 0.55
    assert cfg["vector_fetch_k"] == 12
    assert cfg["text_fetch_k"] == 8
    assert cfg["rrf_rank_constant"] == 42
    assert cfg["structured_top_k"] == 7
    assert cfg["literal_top_k"] == 6


def test_hybrid_search_applies_rrf_config_and_query_family(monkeypatch) -> None:
    captured = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params=None) -> None:
            self.query = query
            self.params = params

        def fetchall(self):
            if "to_tsvector('chinese', content)" in self.query:
                return [(1, "doc_x", 3, "趋势说明", 0.12)]
            return []

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def rollback(self):
            return None

    def fake_rrf(ranked_lists, rank_constant=60):
        captured["rank_constant"] = rank_constant
        return [
            {
                "chunk_id": "tc_1",
                "doc_id": "doc_x",
                "page_number": 3,
                "source_db": "hybrid_text",
                "content": "趋势说明",
                "score": 0.12,
                "metadata": {"rrf_score": 0.01},
                "retrieval_path": "database",
            }
        ]

    monkeypatch.setenv("HYBRID_RRF_RANK_CONSTANT", "88")
    monkeypatch.setattr(tools, "_get_embedding", lambda text: [])
    monkeypatch.setattr(tools, "_get_pg_conn", lambda: FakeConn())
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)
    monkeypatch.setattr(tools, "_rrf_fuse_chunks", fake_rrf)
    monkeypatch.setattr(tools, "_query_fee_formula_text_chunks", lambda conn, query, top_k=10: [])
    monkeypatch.setattr(tools, "_query_fee_comparison_text_chunks", lambda conn, query, top_k=10: [])
    monkeypatch.setattr(tools, "_query_appendix_standard_text_chunks", lambda conn, query, top_k=10: [])
    monkeypatch.setattr(tools, "_query_fill_requirement_text_chunks", lambda conn, query, top_k=10: [])
    monkeypatch.setattr(tools, "_query_text_chunks_literal", lambda conn, query, top_k=10: [])
    monkeypatch.setattr(tools, "_should_include_structured_tables", lambda query: False)

    result = json.loads(tools.hybrid_search.func("中砂从2026年1月到2月的价格走势如何？", top_k=3))

    assert captured["rank_constant"] == 88
    assert result[0]["metadata"]["query_family"] == "trend_chart"
    assert result[0]["metadata"]["hybrid_rank"] == 1


def test_extract_price_row_from_text_chunk_reads_cable_spec_price() -> None:
    content = (
        "SZCOST深圳建设工程价格信息 造价信息 ●建筑材料价格 （2025年12月价格） （续前） "
        "23 电力电缆 0.6/1kV YJV 4 × 95 m 385.02 "
        "24 电力电缆 0.6/1kv YJV 4 × 120 "
        "25 电力电缆 0.6/1kV YJV 5 × 4 m 22.99 "
        "33 电力电缆 0.6/1kV YJV 5×95 481.93 "
        "y 电力电缆 0.6/1kV YJV 5 × 120 m 605.73 "
        "35 电力电缆 0.6/1kV YJV 3x16+2×10 70.97"
    )

    parsed = tools._extract_price_row_from_text_chunk(
        content=content,
        material_name="电力电缆",
        specification="0.6/1KV YJV 5×120",
    )

    assert parsed == ("m", "605.73")


def test_query_price_text_fallback_returns_period_specific_chunk() -> None:
    page_row = (
        123,
        "SZCOST深圳建设工程价格信息 造价信息 ●建筑材料价格 （2025年12月价格） （续前） "
        "33 电力电缆 0.6/1kV YJV 5×95 481.93 "
        "y 电力电缆 0.6/1kV YJV 5 × 120 m 605.73",
    )

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params) -> None:
            self.query = query
            self.params = params

        def fetchall(self):
            if "SELECT DISTINCT doc_id, page_number" in self.query:
                return [("doc_pdf_c090df669c7e4abcb0c56fbb7f5d88cd", 36)]
            return [page_row]

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    results = tools._query_price_text_fallback(
        conn=FakeConn(),
        material_name="电力电缆",
        specification="0.6/1KV YJV 5×120",
        year_month="2025-12",
        top_k=3,
    )

    assert len(results) == 1
    assert results[0]["page_number"] == 36
    assert results[0]["metadata"]["price"] == "605.73"
    assert results[0]["metadata"]["year_month"] == "2025-12"
    assert results[0]["metadata"]["retrieval_path"] == "pdf_page"


def test_price_query_uses_text_fallback_when_price_records_miss(monkeypatch) -> None:
    class FakeCursor:
        def __init__(self) -> None:
            self.execute_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params=None) -> None:
            self.execute_calls += 1

        def fetchall(self):
            return []

    class FakeConn:
        def __init__(self) -> None:
            self.cursor_obj = FakeCursor()

        def cursor(self):
            return self.cursor_obj

    monkeypatch.setattr(tools, "_get_pg_conn", lambda: FakeConn())
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)
    monkeypatch.setattr(
        tools,
        "_query_price_text_fallback",
        lambda conn, material_name, specification, year_month, top_k=5: [
            {
                "chunk_id": "price_text_1",
                "doc_id": "doc_pdf_c090df669c7e4abcb0c56fbb7f5d88cd",
                "page_number": 36,
                "source_db": "text_price_fallback",
                "content": "电力电缆 0.6/1KV YJV 5×120 单位:m 价格:605.73元 期间:2025-12",
                "score": 0.84,
                "metadata": {"year_month": "2025-12", "unit": "m", "price": "605.73"},
            }
        ],
    )

    result = json.loads(
        tools.price_query.func(
            material_name="电力电缆",
            specification="0.6/1KV YJV 5×120",
            year_month="2025-12",
            top_k=3,
        )
    )

    assert result[0]["source_db"] == "text_price_fallback"
    assert result[0]["metadata"]["price"] == "605.73"


def test_extract_material_price_from_ocr_page_reads_middle_sand_row() -> None:
    raw_text = "白水泥\n923.00\n27\n中砂\nm\n194.00\n28\n碎石\n20 ~ 40\nm²\n180.00"

    parsed = tools._extract_material_price_from_ocr_page(raw_text, "中砂")

    assert parsed == ("m³", "194.00")


def test_price_query_uses_ocr_fallback_for_material_only(monkeypatch) -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params=None) -> None:
            self.query = query

        def fetchall(self):
            return []

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(tools, "_get_pg_conn", lambda: FakeConn())
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)
    monkeypatch.setattr(
        tools,
        "_query_material_ocr_fallback",
        lambda material_name, year_month: [
            {
                "chunk_id": "ocr_price_1",
                "doc_id": "doc_pdf_oct",
                "page_number": 14,
                "source_db": "ocr_price_fallback",
                "content": "中砂 单位:m³ 价格:194.00元 期间:2025-10",
                "score": 0.83,
                "metadata": {"year_month": "2025-10", "unit": "m³", "price": "194.00"},
            }
        ],
    )

    result = json.loads(
        tools.price_query.func(
            material_name="中砂",
            specification="",
            year_month="2025-10",
            top_k=3,
        )
    )

    assert result[0]["source_db"] == "ocr_price_fallback"
    assert result[0]["metadata"]["price"] == "194.00"


def test_query_material_text_fallback_returns_middle_sand_row() -> None:
    page_row = (
        321,
        "造价信息 ●建筑材料价格 (2026年1月价格) 中砂 m² 187.00 碎石 20 ~ 40 m 179.00",
    )

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params) -> None:
            self.query = query
            self.params = params

        def fetchall(self):
            if "SELECT DISTINCT doc_id, page_number" in self.query:
                return [("doc_pdf_202601", 19)]
            return [page_row]

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    results = tools._query_material_text_fallback(
        conn=FakeConn(),
        material_name="中砂",
        year_month="2026-01",
        top_k=2,
    )

    assert len(results) == 1
    assert results[0]["source_db"] == "text_material_fallback"
    assert results[0]["metadata"]["price"] == "187.00"
    assert results[0]["metadata"]["unit"] == "m³"
    assert results[0]["metadata"]["retrieval_path"] == "pdf_page"


def test_price_query_uses_text_fallback_for_material_only(monkeypatch) -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params=None) -> None:
            self.query = query

        def fetchall(self):
            return []

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(tools, "_get_pg_conn", lambda: FakeConn())
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)
    monkeypatch.setattr(
        tools,
        "_query_material_text_fallback",
        lambda conn, material_name, year_month, top_k=5: [
            {
                "chunk_id": "text_material_1",
                "doc_id": "doc_pdf_jan",
                "page_number": 19,
                "source_db": "text_material_fallback",
                "content": "中砂 单位:m³ 价格:187.00元 期间:2026-01",
                "score": 0.85,
                "metadata": {"year_month": "2026-01", "unit": "m³", "price": "187.00"},
            }
        ],
    )
    monkeypatch.setattr(tools, "_query_material_ocr_fallback", lambda material_name, year_month: [])

    result = json.loads(
        tools.price_query.func(
            material_name="中砂",
            specification="",
            year_month="2026-01",
            top_k=3,
        )
    )

    assert result[0]["source_db"] == "text_material_fallback"
    assert result[0]["metadata"]["price"] == "187.00"


def test_price_trend_fills_missing_months_from_ocr(monkeypatch) -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params) -> None:
            self.query = query

        def fetchall(self):
            return []

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    fallback_by_month = {
        "2025-10": [
            {
                "chunk_id": "ocr_oct",
                "doc_id": "doc_oct",
                "page_number": 14,
                "source_db": "ocr_price_fallback",
                "content": "中砂 单位:m³ 价格:194.00元 期间:2025-10",
                "score": 0.83,
                "metadata": {"year_month": "2025-10", "unit": "m³", "price": "194.00"},
            }
        ],
        "2025-11": [
            {
                "chunk_id": "ocr_nov",
                "doc_id": "doc_nov",
                "page_number": 12,
                "source_db": "ocr_price_fallback",
                "content": "中砂 单位:m³ 价格:194.00元 期间:2025-11",
                "score": 0.83,
                "metadata": {"year_month": "2025-11", "unit": "m³", "price": "194.00"},
            }
        ],
        "2025-12": [
            {
                "chunk_id": "ocr_dec",
                "doc_id": "doc_dec",
                "page_number": 21,
                "source_db": "ocr_price_fallback",
                "content": "中砂 单位:m³ 价格:192.00元 期间:2025-12",
                "score": 0.83,
                "metadata": {"year_month": "2025-12", "unit": "m³", "price": "192.00"},
            }
        ],
    }

    monkeypatch.setattr(tools, "_get_pg_conn", lambda: FakeConn())
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)
    monkeypatch.setattr(
        tools,
        "_query_material_ocr_fallback",
        lambda material_name, year_month: fallback_by_month.get(year_month, []),
    )

    result = json.loads(
        tools.price_trend.func(
            material_name="中砂",
            start_month="2025-10",
            end_month="2025-12",
        )
    )

    assert [item["metadata"]["year_month"] for item in result] == ["2025-10", "2025-11", "2025-12"]
    assert [item["metadata"]["avg_price"] for item in result] == [194.0, 194.0, 192.0]


def test_price_trend_prefers_text_fallback_before_ocr(monkeypatch) -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params) -> None:
            self.query = query

        def fetchall(self):
            return []

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(tools, "_get_pg_conn", lambda: FakeConn())
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)
    monkeypatch.setattr(
        tools,
        "_query_material_text_fallback",
        lambda conn, material_name, year_month, top_k=1: [
            {
                "chunk_id": f"text_{year_month}",
                "doc_id": "doc_jan",
                "page_number": 19,
                "source_db": "text_material_fallback",
                "content": f"中砂 单位:m³ 价格:187.00元 期间:{year_month}",
                "score": 0.85,
                "metadata": {
                    "year_month": year_month,
                    "unit": "m³",
                    "price": "187.00",
                    "retrieval_path": "pdf_page",
                    "evidence_kind": "pdf_page_table_row",
                    "route_stage": "secondary",
                },
            }
        ] if year_month == "2026-01" else [],
    )
    monkeypatch.setattr(
        tools,
        "_query_material_ocr_fallback",
        lambda material_name, year_month: [],
    )

    result = json.loads(
        tools.price_trend.func(
            material_name="中砂",
            start_month="2026-01",
            end_month="2026-01",
        )
    )

    assert len(result) == 1
    assert result[0]["source_db"] == "text_material_fallback"
    assert result[0]["metadata"]["avg_price"] == 187.0
    assert result[0]["metadata"]["retrieval_path"] == "pdf_page"


def test_price_trend_uses_trend_points_when_available(monkeypatch) -> None:
    class FakeConn:
        def cursor(self):
            raise AssertionError("cursor should not be used when trend points are mocked")

    monkeypatch.setattr(tools, "_get_pg_conn", lambda: FakeConn())
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)
    monkeypatch.setattr(
        tools,
        "_query_trend_points",
        lambda conn, material_name, start_month="", end_month="": [
            (11, "2026-01", 187.0, "m³", 19, "doc_jan", "中砂", None, None, None),
            (12, "2026-02", 189.0, "m³", 12, "doc_feb", "中砂", 2.0, 1.0695, "up"),
        ],
    )

    result = json.loads(
        tools.price_trend.func(
            material_name="中砂",
            start_month="2026-01",
            end_month="2026-02",
        )
    )

    assert [item["source_db"] for item in result] == ["trend_points", "trend_points"]
    assert result[1]["metadata"]["delta"] == 2.0
    assert result[1]["metadata"]["trend_direction"] == "up"
    assert result[0]["metadata"]["retrieval_path"] == "database"


def test_pdf_page_search_returns_pdf_route_metadata(monkeypatch) -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params=None) -> None:
            self.query = query
            self.params = params

        def fetchall(self):
            if "ORDER BY length(content)" in self.query:
                return [(51, "doc_pdf_rule", 8, "安全文明施工费计取基数为分部分项工程费与措施项目费。")]
            return []

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(tools, "_get_pg_conn", lambda: FakeConn())
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)

    result = json.loads(tools.pdf_page_search.func("安全文明施工费计取基数", top_k=3))

    assert len(result) == 1
    assert result[0]["source_db"] == "pdf_page"
    assert result[0]["metadata"]["retrieval_path"] == "pdf_page"


def test_price_query_supports_year_only_period(monkeypatch) -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params=None) -> None:
            self.query = query
            self.params = params

        def fetchall(self):
            if "SELECT DISTINCT year_month" in self.query:
                return []
            return [
                (
                    1,
                    "doc_pdf_year",
                    18,
                    "钛合金门窗 单位:m² 价格:880.00元 期间:2025-03 类别:门窗",
                    {"year_month": "2025-03"},
                    0.0,
                )
            ]

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(tools, "_get_pg_conn", lambda: FakeConn())
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)

    result = json.loads(
        tools.price_query.func(
            material_name="钛合金门窗",
            specification="",
            year_month="2025",
            top_k=3,
        )
    )

    assert result[0]["source_db"] == "price_records"
    assert "期间:2025-03" in result[0]["content"]
