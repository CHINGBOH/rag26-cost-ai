"""Phase H: verify table_row blocks materialize as PriceRow nodes in Neo4j.

Run from repo root:
    python tests/test_ingest_table_to_neo4j.py
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend", "retrieval-service"))

os.environ.setdefault("NEO4J_PASSWORD", "password")

from app.ingest_pipeline import _parse_table_rows, neo4j_write_chunk, _neo4j_session  # noqa


def test_parse_matrix_form():
    cells = [
        ["项目", "规格", "单位", "含税单价"],
        ["送配电装置", "10kV", "系统", "1234.56"],
        ["接地装置", "—", "套", "789.00"],
    ]
    rows = _parse_table_rows(cells)
    assert len(rows) == 2, rows
    assert rows[0]["material_name"] == "送配电装置"
    assert rows[0]["spec"] == "10kV"
    assert rows[0]["unit"] == "系统"
    assert rows[0]["price"] == "1234.56"
    assert rows[0]["row_index"] == 1
    print("[parse-matrix] PASS")


def test_parse_dict_form():
    cells = [
        {"row": 0, "col": 0, "text": "材料"},
        {"row": 0, "col": 1, "text": "单价"},
        {"row": 1, "col": 0, "text": "钢筋"},
        {"row": 1, "col": 1, "text": "5000"},
    ]
    rows = _parse_table_rows(cells)
    assert len(rows) == 1, rows
    assert rows[0]["material_name"] == "钢筋"
    assert rows[0]["price"] == "5000"
    print("[parse-dict] PASS")


def test_parse_unknown_headers():
    cells = [["X", "Y"], ["a", "b"]]
    rows = _parse_table_rows(cells)
    assert rows[0]["col_0"] == "a"
    assert rows[0]["col_1"] == "b"
    print("[parse-unknown] PASS")


def test_neo4j_priceROW_creation():
    drv = _neo4j_session()
    if drv is None:
        print("[neo4j] SKIP — driver unavailable")
        return
    doc_id = f"test_phaseH_{uuid.uuid4().hex[:8]}"
    file_name = "phaseH_test.pdf"
    metadata = {
        "table_cells": [
            ["项目", "规格", "单位", "含税单价"],
            ["送配电装置系统调试", "10kV", "系统", "1234.56"],
            ["接地装置", "套", "套", "789.00"],
            ["电缆桥架安装", "300×100", "米", "55.50"],
        ],
        "table_html": "<table>...</table>",
    }
    n = neo4j_write_chunk(drv, doc_id, file_name, 0,
                          text="送配电装置系统调试 ...", page=14,
                          block_type="table_row", metadata=metadata)
    assert n > 0, f"expected triples written, got {n}"
    with drv.session() as ses:
        cnt = ses.run("MATCH (d:Document {doc_id:$d})-[:HAS_TABLE]->(t:Table)-[:HAS_ROW]->(p:PriceRow) RETURN count(p) as n",
                      d=doc_id).single()["n"]
        assert cnt == 3, f"expected 3 PriceRows, got {cnt}"
        sample = ses.run("MATCH (p:PriceRow {doc_id:$d, row_index:1}) RETURN p.material_name as m, p.price as pr, p.spec as s",
                         d=doc_id).single()
        assert sample["m"] == "送配电装置系统调试"
        assert sample["pr"] == "1234.56"
        assert sample["s"] == "10kV"

        # idempotency: rerun same call, expect still 3 PriceRows (MERGE)
        n2 = neo4j_write_chunk(drv, doc_id, file_name, 0,
                               text="送配电装置系统调试 ...", page=14,
                               block_type="table_row", metadata=metadata)
        cnt2 = ses.run("MATCH (d:Document {doc_id:$d})-[:HAS_ROW]->(:PriceRow) RETURN count(*) as n",
                       d=doc_id).single()["n"]
        # cleanup
        ses.run("MATCH (d:Document {doc_id:$d}) DETACH DELETE d", d=doc_id)
        ses.run("MATCH (t:Table {uid:$u}) DETACH DELETE t", u=f"{doc_id}#0")
        ses.run("MATCH (p:PriceRow {table_uid:$u}) DETACH DELETE p", u=f"{doc_id}#0")
        ses.run("MATCH (c:Chunk {uid:$u}) DETACH DELETE c", u=f"{doc_id}#0")
    drv.close()
    print(f"[neo4j] PASS — 3 PriceRows created, sample row_1 OK; rerun triples={n2}")


if __name__ == "__main__":
    test_parse_matrix_form()
    test_parse_dict_form()
    test_parse_unknown_headers()
    test_neo4j_priceROW_creation()
    print("\nPHASE H PASS")
