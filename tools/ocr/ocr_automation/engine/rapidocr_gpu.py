"""
RapidOCR GPU 引擎封装
支持自动检测GPU可用性，fallback到CPU
"""

import logging
import time
from typing import List, Dict, Tuple, Optional
from pathlib import Path

import fitz
from PIL import Image
import io

logger = logging.getLogger(__name__)


class RapidOCREngine:
    """RapidOCR GPU/CPU 封装"""

    def __init__(self, dpi: int = 200):
        self.dpi = dpi
        self._engine = None
        self._gpu_available = False
        self._init_engine()

    def _init_engine(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
            import onnxruntime as ort
            providers = ort.get_available_providers()
            self._gpu_available = any(p in providers for p in ['CUDAExecutionProvider', 'TensorrtExecutionProvider'])
            logger.info(f"ONNXRuntime providers: {providers}")
            self._engine = RapidOCR()
            logger.info(f"✅ RapidOCR loaded (GPU={self._gpu_available})")
        except Exception as e:
            logger.error(f"❌ Failed to load RapidOCR: {e}")
            raise

    def ocr_page(self, page: fitz.Page) -> Tuple[List[Dict], Image.Image]:
        """
        OCR单页PDF，返回文字块列表和渲染图片
        
        Returns:
            cells: [{'x','y','x1','y1','x2','y2','text','conf'}, ...]
            img: PIL.Image
        """
        pix = page.get_pixmap(dpi=self.dpi)
        img = Image.open(io.BytesIO(pix.tobytes('png')))
        
        t0 = time.time()
        result = self._engine(img)
        dt = time.time() - t0
        
        cells = []
        if result and result[0]:
            for box in result[0]:
                coords, text, conf = box
                x1, y1 = coords[0]
                x2, y2 = coords[2]
                cells.append({
                    'x': (x1 + x2) / 2,
                    'y': (y1 + y2) / 2,
                    'x1': x1, 'y1': y1,
                    'x2': x2, 'y2': y2,
                    'text': text,
                    'conf': conf,
                })
        
        logger.debug(f"OCR page: {len(cells)} cells in {dt:.2f}s (GPU={self._gpu_available})")
        return cells, img

    def ocr_image(self, image_path: Path) -> List[Dict]:
        """OCR单张图片文件"""
        img = Image.open(image_path)
        result = self._engine(str(image_path))
        cells = []
        if result and result[0]:
            for box in result[0]:
                coords, text, conf = box
                x1, y1 = coords[0]
                x2, y2 = coords[2]
                cells.append({
                    'x': (x1 + x2) / 2,
                    'y': (y1 + y2) / 2,
                    'x1': x1, 'y1': y1,
                    'x2': x2, 'y2': y2,
                    'text': text,
                    'conf': conf,
                })
        return cells
