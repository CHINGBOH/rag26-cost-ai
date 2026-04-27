import importlib.util
import json
from pathlib import Path
import sys
import types


def _install_import_stubs() -> None:
    if "fastapi" not in sys.modules:
        fastapi = types.ModuleType("fastapi")

        class FakeFastAPI:
            def __init__(self, *args, **kwargs):
                pass

            def on_event(self, *args, **kwargs):
                def decorator(func):
                    return func

                return decorator

            def get(self, *args, **kwargs):
                def decorator(func):
                    return func

                return decorator

            post = get

        class FakeUploadFile:
            filename = "dummy.pdf"

        class FakeBackgroundTasks:
            def add_task(self, *args, **kwargs):
                return None

        class FakeHTTPException(Exception):
            def __init__(self, status_code: int, detail: str):
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail

        def fake_file(*args, **kwargs):
            return None

        fastapi.FastAPI = FakeFastAPI
        fastapi.File = fake_file
        fastapi.UploadFile = FakeUploadFile
        fastapi.HTTPException = FakeHTTPException
        fastapi.BackgroundTasks = FakeBackgroundTasks
        sys.modules["fastapi"] = fastapi

    if "pydantic" not in sys.modules:
        pydantic = types.ModuleType("pydantic")

        class FakeBaseModel:
            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)

            def model_dump(self):
                return self.__dict__.copy()

            @classmethod
            def model_validate_json(cls, value: str):
                return cls(**json.loads(value))

        pydantic.BaseModel = FakeBaseModel
        sys.modules["pydantic"] = pydantic

    if "fitz" not in sys.modules:
        fitz = types.ModuleType("fitz")

        class FakeMatrix:
            def __init__(self, *args, **kwargs):
                pass

        fitz.Matrix = FakeMatrix
        fitz.Page = object
        fitz.open = lambda *args, **kwargs: None
        sys.modules["fitz"] = fitz

    if "paddleocr" not in sys.modules:
        paddleocr = types.ModuleType("paddleocr")

        class DummyOCR:
            def __init__(self, *args, **kwargs):
                pass

            def ocr(self, *args, **kwargs):
                return [[]]

            def __call__(self, *args, **kwargs):
                return []

        paddleocr.PaddleOCR = DummyOCR
        paddleocr.PPStructure = DummyOCR
        sys.modules["paddleocr"] = paddleocr

    if "PIL" not in sys.modules or "PIL.Image" not in sys.modules:
        pil = types.ModuleType("PIL")
        image_module = types.ModuleType("PIL.Image")

        class DummyImageContext:
            size = (100, 100)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def resize(self, *args, **kwargs):
                return self

            def save(self, *args, **kwargs):
                return None

            def convert(self, *args, **kwargs):
                return self

        class DummyResampling:
            LANCZOS = 1

        image_module.open = lambda *args, **kwargs: DummyImageContext()
        image_module.Resampling = DummyResampling
        pil.Image = image_module
        sys.modules["PIL"] = pil
        sys.modules["PIL.Image"] = image_module

    if "numpy" not in sys.modules:
        numpy = types.ModuleType("numpy")
        numpy.array = lambda value: value
        sys.modules["numpy"] = numpy


_install_import_stubs()


MODULE_PATH = Path(__file__).resolve().parents[2] / "src/backend/ocr-service/ocr_service.py"
SPEC = importlib.util.spec_from_file_location("ocr_service_under_test", MODULE_PATH)
ocr_service = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(ocr_service)


def _make_text_block(text: str) -> object:
    return ocr_service.OCRTextBlock(
        text=text,
        confidence=1.0,
        bbox={"x": 0, "y": 0, "width": 10, "height": 10},
    )


def _make_native_page(raw_text: str) -> object:
    lines = [line for line in raw_text.splitlines() if line.strip()]
    return ocr_service.OCRPageResult(
        page_number=0,
        text_blocks=[_make_text_block(line) for line in lines],
        tables=[],
        figures=[],
        raw_text=raw_text,
        markdown=raw_text,
        confidence=1.0 if lines else 0.0,
    )


def test_build_native_page_result_from_text_dict_extracts_lines() -> None:
    text_dict = {
        "blocks": [
            {
                "type": 0,
                "lines": [
                    {"bbox": [0, 0, 20, 10], "spans": [{"text": "第一行标题"}]},
                    {"bbox": [0, 12, 40, 22], "spans": [{"text": "第二行内容"}]},
                ],
            }
        ]
    }

    page = ocr_service._build_native_page_result_from_text_dict(text_dict)

    assert page.raw_text == "第一行标题\n第二行内容"
    assert len(page.text_blocks) == 2
    assert page.text_blocks[0].text == "第一行标题"
    assert page.confidence == 1.0


