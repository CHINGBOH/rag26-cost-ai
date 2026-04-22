"""
Table Transformer (TATR) 表格结构识别
使用 microsoft/table-transformer-structure-recognition 模型
"""

import logging
from typing import List, Dict, Tuple
from pathlib import Path

import torch
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)


class TableTransformerEngine:
    """Table Transformer 表格检测与结构识别引擎"""

    def __init__(self, device: str = None):
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        self.detection_model = None
        self.detection_processor = None
        self.structure_model = None
        self.structure_processor = None
        self._load_models()

    def _load_models(self):
        """加载TATR模型"""
        try:
            from transformers import AutoModelForObjectDetection, AutoProcessor
            
            logger.info("Loading Table Transformer detection model...")
            self.detection_processor = AutoProcessor.from_pretrained(
                "microsoft/table-transformer-detection"
            )
            self.detection_model = AutoModelForObjectDetection.from_pretrained(
                "microsoft/table-transformer-detection"
            ).to(self.device)
            self.detection_model.eval()
            
            logger.info("Loading Table Transformer structure model...")
            self.structure_processor = AutoProcessor.from_pretrained(
                "microsoft/table-transformer-structure-recognition"
            )
            self.structure_model = AutoModelForObjectDetection.from_pretrained(
                "microsoft/table-transformer-structure-recognition"
            ).to(self.device)
            self.structure_model.eval()
            
            logger.info(f"✅ TATR models loaded on {self.device}")
        except Exception as e:
            logger.error(f"❌ Failed to load TATR models: {e}")
            raise

    def detect_tables(self, image: Image.Image) -> List[Dict]:
        """
        检测图片中的表格区域
        
        Returns:
            List of {'bbox': [x1, y1, x2, y2], 'score': float}
        """
        inputs = self.detection_processor(images=image, return_tensors="pt").to(self.device)
        
        with torch.no_grad():
            outputs = self.detection_model(**inputs)
        
        # 后处理
        target_sizes = torch.tensor([image.size[::-1]])
        results = self.detection_processor.post_process_object_detection(
            outputs, threshold=0.7, target_sizes=target_sizes
        )[0]
        
        tables = []
        for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):
            if label == 1:  # table class
                tables.append({
                    'bbox': box.tolist(),
                    'score': score.item(),
                })
        
        return tables

    def recognize_structure(self, image: Image.Image) -> List[Dict]:
        """
        识别表格结构（单元格位置）
        
        Returns:
            List of cell dicts: {'bbox': [x1,y1,x2,y2], 'label': str}
            labels: 'table', 'table column', 'table row', 'table column header', 'table projected row header', 'table spanning cell'
        """
        inputs = self.structure_processor(images=image, return_tensors="pt").to(self.device)
        
        with torch.no_grad():
            outputs = self.structure_model(**inputs)
        
        target_sizes = torch.tensor([image.size[::-1]])
        results = self.structure_processor.post_process_object_detection(
            outputs, threshold=0.6, target_sizes=target_sizes
        )[0]
        
        id2label = self.structure_model.config.id2label
        id2label[len(id2label)] = "no object"
        
        cells = []
        for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):
            cells.append({
                'bbox': box.tolist(),
                'label': id2label.get(label.item(), 'unknown'),
                'score': score.item(),
            })
        
        return cells

    def extract_table_data(self, image: Image.Image, ocr_cells: List[Dict]) -> List[List[str]]:
        """
        结合TATR结构识别和OCR文字，提取表格数据
        
        Args:
            image: 表格图片
            ocr_cells: OCR结果 [{'x','y','x1','y1','x2','y2','text'}, ...]
        
        Returns:
            二维数组表示的表格数据
        """
        # 1. 识别表格结构
        structure_cells = self.recognize_structure(image)
        
        # 2. 过滤出row和column header
        rows = [c for c in structure_cells if 'row' in c['label'].lower()]
        cols = [c for c in structure_cells if 'column' in c['label'].lower()]
        
        if not rows or not cols:
            logger.warning("No table structure detected, falling back to OCR clustering")
            return []
        
        # 3. 将OCR文字匹配到单元格
        table = []
        for row_cell in sorted(rows, key=lambda c: c['bbox'][1]):
            row_data = []
            for col_cell in sorted(cols, key=lambda c: c['bbox'][0]):
                # 计算OCR文字块与单元格的IoU
                best_text = ''
                best_iou = 0
                for ocr in ocr_cells:
                    ocr_box = [ocr['x1'], ocr['y1'], ocr['x2'], ocr['y2']]
                    iou = self._compute_iou(col_cell['bbox'], ocr_box)
                    if iou > best_iou and iou > 0.3:
                        best_iou = iou
                        best_text = ocr['text']
                row_data.append(best_text)
            table.append(row_data)
        
        return table

    @staticmethod
    def _compute_iou(box1: List[float], box2: List[float]) -> float:
        """计算两个bbox的IoU"""
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])
        
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = area1 + area2 - inter
        
        return inter / union if union > 0 else 0
