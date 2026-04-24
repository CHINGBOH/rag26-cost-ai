import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.agent import tools


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
