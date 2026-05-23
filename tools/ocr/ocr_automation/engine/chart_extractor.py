"""
图表数据提取引擎
支持：趋势图区域检测、OCR标签提取、数据点提取（传统CV方法 + 矢量路径方法）

两种提取模式：
1. OCR 标签模式（默认）：提取图表标题、图例、单位等文字标签，不提取具体数据点
2. 矢量路径模式：直接从 PDF 矢量绘制路径中提取数据点（需要配置子图区域）
   适用：PDF 中的矢量趋势图/折线图
   详见：chart_vector_extractor.py

使用示例：
    >>> extractor = ChartExtractor(output_dir=Path("./output"))
    >>> # 模式 1：OCR 标签提取
    >>> records = extractor.extract_from_image(img, cells, doc_code, page_num)
    >>> # 模式 2：矢量路径提取（需要 pdf_path 和子图配置）
    >>> records = extractor.extract_vector_data(pdf_path, page_num, subcharts)
"""

import logging
import re
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)


class ChartExtractor:
    """图表提取器 - 支持 OCR 标签提取和矢量路径数据提取"""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._vector_extractor = None

    def save_chart_image(self, img: Image.Image, doc_code: str, page_number: int) -> Path:
        """保存图表图片"""
        path = self.output_dir / f"{doc_code}_p{page_number:03d}_chart.png"
        img.save(path)
        return path

    def extract_ocr_labels(self, cells: List[Dict]) -> Dict:
        """
        从OCR结果中提取图表的文字标签
        
        Returns:
            {
                'title': str,
                'subtitle': str,
                'legend': [str],
                'y_axis_labels': [str],  # Y轴刻度值
                'x_axis_labels': [str],  # X轴刻度值
                'unit': str,
            }
        """
        result = {
            'title': '',
            'subtitle': '',
            'legend': [],
            'y_axis_labels': [],
            'x_axis_labels': [],
            'unit': '',
        }
        
        texts = [c['text'].strip() for c in cells]
        full_text = ' '.join(texts)
        
        # 提取标题
        if '趋势图' in full_text:
            for t in texts:
                if '趋势图' in t and len(t) > 5:
                    result['title'] = t
                    break
        
        # 提取副标题（年份范围等）
        m = re.search(r'（(\d{4}-\d{4}年)）', full_text)
        if m:
            result['subtitle'] = m.group(1)
        
        # 提取单位
        m = re.search(r'（单位：([^）]+)）', full_text)
        if m:
            result['unit'] = m.group(1)
        
        # 提取图例（通常包含材料名称+型号）
        # 图例特征：包含材料名称，且后面没有数字或很短
        for t in texts:
            if any(kw in t for kw in ['钢筋', '水泥', '角钢', '混凝土', '砂浆', '电缆', '钢管']):
                if len(t) < 60 and '趋势图' not in t and '单位' not in t:
                    if t not in result['legend']:
                        result['legend'].append(t)
        
        # 提取Y轴刻度值（通常是较大的数字，可能是价格）
        for t in texts:
            m = re.match(r'^(\d{3,5})$', t)
            if m:
                val = int(m.group(1))
                if 100 <= val <= 100000:
                    result['y_axis_labels'].append(t)
        
        # 提取X轴刻度值（年份-月份格式）
        for t in texts:
            if re.match(r'^\d{2}-\d{1,2}$', t) or re.match(r'^\d{4}-\d{2}$', t):
                result['x_axis_labels'].append(t)
        
        return result

    def extract_from_image(self, img: Image.Image, cells: List[Dict],
                           doc_code: str, page_number: int) -> List[Dict]:
        """
        从图表图片中提取时间序列数据
        
        当前实现：保存图片 + OCR标签提取
        未来可扩展：DePlot/视觉LLM自动提取数据点
        
        Returns:
            List of chart_series dicts
        """
        chart_path = self.save_chart_image(img, doc_code, page_number)
        labels = self.extract_ocr_labels(cells)
        
        series_list = []
        
        # 为每个图例创建一个系列记录
        for legend in labels['legend']:
            series_list.append({
                'page_number': page_number,
                'chart_title': labels['title'] or labels['subtitle'],
                'series_name': legend,
                'year_month': None,  # 无法从扫描图精确提取
                'price_value': None,
                'extraction_method': 'ocr_labels_only',
                'confidence': 0.5,
                'chart_image_path': str(chart_path),
                'unit': labels['unit'],
                'y_axis_labels': labels['y_axis_labels'],
                'x_axis_labels': labels['x_axis_labels'],
            })
        
        # 如果没有图例，至少保存一个汇总记录
        if not series_list:
            series_list.append({
                'page_number': page_number,
                'chart_title': labels['title'] or '趋势图',
                'series_name': '汇总',
                'year_month': None,
                'price_value': None,
                'extraction_method': 'ocr_labels_only',
                'confidence': 0.3,
                'chart_image_path': str(chart_path),
                'unit': labels['unit'],
            })
        
        return series_list

    def extract_index_table(self, rows: List[List[Dict]], page_number: int,
                            chart_title: str = '') -> List[Dict]:
        """
        从价格指数表格（Page 13-14类型）提取时间序列
        
        表格格式：
        类别 | 项目 | 2024-2月 | 2024-3月 | ...
        
        Returns:
            List of chart_series dicts
        """
        series_list = []
        
        # 重建表格
        from ..parser.table_rebuilder import rebuild_table, detect_header_row
        table = rebuild_table(rows)
        if not table:
            return series_list
        
        header_idx = detect_header_row(table)
        if header_idx is None:
            return series_list
        
        header_row = table[header_idx]
        # 提取月份列（从第2列开始）
        months = []
        for col_idx, text in header_row.items():
            if col_idx >= 2:
                # 尝试提取年月
                m = re.search(r'(\d{4})年\s*(\d{1,2})月', text)
                if m:
                    months.append((col_idx, f"{m.group(1)}-{int(m.group(2)):02d}"))
        
        # 遍历数据行
        current_category = ''
        for row in table[header_idx + 1:]:
            texts = list(row.values())
            if not texts:
                continue
            
            # 检测分类/项目名称
            first_col = row.get(0, '')
            second_col = row.get(1, '')
            
            if first_col and not second_col and len(first_col) < 20:
                current_category = first_col
                continue
            
            series_name = f"{current_category}_{second_col or first_col}".strip('_')
            if not series_name or series_name == '_':
                continue
            
            # 提取各月数值
            for col_idx, year_month in months:
                val_text = row.get(col_idx, '')
                val = self._parse_number(val_text)
                if val is not None:
                    series_list.append({
                        'page_number': page_number,
                        'chart_title': chart_title,
                        'series_name': series_name,
                        'year_month': year_month,
                        'price_value': val,
                        'extraction_method': 'ocr_index_table',
                        'confidence': 0.9,
                    })
        
        return series_list

    # ------------------------------------------------------------------
    # 矢量路径提取模式（新增）
    # ------------------------------------------------------------------

    def extract_vector_data(
        self,
        pdf_path: str,
        page_num: int,
        subcharts: List[Dict],
        month_start: Tuple[int, int] = (2023, 1),
    ) -> List[Dict]:
        """
        从 PDF 矢量路径中提取趋势图数据点

        这是 OCR 标签模式的补充，当需要精确提取数据点时使用。

        Args:
            pdf_path: PDF 文件路径
            page_num: 页码（从 1 开始）
            subcharts: 子图配置列表，每个元素为 dict：
                {
                    "y1": 130, "y2": 292,
                    "name": "热轧钢筋",
                    "series": ["光圆钢筋", "带肋钢筋"],
                    "price_range": (3000, 5500),
                    "x_axis_margin": 45,  # 可选，默认 45
                }
            month_start: 起始年月 (year, month)，默认 (2023, 1)

        Returns:
            List of chart_series dicts（与 extract_from_image 输出格式兼容）
        """
        try:
            from .chart_vector_extractor import ChartVectorExtractor
        except ImportError:
            logger.error("chart_vector_extractor not available. Install pymupdf.")
            return []

        if self._vector_extractor is None:
            self._vector_extractor = ChartVectorExtractor()

        try:
            results = self._vector_extractor.extract_from_pdf(
                pdf_path=pdf_path,
                page_num=page_num,
                subcharts=subcharts,
                month_start=month_start,
            )
        except Exception as e:
            logger.error(f"Vector extraction failed for page {page_num}: {e}")
            return []

        # 转换为与 extract_from_image 兼容的格式
        records = []
        for r in results:
            d = r.to_dict()
            for point in d["data_points"]:
                records.append({
                    "page_number": d["page"],
                    "chart_title": d["chart_name"],
                    "series_name": d["series_name"],
                    "year_month": point["month"],
                    "price_value": point["price"],
                    "extraction_method": "pdf_vector_paths",
                    "confidence": 1.0,
                    "unit": d["unit"],
                    "_y_pixel": point.get("_y_pixel"),
                })
        return records

    def auto_detect_subcharts(
        self,
        pdf_path: str,
        page_num: int,
    ) -> List[Dict]:
        """
        自动检测子图区域（辅助配置）

        当不确定子图边界时，先用此方法获取大致区域，再手动微调。

        Returns:
            List of detected subchart regions
        """
        try:
            from .chart_vector_extractor import ChartVectorExtractor
        except ImportError:
            logger.error("chart_vector_extractor not available.")
            return []

        if self._vector_extractor is None:
            self._vector_extractor = ChartVectorExtractor()

        return self._vector_extractor.extract_auto_detect(pdf_path, page_num)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_number(s: str) -> Optional[float]:
        """解析数字"""
        if not s:
            return None
        s = s.strip().replace(',', '')
        try:
            return float(s)
        except Exception:
            return None
