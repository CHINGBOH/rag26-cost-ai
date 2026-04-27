"""
OCR Service - FastAPI Implementation
Standalone OCR microservice using PaddleOCR + PPStructure
Supports: PDF (sync + async), images (jpg/png/tiff/bmp/webp/etc.)
"""

import os
import tempfile
import shutil
import asyncio
import time
import uuid
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from pydantic import BaseModel
import fitz  # PyMuPDF

# OCR and Structure imports
try:
    from paddleocr import PaddleOCR
    from PIL import Image
    import numpy as np

    try:
        from paddleocr import PPStructure
    except ImportError:
        PPStructure = None
        print("WARNING: PPStructure not available, table detection disabled.")

    PADDLE_AVAILABLE = True
except ImportError as e:
    PADDLE_AVAILABLE = False
    print(f"WARNING: PaddleOCR not available: {e}")

# Configuration constants
MAX_FILE_SIZE = 2048 * 1024 * 1024         # 2GB
MAX_PAGES_SYNC = 30                        # sync endpoint page limit
MAX_PAGES_TOTAL = 1000                     # hard limit
MAX_IMAGE_DIMENSION = 4000                 # px, resize if larger
MAX_WIDTH_PIXELS = 1200                    # px, controls PDF render DPI (lower = less GPU memory)
OCR_WORKERS = 1                            # thread pool size for blocking OCR (GPU is NOT thread-safe)
SECOND_PASS_WIDTH_PIXELS = 1800            # wider rerender for weak OCR pages
SECOND_PASS_CONFIDENCE = 0.72              # retry when OCR confidence is below this threshold
SECOND_PASS_MIN_TEXT_CHARS = 48            # retry when OCR text is too sparse to trust
NATIVE_TEXT_MIN_CHARS = 60                 # minimum non-whitespace chars before trusting embedded PDF text
NATIVE_TEXT_MIN_BLOCKS = 4                 # minimum line blocks before skipping OCR
IMAGE_HEAVY_PAGE_COVERAGE = 0.35           # only image-heavy pages should block native-text fast path
STRUCTURED_PAGE_KEYWORDS = (
    "序号",
    "项目编码",
    "项目名称",
    "材料名称",
    "规格",
    "型号",
    "单位",
    "价格",
    "单价",
    "费率",
    "推荐费率",
    "参考范围",
    "计算规则",
    "工作内容",
)

# Persistent output dirs (Docker-friendly via env vars)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.environ.get("OCR_OUTPUT_DIR", os.path.join(BASE_DIR, "ocr_outputs"))
TEMP_JOB_DIR = os.path.join(OUTPUT_DIR, "_jobs")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_JOB_DIR, exist_ok=True)

app = FastAPI(title="RAG OCR Service", version="2.1.0")

# Thread pool for CPU-heavy OCR tasks
_ocr_executor = ThreadPoolExecutor(max_workers=OCR_WORKERS)

# GPU lock - Paddle GPU context is not thread-safe
_gpu_lock = threading.Lock()

# In-memory job registry (job_id -> status dict)
_job_registry = {}

# Global OCR engines
ocr_engine: Optional[PaddleOCR] = None
table_engine: Optional[PPStructure] = None


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class OCRTextBlock(BaseModel):
    text: str
    confidence: float
    bbox: dict


class OCRTableCell(BaseModel):
    row: int
    col: int
    text: str
    bbox: dict


class OCRTable(BaseModel):
    html: Optional[str]
    markdown: Optional[str]
    cells: List[OCRTableCell]


class OCRFigure(BaseModel):
    """Detected chart / figure region with OCR-extracted text labels."""
    bbox: dict
    region_type: str          # 'figure', 'chart', 'diagram', 'formula', etc.
    text_in_region: str       # All text found inside the figure bounding box
    confidence: float


class OCRPageResult(BaseModel):
    page_number: int
    text_blocks: List[OCRTextBlock]
    tables: List[OCRTable]
    figures: List[OCRFigure]  # chart / trend-graph regions
    raw_text: str
    markdown: str
    confidence: float
    route_info: Optional[dict] = None


class OCRDocumentResult(BaseModel):
    document_id: str
    file_name: str
    total_pages: int
    pages: List[OCRPageResult]
    full_text: str
    processing_time: float
    route_metrics: Optional[dict] = None