def test_should_skip_ocr_for_narrative_native_page() -> None:
    raw_text = "\n".join(
        [
            "深圳市建设工程计价费率标准（2025）",
            "一、总则",
            "根据有关文件规定，结合我市工程实际，组织编制本费率标准。",
            "采用深圳市消耗量标准、价格信息作为计价依据的建设工程，应按本费率标准执行。",
        ]
    )
    native_page = _make_native_page(raw_text)

    assert ocr_service._should_skip_ocr_for_native_page(native_page, embedded_image_coverage=0.0) is True


def test_should_skip_ocr_for_narrative_page_with_small_embedded_image() -> None:
    raw_text = "\n".join(
        [
            "深圳市建设工程计价费率标准（2025）",
            "一、总则",
            "根据有关文件规定，结合我市工程实际，组织编制本费率标准。",
            "采用深圳市消耗量标准、价格信息作为计价依据的建设工程，应按本费率标准执行。",
        ]
    )
    native_page = _make_native_page(raw_text)

    assert ocr_service._should_skip_ocr_for_native_page(native_page, embedded_image_coverage=0.08) is True


def test_should_not_skip_ocr_for_image_heavy_narrative_page() -> None:
    raw_text = "\n".join(
        [
            "深圳市建设工程计价费率标准（2025）",
            "一、总则",
            "根据有关文件规定，结合我市工程实际，组织编制本费率标准。",
            "采用深圳市消耗量标准、价格信息作为计价依据的建设工程，应按本费率标准执行。",
        ]
    )
    native_page = _make_native_page(raw_text)

    assert ocr_service._should_skip_ocr_for_native_page(native_page, embedded_image_coverage=0.52) is False


def test_should_not_skip_ocr_for_structured_native_page() -> None:
    raw_text = "\n".join(
        [
            "序号 项目编码 项目名称 计量单位 计算规则",
            "1 A001 装配式钢结构围挡 项 按项计价",
            "2 A002 PVC围挡 m 按围挡长度以米计算",
            "3 A003 铁马 项 按项计价",
            "4 A004 水马 项 按项计价",
            "5 A005 施工废弃物外运和处置 t 按质量以吨计算",
        ]
    )
    native_page = _make_native_page(raw_text)

    assert ocr_service._looks_like_structured_native_page(raw_text) is True
    assert ocr_service._should_skip_ocr_for_native_page(native_page, embedded_image_coverage=0.0) is False


def test_get_embedded_image_stats_uses_image_block_coverage() -> None:
    class DummyRect:
        width = 100
        height = 200

    class DummyPage:
        rect = DummyRect()

    has_images, coverage = ocr_service._get_embedded_image_stats(
        DummyPage(),
        text_dict={
            "blocks": [
                {"type": 0, "bbox": [0, 0, 50, 50]},
                {"type": 1, "bbox": [0, 0, 50, 100]},
                {"type": 1, "bbox": [50, 100, 100, 200]},
            ]
        },
    )

    assert has_images is True
    assert coverage == 0.5


def test_merge_native_text_with_ocr_page_preserves_structured_payload() -> None:
    native_page = _make_native_page(
        "送配电装置系统调试适用于10kV以下送配电回路。\n按系统为单位计算。\n不包括配电箱至电动机回路。\n"
        "调试内容应包括相关系统试运行。"
    )
    ocr_page = ocr_service.OCRPageResult(
        page_number=0,
        text_blocks=[_make_text_block("OCR 噪声文本")],
        tables=[
            ocr_service.OCRTable(
                html="<table><tr><td>序号</td><td>项目名称</td></tr></table>",
                markdown="| 序号 | 项目名称 |\n| --- | --- |",
                cells=[],
            )
        ],
        figures=[
            ocr_service.OCRFigure(
                bbox={"x": 0, "y": 0, "width": 100, "height": 100},
                region_type="figure",
                text_in_region="图例",
                confidence=0.88,
            )
        ],
        raw_text="OCR 噪声文本",
        markdown="OCR 噪声文本",
        confidence=0.66,
    )

    merged = ocr_service._merge_native_text_with_ocr_page(native_page, ocr_page)

    assert merged.raw_text == native_page.raw_text
    assert merged.text_blocks[0].text == "送配电装置系统调试适用于10kV以下送配电回路。"
    assert merged.tables == ocr_page.tables
    assert merged.figures == ocr_page.figures


