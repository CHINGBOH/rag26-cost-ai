import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import router
import app.agent.graph as graph_module


def _parse_sse_events(payload: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in payload.split("\n\n"):
        if not block.strip():
            continue
        event_name = ""
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data_lines.append(line[len("data: "):])
        if event_name and data_lines:
            events.append((event_name, json.loads("\n".join(data_lines))))
    return events


def test_stream_endpoint_uses_presentation_policy_node_payload(monkeypatch):
    class FakeGraph:
        def stream(self, initial_state, config=None):
            yield {
                "query_analysis": {
                    "query_type": "standard_ref",
                    "sub_queries": [],
                    "query_entities": {},
                }
            }
            yield {
                "synthesize_node": {
                    "synthesis_prompt": "",
                    "evaluation": {},
                    "llm_runtime": {},
                    "citations_text": "",
                    "retrieved_chunks": [],
                    "presentation": {
                        "type": "answer_sections",
                        "query_type": "standard_ref",
                        "title": "规则说明",
                        "summary": "机械费为0时基数为人工费。",
                        "highlights": [{"kind": "rule", "value": "企业管理费基数=(人工费+机械费×0.1)"}],
                        "sections": [{"kind": "analysis", "body": "条文公式可直接代入。"}],
                        "sources": [],
                    },
                }
            }
            yield {
                "presentation_policy_node": {
                    "presentation": {
                        "type": "answer_sections",
                        "query_type": "standard_ref",
                        "title": "规则说明",
                        "summary": "机械费为0时基数为人工费。",
                        "support_kicker": "公式依据",
                        "highlights": [{"kind": "rule", "label": "公式要点", "value": "企业管理费基数=(人工费+机械费×0.1)"}],
                        "sections": [{"kind": "analysis", "label": "公式依据", "body": "条文公式可直接代入。"}],
                        "sources": [],
                    },
                    "presentation_policy": {
                        "support_kicker": "公式依据",
                        "section_labels": {"analysis": "公式依据"},
                        "highlight_labels": {"rule": "公式要点"},
                    },
                }
            }

    monkeypatch.setattr(graph_module, "get_agent_graph", lambda: FakeGraph())

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.post(
        "/api/v1/agent/stream",
        json={"query": "2025版机械费为0时企业管理费基数是什么", "max_iterations": 2},
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    presentation_events = [data for event, data in events if event == "presentation"]
    done_events = [data for event, data in events if event == "done"]

    assert presentation_events
    assert any(item.get("support_kicker") == "公式依据" for item in presentation_events)
    assert done_events
    assert done_events[-1]["presentation"]["support_kicker"] == "公式依据"
    assert done_events[-1]["presentation"]["sections"][0]["label"] == "公式依据"