class AsyncJobResponse(BaseModel):
    job_id: str
    status: str


class AsyncJobStatus(BaseModel):
    job_id: str
    status: str
    progress: dict
    result: Optional[OCRDocumentResult] = None
    error: Optional[str] = None


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _build_native_page_result_from_text_dict(text_dict: dict) -> OCRPageResult:
    text_blocks: List[OCRTextBlock] = []
    lines: List[str] = []

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text_parts = []
            for span in line.get("spans", []):
                span_text = str(span.get("text") or "")
                if span_text.strip():
                    text_parts.append(span_text)
            if not text_parts:
                continue

            line_text = "".join(text_parts).strip()
            if not line_text:
                continue

            line_bbox = line.get("bbox") or block.get("bbox") or [0, 0, 0, 0]
            x0, y0, x1, y1 = [float(v) for v in line_bbox[:4]]
            text_blocks.append(
                OCRTextBlock(
                    text=line_text,
                    confidence=1.0,
                    bbox={
                        "x": x0,
                        "y": y0,
                        "width": max(0.0, x1 - x0),
                        "height": max(0.0, y1 - y0),
                    },
                )
            )
            lines.append(line_text)

    raw_text = "\n".join(lines).strip()
    return OCRPageResult(
        page_number=0,
        text_blocks=text_blocks,
        tables=[],
        figures=[],
        raw_text=raw_text,
        markdown=raw_text,
        confidence=1.0 if text_blocks else 0.0,
    )


def _get_page_text_dict(page: fitz.Page) -> dict:
    try:
        return page.get_text("dict")
    except Exception:
        return {}


def _extract_native_page_result(page: fitz.Page) -> OCRPageResult:
    return _build_native_page_result_from_text_dict(_get_page_text_dict(page))


def _is_strong_native_text(raw_text: str, block_count: int) -> bool:
    return len(_compact_text(raw_text)) >= NATIVE_TEXT_MIN_CHARS and block_count >= NATIVE_TEXT_MIN_BLOCKS


def _looks_like_structured_native_page(raw_text: str) -> bool:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return False

    keyword_hits = sum(1 for keyword in STRUCTURED_PAGE_KEYWORDS if keyword in raw_text)
    short_lines = sum(1 for line in lines if len(_compact_text(line)) <= 12)
    numeric_lines = sum(1 for line in lines if sum(ch.isdigit() for ch in line) >= 3)

    return keyword_hits >= 4 or (keyword_hits >= 2 and len(lines) >= 8) or (
        len(lines) >= 12 and short_lines >= 8 and numeric_lines >= 5
    )


def _get_embedded_image_stats(page: fitz.Page, text_dict: Optional[dict] = None) -> tuple[bool, float]:
    if text_dict is None:
        text_dict = _get_page_text_dict(page)

    try:
        page_area = float(page.rect.width) * float(page.rect.height)
    except Exception:
        page_area = 0.0

    if page_area <= 0:
        return False, 0.0

    total_image_area = 0.0
    has_images = False
    for block in text_dict.get("blocks", []):
        if block.get("type") != 1:
            continue

        bbox = block.get("bbox") or [0, 0, 0, 0]
        if len(bbox) < 4:
            continue

        x0, y0, x1, y1 = [float(v) for v in bbox[:4]]
        image_area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        if image_area <= 0:
            continue

        has_images = True
        total_image_area += image_area

    coverage = min(1.0, total_image_area / page_area) if has_images else 0.0
    return has_images, coverage


def _should_skip_ocr_for_native_page(native_page: OCRPageResult, embedded_image_coverage: float) -> bool:
    if not _is_strong_native_text(native_page.raw_text, len(native_page.text_blocks)):
        return False
    if embedded_image_coverage >= IMAGE_HEAVY_PAGE_COVERAGE:
        return False
    if _looks_like_structured_native_page(native_page.raw_text):
        return False
    return True


def _should_overlay_native_text(native_page: OCRPageResult) -> bool:
    return _is_strong_native_text(native_page.raw_text, len(native_page.text_blocks))


def _merge_native_text_with_ocr_page(native_page: OCRPageResult, ocr_page: OCRPageResult) -> OCRPageResult:
    if not _should_overlay_native_text(native_page):
        return ocr_page

    return OCRPageResult(
        page_number=ocr_page.page_number,
        text_blocks=native_page.text_blocks,
        tables=ocr_page.tables,
        figures=ocr_page.figures,
        raw_text=native_page.raw_text,
        markdown=native_page.markdown,
        confidence=max(native_page.confidence, ocr_page.confidence),
    )


