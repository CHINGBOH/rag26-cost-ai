import importlib.util
from pathlib import Path
import sys
import types


def _install_import_stubs() -> None:
    if "requests" not in sys.modules:
        requests = types.ModuleType("requests")
        requests.get = lambda *args, **kwargs: None
        requests.post = lambda *args, **kwargs: None
        sys.modules["requests"] = requests


_install_import_stubs()


MODULE_PATH = Path(__file__).resolve().parents[2] / "ocr_tools/batch_scan.py"
SPEC = importlib.util.spec_from_file_location("batch_scan_under_test", MODULE_PATH)
batch_scan = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(batch_scan)


def test_extract_route_metrics_prefers_document_summary() -> None:
    result = {
        "route_metrics": {
            "native_pages": 3,
            "ocr_pages": 5,
            "hybrid_pages": 2,
            "second_pass_pages": 1,
            "total_ocr_attempts": 8,
            "total_pages": 10,
        },
        "pages": [
            {"route_info": {"strategy": "native", "ocr_attempts": 0, "used_second_pass": False}},
        ],
    }

    metrics = batch_scan.extract_route_metrics(result)

    assert metrics == {
        "native_pages": 3,
        "ocr_pages": 5,
        "hybrid_pages": 2,
        "second_pass_pages": 1,
        "total_ocr_attempts": 8,
        "total_pages": 10,
        "known_pages": 10,
    }


def test_extract_route_metrics_falls_back_to_page_route_info() -> None:
    result = {
        "pages": [
            {"route_info": {"strategy": "native", "ocr_attempts": 0, "used_second_pass": False}},
            {"route_info": {"strategy": "ocr", "ocr_attempts": 2, "used_second_pass": True}},
            {"route_info": {"strategy": "hybrid", "ocr_attempts": 1, "used_second_pass": False}},
            {},
        ]
    }

    metrics = batch_scan.extract_route_metrics(result)

    assert metrics == {
        "native_pages": 1,
        "ocr_pages": 1,
        "hybrid_pages": 1,
        "second_pass_pages": 1,
        "total_ocr_attempts": 3,
        "total_pages": 4,
        "known_pages": 3,
    }


def test_summarize_state_aggregates_route_ratios() -> None:
    pdfs = [Path("/tmp/a.pdf"), Path("/tmp/b.pdf"), Path("/tmp/c.pdf")]
    state = {
        str(pdfs[0]): {
            "status": "done",
            "route_metrics": {
                "native_pages": 2,
                "ocr_pages": 1,
                "hybrid_pages": 1,
                "second_pass_pages": 1,
                "total_ocr_attempts": 3,
                "total_pages": 4,
                "known_pages": 4,
            },
        },
        str(pdfs[1]): {
            "status": "done",
            "route_metrics": {
                "native_pages": 1,
                "ocr_pages": 3,
                "hybrid_pages": 0,
                "second_pass_pages": 2,
                "total_ocr_attempts": 5,
                "total_pages": 4,
                "known_pages": 4,
            },
        },
        str(pdfs[2]): {"status": "error", "error": "boom"},
    }

    summary = batch_scan.summarize_state(state, pdfs)

    assert summary["files"] == {
        "total": 3,
        "done": 2,
        "error": 1,
        "todo": 0,
        "files_with_route_metrics": 2,
    }
    assert summary["route_metrics"] == {
        "native_pages": 3,
        "ocr_pages": 4,
        "hybrid_pages": 1,
        "second_pass_pages": 3,
        "total_ocr_attempts": 8,
        "total_pages": 8,
        "known_pages": 8,
    }
    assert summary["route_ratios"] == {
        "native_ratio": 0.375,
        "ocr_ratio": 0.5,
        "hybrid_ratio": 0.125,
    }