def test_should_trigger_second_pass_for_weak_sparse_ocr() -> None:
    weak_page = ocr_service.OCRPageResult(
        page_number=0,
        text_blocks=[_make_text_block("模糊")],
        tables=[],
        figures=[],
        raw_text="模糊",
        markdown="模糊",
        confidence=0.41,
    )

    assert ocr_service._should_trigger_second_pass(weak_page) is True


def test_build_document_route_metrics_counts_strategies() -> None:
    native_page = _make_native_page("原生正文\n第二段正文\n第三段正文\n第四段正文")
    native_page.route_info = {
        "strategy": "native",
        "reason": "strong_native_text",
        "ocr_attempts": 0,
        "used_second_pass": False,
    }
    ocr_page = _make_native_page("OCR 页面")
    ocr_page.route_info = {
        "strategy": "ocr",
        "reason": "weak_native_text",
        "ocr_attempts": 2,
        "used_second_pass": True,
    }
    hybrid_page = _make_native_page("混合页面")
    hybrid_page.route_info = {
        "strategy": "hybrid",
        "reason": "structured_native_page",
        "ocr_attempts": 1,
        "used_second_pass": False,
    }

    metrics = ocr_service._build_document_route_metrics([native_page, ocr_page, hybrid_page])

    assert metrics == {
        "native_pages": 1,
        "ocr_pages": 1,
        "hybrid_pages": 1,
        "second_pass_pages": 1,
        "total_ocr_attempts": 3,
        "total_pages": 3,
    }


def test_process_pdf_page_with_routing_uses_second_pass_and_keeps_better_result() -> None:
    class DummyPage:
        pass

    page = DummyPage()
    weak_native_page = ocr_service.OCRPageResult(
        page_number=0,
        text_blocks=[],
        tables=[],
        figures=[],
        raw_text="",
        markdown="",
        confidence=0.0,
    )
    first_ocr_page = ocr_service.OCRPageResult(
        page_number=0,
        text_blocks=[_make_text_block("模糊")],
        tables=[],
        figures=[],
        raw_text="模糊",
        markdown="模糊",
        confidence=0.36,
    )
    retry_ocr_page = ocr_service.OCRPageResult(
        page_number=0,
        text_blocks=[_make_text_block("二次识别后的更清晰文本")],
        tables=[],
        figures=[],
        raw_text="二次识别后的更清晰文本",
        markdown="二次识别后的更清晰文本",
        confidence=0.91,
    )

    render_calls = []
    original_extract = ocr_service._extract_native_page_result
    original_image_stats = ocr_service._get_embedded_image_stats
    original_render = ocr_service._render_pdf_page_to_image
    original_run_ocr = ocr_service._run_ocr_on_image
    try:
        ocr_service._extract_native_page_result = lambda page_obj: weak_native_page
        ocr_service._get_embedded_image_stats = lambda page_obj, text_dict=None: (False, 0.0)

        def fake_render(page_obj, output_dir, page_number, max_width_pixels=ocr_service.MAX_WIDTH_PIXELS, suffix=""):
            render_calls.append((page_number, max_width_pixels, suffix))
            return f"/tmp/page_{page_number}_{max_width_pixels}{suffix}.jpg"

        def fake_run_ocr(image_path, serialize_ocr=False):
            if "_retry" in image_path:
                return retry_ocr_page
            return first_ocr_page

        ocr_service._render_pdf_page_to_image = fake_render
        ocr_service._run_ocr_on_image = fake_run_ocr

        page_result = ocr_service._process_pdf_page_with_routing(
            page,
            "/tmp",
            7,
            serialize_ocr=False,
        )
    finally:
        ocr_service._extract_native_page_result = original_extract
        ocr_service._get_embedded_image_stats = original_image_stats
        ocr_service._render_pdf_page_to_image = original_render
        ocr_service._run_ocr_on_image = original_run_ocr

    assert [call[1] for call in render_calls] == [ocr_service.MAX_WIDTH_PIXELS, ocr_service.SECOND_PASS_WIDTH_PIXELS]
    assert page_result.page_number == 7
    assert page_result.raw_text == "二次识别后的更清晰文本"
    assert page_result.route_info["strategy"] == "ocr"
    assert page_result.route_info["ocr_attempts"] == 2
    assert page_result.route_info["used_second_pass"] is True
    assert page_result.route_info["embedded_image_coverage"] == 0.0
