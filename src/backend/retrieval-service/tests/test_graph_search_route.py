import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.agent import tools


def test_graph_search_reuses_concept_route_with_graph_path(monkeypatch) -> None:
    class FakeConn:
        pass

    monkeypatch.setattr(tools, "_get_pg_conn", lambda: FakeConn())
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)
    monkeypatch.setattr(
        tools,
        "_load_concept_hits",
        lambda conn, query, top_k=6: [
            {
                "chunk_id": "concept_1_rule_企业管理费",
                "doc_id": "doc_fee_2025",
                "page_number": 6,
                "source_db": "concept_search",
                "content": "概念:企业管理费 类型:rule_item 建议下钻:text_search",
                "score": 0.93,
                "metadata": {
                    "concept_name": "企业管理费",
                    "concept_type": "rule_item",
                    "preferred_tool": "text_search",
                },
                "retrieval_path": "database",
            }
        ],
    )
    monkeypatch.setattr(tools, "_expand_concept_hits", lambda conn, query, concept_hits, top_k=3: [])

    result = json.loads(tools.graph_search.func("企业管理费如何计算", top_k=3))

    assert len(result) == 1
    assert result[0]["source_db"] == "concept_search"
    assert result[0]["retrieval_path"] == "graph"
    assert result[0]["metadata"]["graph_entry_query"] == "企业管理费如何计算"