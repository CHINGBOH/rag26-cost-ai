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


class OCRPageResult(BaseModel):
    page_number: int
    text_blocks: List[OCRTextBlock]
    tables: List[OCRTable]
    raw_text: str
    markdown: str
    confidence: float


class OCRDocumentResult(BaseModel):
    document_id: str
    file_name: str
    total_pages: int
    pages: List[OCRPageResult]
    full_text: str
    processing_time: float


class AsyncJobResponse(BaseModel):
    job_id: str
    status: str


class AsyncJobStatus(BaseModel):
    job_id: str
    status: str
    progress: dict
    result: Optional[OCRDocumentResult] = None
    error: Optional[str] = None


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
    return {
        "status": "ok",
        "paddle_available": PADDLE_AVAILABLE,
        "ocr_initialized": ocr_engine is not None,
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

        return OCRDocumentResult(
            document_id=f"doc_img_{uuid.uuid4().hex}",
            file_name=file.filename,
            total_pages=1,
            pages=[page_result],
            full_text=page_result.raw_text,
            processing_time=time.time() - start,
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
    loop = asyncio.get_event_loop()

    try:
        for page_num in range(total_pages):
            page = doc.load_page(page_num)
            page_rect = page.rect
            page_width_pt = page_rect.width
            target_dpi = min(200, int(MAX_WIDTH_PIXELS / page_width_pt * 72))

            mat = fitz.Matrix(target_dpi / 72, target_dpi / 72)
            pix = page.get_pixmap(matrix=mat)
            image_path = os.path.join(temp_dir, f"page_{page_num + 1:04d}.jpg")
            pix.save(image_path)

            page_result = await loop.run_in_executor(
                _ocr_executor, _process_image_sync, image_path
            )
            page_result.page_number = page_num + 1
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
                page_rect = page.rect
                page_width_pt = page_rect.width
                target_dpi = min(200, int(MAX_WIDTH_PIXELS / page_width_pt * 72))

                mat = fitz.Matrix(target_dpi / 72, target_dpi / 72)
                pix = page.get_pixmap(matrix=mat)
                image_path = os.path.join(job_dir, f"page_{page_num + 1:04d}.jpg")
                pix.save(image_path)

                # GPU operations must be serialized with lock
                with _gpu_lock:
                    page_result = _process_image_sync(image_path)
                page_result.page_number = page_num + 1

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
                if region.get("type") == "table":
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
        except Exception as e:
            print(f"Table detection failed: {e}")

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
