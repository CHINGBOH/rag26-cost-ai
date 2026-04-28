import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.agent import tools


def test_topology_search_rewrites_anchor_and_evidence_routes(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr(tools, "_get_pg_conn", lambda: object())
    monkeypatch.setattr(tools, "_put_pg_conn", lambda conn: None)
    monkeypatch.setattr(
        tools,
        "_load_concept_hits",
        lambda conn, query, top_k=6: [
            {
                "chunk_id": "concept_graph_7",
                "doc_id": "doc-anchor",
                "page_number": 1,
                "source_db": "concept_graph",
                "content": "概念:企业管理费 类型:fee_item",
                "score": 0.93,
                "metadata": {
                    "concept_id": 7,
                    "concept_name": "企业管理费",
                    "concept_type": "fee_item",
                },
                "retrieval_path": "graph",
            }
        ],
    )

    def fake_expand(conn, query, concept_hits, top_k=2, recursive_depth=None):
        captured["recursive_depth"] = recursive_depth
        return [
            {
                "chunk_id": "fee_rates_11",
                "doc_id": "doc-fee",
                "page_number": 6,
                "source_db": "graph_fee_rates",
                "content": "企业管理费 推荐费率:5.20%",
                "score": 0.84,
                "metadata": {
                    "graph_depth": 2,
                    "parent_concept_id": "concept_graph_7",
                    "parent_concept_graph_id": 7,
                    "parent_concept_name": "企业管理费",
                    "parent_concept_type": "fee_item",
                },
                "retrieval_path": "database",
            }
        ]

    monkeypatch.setattr(tools, "_expand_concept_hits", fake_expand)

    result = json.loads(tools.topology_search.func("企业管理费如何计算", top_k=4, max_depth=2))

    assert captured["recursive_depth"] == 2
    assert result[0]["retrieval_path"] == "topology"
    assert result[0]["metadata"]["topology_role"] == "anchor"
    assert result[0]["metadata"]["stop_reason"] == "expanded"

    evidence = next(item for item in result if item["chunk_id"] == "fee_rates_11")
    assert evidence["retrieval_path"] == "topology"
    assert evidence["metadata"]["topology_role"] == "evidence"
    assert evidence["metadata"]["topology_depth"] == 2
    assert evidence["metadata"]["stop_reason"] == "max_depth_reached"