def _render_pdf_page_to_image(
    page: fitz.Page,
    output_dir: str,
    page_number: int,
    max_width_pixels: int = MAX_WIDTH_PIXELS,
    suffix: str = "",
) -> str:
    page_rect = page.rect
    page_width_pt = page_rect.width
    target_dpi = min(300, int(max_width_pixels / page_width_pt * 72))

    mat = fitz.Matrix(target_dpi / 72, target_dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    image_path = os.path.join(output_dir, f"page_{page_number:04d}{suffix}.jpg")
    pix.save(image_path)
    return image_path


def _run_ocr_on_image(image_path: str, serialize_ocr: bool = False) -> OCRPageResult:
    if serialize_ocr:
        with _gpu_lock:
            return _process_image_sync(image_path)
    return _process_image_sync(image_path)


def _score_ocr_page_result(page_result: OCRPageResult) -> tuple[int, float, int, int, int]:
    return (
        len(page_result.tables) + len(page_result.figures),
        page_result.confidence,
        len(_compact_text(page_result.raw_text)),
        len(page_result.text_blocks),
        len(page_result.markdown or ""),
    )


def _should_trigger_second_pass(ocr_page: OCRPageResult) -> bool:
    if ocr_page.tables or ocr_page.figures:
        return False
    if ocr_page.confidence >= SECOND_PASS_CONFIDENCE:
        return False
    return len(_compact_text(ocr_page.raw_text)) < SECOND_PASS_MIN_TEXT_CHARS


def _build_page_route_info(
    *,
    strategy: str,
    reason: str,
    native_page: OCRPageResult,
    has_embedded_images: bool,
    embedded_image_coverage: float,
    ocr_attempts: int,
    used_second_pass: bool,
) -> dict:
    return {
        "strategy": strategy,
        "reason": reason,
        "native_text_chars": len(_compact_text(native_page.raw_text)),
        "native_text_blocks": len(native_page.text_blocks),
        "has_embedded_images": has_embedded_images,
        "embedded_image_coverage": round(embedded_image_coverage, 4),
        "ocr_attempts": ocr_attempts,
        "used_second_pass": used_second_pass,
    }


def _build_document_route_metrics(pages: List[OCRPageResult]) -> dict:
    metrics = {
        "native_pages": 0,
        "ocr_pages": 0,
        "hybrid_pages": 0,
        "second_pass_pages": 0,
        "total_ocr_attempts": 0,
    }

    for page in pages:
        route_info = page.route_info or {}
        strategy = route_info.get("strategy")
        if strategy == "native":
            metrics["native_pages"] += 1
        elif strategy == "hybrid":
            metrics["hybrid_pages"] += 1
        else:
            metrics["ocr_pages"] += 1

        attempts = int(route_info.get("ocr_attempts") or 0)
        metrics["total_ocr_attempts"] += attempts
        if route_info.get("used_second_pass"):
            metrics["second_pass_pages"] += 1

    metrics["total_pages"] = len(pages)
    return metrics


def _process_pdf_page_with_routing(
    page: fitz.Page,
    output_dir: str,
    page_number: int,
    *,
    serialize_ocr: bool,
) -> OCRPageResult:
    text_dict = _get_page_text_dict(page)
    native_page = _build_native_page_result_from_text_dict(text_dict)
    has_embedded_images, embedded_image_coverage = _get_embedded_image_stats(page, text_dict=text_dict)

    if _should_skip_ocr_for_native_page(native_page, embedded_image_coverage):
        native_page.page_number = page_number
        native_page.route_info = _build_page_route_info(
            strategy="native",
            reason="strong_native_text",
            native_page=native_page,
            has_embedded_images=has_embedded_images,
            embedded_image_coverage=embedded_image_coverage,
            ocr_attempts=0,
            used_second_pass=False,
        )
        return native_page

    route_reason = "weak_native_text"
    if embedded_image_coverage >= IMAGE_HEAVY_PAGE_COVERAGE:
        route_reason = "embedded_images"
    elif _looks_like_structured_native_page(native_page.raw_text):
        route_reason = "structured_native_page"

    image_path = _render_pdf_page_to_image(page, output_dir, page_number)
    first_ocr_page = _run_ocr_on_image(image_path, serialize_ocr=serialize_ocr)
    selected_ocr_page = first_ocr_page
    attempts = 1
    used_second_pass = False

    if _should_trigger_second_pass(first_ocr_page):
        retry_image_path = _render_pdf_page_to_image(
            page,
            output_dir,
            page_number,
            max_width_pixels=SECOND_PASS_WIDTH_PIXELS,
            suffix="_retry",
        )
        retry_ocr_page = _run_ocr_on_image(retry_image_path, serialize_ocr=serialize_ocr)
        attempts = 2
        used_second_pass = True
        if _score_ocr_page_result(retry_ocr_page) >= _score_ocr_page_result(first_ocr_page):
            selected_ocr_page = retry_ocr_page

    page_result = _merge_native_text_with_ocr_page(native_page, selected_ocr_page)
    page_result.page_number = page_number
    page_result.route_info = _build_page_route_info(
        strategy="hybrid" if _should_overlay_native_text(native_page) else "ocr",
        reason=route_reason,
        native_page=native_page,
        has_embedded_images=has_embedded_images,
        embedded_image_coverage=embedded_image_coverage,
        ocr_attempts=attempts,
        used_second_pass=used_second_pass,
    )
    return page_result


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    global ocr_engine, table_engine

    if not PADDLE_AVAILABLE:
        print("WARNING: PaddleOCR not available.")
        return

    print("Initializing PaddleOCR engines...")

    use_gpu = False
    try:
        import paddle
        if paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
            paddle.set_device("gpu:0")
            use_gpu = True
            print(f"GPU available: {paddle.device.cuda.get_device_name(0)}")
    except Exception as e:
        print(f"GPU detection failed, use CPU: {e}")

    print(f"Loading OCR engine (GPU={use_gpu})...")
    ocr_engine = PaddleOCR(
        use_angle_cls=True,
        lang="ch",
        use_gpu=use_gpu,
        show_log=False,
    )
    print("OCR engine loaded.")

    if PPStructure is not None:
        try:
            print(f"Loading table engine (GPU={use_gpu})...")
            table_engine = PPStructure(
                layout=True, ocr=True, show_log=False, use_gpu=use_gpu, table=True, formula=False
            )
            print("Table engine loaded (GPU).")
        except Exception as e:
            print(f"Table engine GPU failed: {e}")
            try:
                table_engine = PPStructure(
                    layout=True, ocr=True, show_log=False, use_gpu=False, table=True, formula=False
                )
                print("Table engine loaded (CPU fallback).")
            except Exception as e2:
                print(f"Table engine CPU also failed: {e2}")
                table_engine = None
    else:
        table_engine = None

    print("OCR engines initialized.")


@app.on_event("shutdown")
async def shutdown_event():
    _ocr_executor.shutdown(wait=True)


@app.get("/health")
async def health_check():
    use_gpu = False
    gpu_name = None
    try:
        import paddle
        if paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
            use_gpu = True
            try:
                gpu_name = paddle.device.cuda.get_device_name(0)
            except Exception:
                gpu_name = "unknown"
    except Exception:
        pass
    return {
        "status": "ok",
        "paddle_available": PADDLE_AVAILABLE,
        "ocr_initialized": ocr_engine is not None,
        "table_engine_initialized": table_engine is not None,
        "use_gpu": use_gpu,
        "gpu_name": gpu_name,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/ocr/pdf", response_model=OCRDocumentResult)
async def process_pdf(file: UploadFile = File(...)):
    """Synchronous PDF OCR (small PDFs, <=30 pages recommended)."""
    if not PADDLE_AVAILABLE or ocr_engine is None:
        raise HTTPException(status_code=503, detail="OCR service not available.")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Only PDF files allowed")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_FILE_SIZE // (1024 * 1024)}MB)")

    temp_dir = tempfile.mkdtemp(prefix="ocr_")
    pdf_path = os.path.join(temp_dir, f"{uuid.uuid4()}.pdf")

    try:
        with open(pdf_path, "wb") as f:
            f.write(content)

        try:
            doc = fitz.open(pdf_path)
            page_count = len(doc)
            doc.close()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid or corrupted PDF file")

        if page_count > MAX_PAGES_SYNC:
            raise HTTPException(
                status_code=400,
                detail=f"PDF has {page_count} pages. For large PDFs use /ocr/pdf/async endpoint (max {MAX_PAGES_SYNC} pages for sync)."
            )

        start = time.time()
        result = await _process_pdf_sync(pdf_path, temp_dir, original_filename=file.filename)
        result.processing_time = time.time() - start
        return result
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"OCR PDF error: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e)[:500])
    finally:
        _cleanup(temp_dir)


@app.post("/ocr/pdf/async", response_model=AsyncJobResponse)
async def process_pdf_async(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """Asynchronous PDF OCR for large files. Returns job_id immediately."""
    if not PADDLE_AVAILABLE or ocr_engine is None:
        raise HTTPException(status_code=503, detail="OCR service not available.")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Only PDF files allowed")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_FILE_SIZE // (1024 * 1024)}MB)")

    job_id = f"job_{uuid.uuid4().hex}"
    job_dir = os.path.join(TEMP_JOB_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    pdf_path = os.path.join(job_dir, f"{uuid.uuid4()}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(content)

    _job_registry[job_id] = {
        "status": "pending",
        "progress": {"current": 0, "total": 0, "percent": 0},
        "result": None,
        "error": None,
        "job_dir": job_dir,
    }

    background_tasks.add_task(
        _process_pdf_background, job_id, pdf_path, job_dir, file.filename
    )

    return AsyncJobResponse(job_id=job_id, status="pending")


@app.get("/ocr/pdf/async/{job_id}", response_model=AsyncJobStatus)
async def get_pdf_async_status(job_id: str):
    """Check async OCR job status and retrieve result when completed."""
    job = _job_registry.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return AsyncJobStatus(
        job_id=job_id,
        status=job["status"],
        progress=job["progress"],
        result=job.get("result"),
        error=job.get("error"),
    )


@app.post("/ocr/image", response_model=OCRDocumentResult)
async def process_image(file: UploadFile = File(...)):
    if not PADDLE_AVAILABLE or ocr_engine is None:
        raise HTTPException(status_code=503, detail="OCR service not available.")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_FILE_SIZE // (1024 * 1024)}MB)")

    temp_dir = tempfile.mkdtemp(prefix="ocr_")
    ext = os.path.splitext(file.filename)[1] or ".jpg"
    image_path = os.path.join(temp_dir, f"{uuid.uuid4()}{ext}")

    try:
        with open(image_path, "wb") as f:
            f.write(content)

        start = time.time()
        page_result = await asyncio.get_event_loop().run_in_executor(
            _ocr_executor, _process_image_sync, image_path
        )
        page_result.page_number = 1
        page_result.route_info = {
            "strategy": "ocr",
            "reason": "image_upload",
            "native_text_chars": 0,
            "native_text_blocks": 0,
            "has_embedded_images": False,
            "ocr_attempts": 1,
            "used_second_pass": False,
        }

        return OCRDocumentResult(
            document_id=f"doc_img_{uuid.uuid4().hex}",
            file_name=file.filename,
            total_pages=1,
            pages=[page_result],
            full_text=page_result.raw_text,
            processing_time=time.time() - start,
            route_metrics=_build_document_route_metrics([page_result]),
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"OCR image error: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e)[:500])
    finally:
        _cleanup(temp_dir)


# ---------------------------------------------------------------------------
# Internal processing
# ---------------------------------------------------------------------------

async def _process_pdf_sync(pdf_path: str, temp_dir: str, original_filename: str) -> OCRDocumentResult:
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or corrupted PDF file")

    if doc.is_encrypted:
        doc.close()
        raise HTTPException(status_code=400, detail="Password-protected PDF not supported")

    total_pages = len(doc)
    if total_pages > MAX_PAGES_TOTAL:
        doc.close()
        raise HTTPException(status_code=400, detail=f"PDF too large (max {MAX_PAGES_TOTAL} pages)")

    pages: List[OCRPageResult] = []

    try:
        for page_num in range(total_pages):
            page = doc.load_page(page_num)
            page_result = _process_pdf_page_with_routing(
                page,
                temp_dir,
                page_num + 1,
                serialize_ocr=True,
            )
            pages.append(page_result)
    finally:
        doc.close()

    full_text = "\n\n".join([p.raw_text for p in pages])

    return OCRDocumentResult(
        document_id=f"doc_pdf_{uuid.uuid4().hex}",
        file_name=original_filename,
        total_pages=total_pages,
        pages=pages,
        full_text=full_text,
        processing_time=0.0,
        route_metrics=_build_document_route_metrics(pages),
    )


def _process_pdf_background(job_id: str, pdf_path: str, job_dir: str, original_filename: str):
    """Background task: page-by-page OCR with incremental persistence."""
    import traceback

    def _update(current: int, total: int):
        _job_registry[job_id]["status"] = "processing"
        _job_registry[job_id]["progress"] = {
            "current": current,
            "total": total,
            "percent": round(current / total * 100, 1) if total else 0,
        }

    try:
        doc = fitz.open(pdf_path)
        if doc.is_encrypted:
            doc.close()
            raise ValueError("Password-protected PDF not supported")

        total_pages = len(doc)
        if total_pages > MAX_PAGES_TOTAL:
            doc.close()
            raise ValueError(f"PDF too large (max {MAX_PAGES_TOTAL} pages)")

        _update(0, total_pages)

        pages_file = os.path.join(job_dir, "pages.jsonl")

        try:
            for page_num in range(total_pages):
                page = doc.load_page(page_num)
                page_result = _process_pdf_page_with_routing(
                    page,
                    job_dir,
                    page_num + 1,
                    serialize_ocr=True,
                )

                with open(pages_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(page_result.model_dump(), ensure_ascii=False) + "\n")

                _update(page_num + 1, total_pages)
        finally:
            doc.close()

        # Assemble final result
        pages: List[OCRPageResult] = []
        with open(pages_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    pages.append(OCRPageResult.model_validate_json(line))

        full_text = "\n\n".join([p.raw_text for p in pages])
        result = OCRDocumentResult(
            document_id=f"doc_pdf_{uuid.uuid4().hex}",
            file_name=original_filename,
            total_pages=total_pages,
            pages=pages,
            full_text=full_text,
            processing_time=0.0,
            route_metrics=_build_document_route_metrics(pages),
        )

        result_path = os.path.join(OUTPUT_DIR, f"{job_id}_result.json")
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)

        _job_registry[job_id]["status"] = "completed"
        _job_registry[job_id]["result"] = result
        _job_registry[job_id]["progress"]["percent"] = 100.0

    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        print(f"Async job {job_id} failed: {error_msg}")
        _job_registry[job_id]["status"] = "failed"
        _job_registry[job_id]["error"] = str(e)[:500]


def _process_image_sync(image_path: str) -> OCRPageResult:
    """Synchronous image OCR + table detection. Must run inside executor or with gpu lock."""

    with Image.open(image_path) as img:
        width, height = img.size
        if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
            scale = MAX_IMAGE_DIMENSION / max(width, height)
            new_size = (int(width * scale), int(height * scale))
            resized = img.resize(new_size, Image.Resampling.LANCZOS)
            resized.save(image_path, quality=85)
            print(f"Resized image from {width}x{height} to {new_size[0]}x{new_size[1]}")

    ocr_result = ocr_engine.ocr(image_path, cls=True)

    text_blocks = []
    if ocr_result and ocr_result[0]:
        for line in ocr_result[0]:
            bbox = line[0]
            text = line[1][0]
            confidence = line[1][1]
            text_blocks.append(
                OCRTextBlock(
                    text=text,
                    confidence=confidence,
                    bbox={
                        "x": min(p[0] for p in bbox),
                        "y": min(p[1] for p in bbox),
                        "width": max(p[0] for p in bbox) - min(p[0] for p in bbox),
                        "height": max(p[1] for p in bbox) - min(p[1] for p in bbox),
                    },
                )
            )

    tables: List[OCRTable] = []
    figures: List[OCRFigure] = []
    if table_engine is not None:
        try:
            with Image.open(image_path) as img:
                w, h = img.size
                if w > 2500 or h > 2500:
                    scale = 2500 / max(w, h)
                    img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
                img_array = np.array(img.convert("RGB"))

            structure_result = table_engine(img_array)
            for region in structure_result:
                region_type = region.get("type", "")
                if region_type == "table":
                    html = region.get("res", {}).get("html", "")
                    if html:
                        cells = _parse_table_cells_from_html(html)
                        tables.append(
                            OCRTable(
                                html=html,
                                markdown=_html_to_markdown(html),
                                cells=cells,
                            )
                        )
                elif region_type in ("figure", "chart", "diagram", "formula"):
                    # Crop the figure/chart region and run OCR to extract all text
                    # (axis labels, tick values, legends, data annotations, etc.)
                    bbox_raw = region.get("bbox", [])
                    fig_bbox = {}
                    fig_texts = []
                    fig_confidences = []
                    if len(bbox_raw) == 4:
                        x1, y1, x2, y2 = int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3])
                        fig_bbox = {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}
                        # Crop and re-OCR the chart region to capture all text inside
                        img_h, img_w = img_array.shape[:2]
                        x1c, y1c = max(0, x1), max(0, y1)
                        x2c, y2c = min(img_w, x2), min(img_h, y2)
                        if x2c > x1c and y2c > y1c:
                            cropped = img_array[y1c:y2c, x1c:x2c]
                            try:
                                crop_ocr = ocr_engine.ocr(cropped, cls=True)
                                if crop_ocr and crop_ocr[0]:
                                    for line in crop_ocr[0]:
                                        text = line[1][0]
                                        conf = line[1][1]
                                        fig_texts.append(text)
                                        fig_confidences.append(conf)
                            except Exception as fe:
                                print(f"Figure crop OCR failed: {fe}")
                    fig_text = "\n".join(fig_texts)
                    fig_conf = sum(fig_confidences) / len(fig_confidences) if fig_confidences else 0.0
                    figures.append(
                        OCRFigure(
                            bbox=fig_bbox,
                            region_type=region_type,
                            text_in_region=fig_text,
                            confidence=fig_conf,
                        )
                    )
        except Exception as e:
            print(f"Table/figure detection failed: {e}")

    # Clear GPU cache between pages to prevent OOM
    try:
        import paddle
        if paddle.is_compiled_with_cuda():
            paddle.device.cuda.synchronize()
    except Exception:
        pass

    raw_text = "\n".join([b.text for b in text_blocks])
    markdown = "\n\n".join([b.text for b in text_blocks])
    avg_confidence = sum(b.confidence for b in text_blocks) / len(text_blocks) if text_blocks else 0.0

    return OCRPageResult(
        page_number=0,
        text_blocks=text_blocks,
        tables=tables,
        figures=figures,
        raw_text=raw_text,
        markdown=markdown,
        confidence=avg_confidence,
    )


def _parse_table_cells_from_html(html: str) -> List[OCRTableCell]:
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(html, "html.parser")
        cells = []
        for row_idx, tr in enumerate(soup.find_all("tr")):
            for col_idx, td in enumerate(tr.find_all(["td", "th"])):
                style = td.get("style", "")
                bbox = {}
                if "left:" in style:
                    bbox["x"] = float(style.split("left:")[1].split("px")[0].strip())
                if "top:" in style:
                    bbox["y"] = float(style.split("top:")[1].split("px")[0].strip())
                if "width:" in style:
                    bbox["width"] = float(style.split("width:")[1].split("px")[0].strip())
                if "height:" in style:
                    bbox["height"] = float(style.split("height:")[1].split("px")[0].strip())
                cells.append(OCRTableCell(
                    row=row_idx,
                    col=col_idx,
                    text=td.get_text(strip=True),
                    bbox=bbox,
                ))
        return cells
    except Exception as e:
        print(f"Failed to parse table cells: {e}")
        return []


def _html_to_markdown(html: str) -> str:
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(html, "html.parser")
        md_lines = []
        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(cells)
            if not rows:
                continue
            max_cols = max(len(r) for r in rows)
            header = rows[0] if rows else []
            header += [""] * (max_cols - len(header))
            md_lines.append("| " + " | ".join(header) + " |")
            md_lines.append("| " + " | ".join(["---"] * max_cols) + " |")
            for row in rows[1:]:
                row += [""] * (max_cols - len(row))
                md_lines.append("| " + " | ".join(row[:max_cols]) + " |")
            md_lines.append("")
        return "\n".join(md_lines)
    except Exception as e:
        print(f"Failed to convert HTML to Markdown: {e}")
        return html


def _cleanup(temp_dir: str):
    try:
        shutil.rmtree(temp_dir)
    except Exception as e:
        print(f"Cleanup failed: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
