"""
OCR Pipeline CLI 入口
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import List

from .config import load_config_from_env
from .engine.rapidocr_gpu import RapidOCREngine
from .engine.chart_extractor import ChartExtractor
from .parser.layout_classifier import classify_page, is_continued_page
from .parser.table_rebuilder import cluster_rows, parse_standard_price_table
from .parser.category_inferencer import resolve_categories, infer_page_type_from_neighbors as infer_category_neighbors
from .parser.price_normalizer import batch_validate
from .store.pg_store import PGStore
from .store.embedding_generator import EmbeddingGenerator

try:
    from .engine.table_transformer import TableTransformerEngine
    TATR_AVAILABLE = True
except Exception as e:
    TATR_AVAILABLE = False
    logging.getLogger(__name__).debug(f"TATR not available: {e}")

try:
    from .engine.vision_llm import VisionLLMEngine
    VISION_LLM_AVAILABLE = True
except Exception as e:
    VISION_LLM_AVAILABLE = False
    logging.getLogger(__name__).debug(f"Vision LLM not available: {e}")

import fitz

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


class OCRPipeline:
    """OCR Pipeline 主控制器"""

    def __init__(self, config=None):
        self.cfg = config or load_config_from_env()
        self.ocr = RapidOCREngine(dpi=self.cfg.ocr.dpi)
        self.chart_extractor = ChartExtractor(self.cfg.charts_dir)
        self.pg = PGStore(
            host=self.cfg.db.host, port=self.cfg.db.port,
            dbname=self.cfg.db.dbname, user=self.cfg.db.user,
            password=self.cfg.db.password
        )
        self.embed = EmbeddingGenerator(
            backend=self.cfg.embedding.backend,
            tei_url=self.cfg.embedding.tei_url,
            ollama_url=self.cfg.embedding.ollama_url,
            ollama_model=self.cfg.embedding.ollama_model,
            dimension=self.cfg.embedding.dimension,
            batch_size=self.cfg.embedding.batch_size
        )
        
        # Chart Vector Extractor（PDF矢量路径提取趋势图数据）
        self._vector_extractor = None
        if self.cfg.enable_chart_vector:
            try:
                from .engine.chart_vector_extractor import ChartVectorExtractor
                self._vector_extractor = ChartVectorExtractor()
                logger.info("✅ Chart vector extraction enabled (pymupdf)")
            except ImportError as e:
                logger.warning(f"⚠️ Chart vector extraction not available: {e}")
        
        # 可选ML引擎
        self.tatr = None
        self.vision_llm = None
        
        if TATR_AVAILABLE and self.cfg.enable_gpu:
            try:
                self.tatr = TableTransformerEngine()
                logger.info("✅ TATR table recognition enabled")
            except Exception as e:
                logger.warning(f"⚠️ TATR init failed: {e}")
        
        if VISION_LLM_AVAILABLE:
            try:
                self.vision_llm = VisionLLMEngine()
                logger.info("✅ Vision LLM chart extraction enabled")
            except Exception as e:
                logger.warning(f"⚠️ Vision LLM init failed: {e}")

    def process_pdf(self, pdf_path: str, doc_type: str = 'price_info',
                    period: str = None, file_name: str = None) -> dict:
        """
        处理单个PDF文件
        
        Returns:
            {'doc_id': int, 'records': int, 'chunks': int, 'charts': int, 'quarantine': int}
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        
        file_name = file_name or pdf_path.name
        period = period or self._extract_period(file_name)
        doc_code = self.pg.doc_code_from_name(file_name)
        
        logger.info(f"=" * 60)
        logger.info(f"Processing: {file_name}")
        logger.info(f"Period: {period}, Type: {doc_type}")
        logger.info(f"=" * 60)
        
        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)
        
        # 注册文档
        doc_id = self.pg.register_document(
            file_name=str(file_name), file_path=str(pdf_path),
            doc_type=doc_type, period=period, total_pages=total_pages
        )
        
        # 清理旧数据（确保重新导入时不重复）
        if not self.cfg.resume:
            self.pg.clear_document_data(doc_id)
        
        # 断点续传：获取待处理页码
        if self.cfg.resume:
            pending_pages = self.pg.get_pending_pages(str(pdf_path), total_pages)
            if pending_pages:
                logger.info(f"Resuming: {len(pending_pages)}/{total_pages} pages pending")
        else:
            pending_pages = list(range(1, total_pages + 1))
        
        all_price_records = []
        all_text_chunks = []
        all_chart_series = []
        all_quarantine = []
        page_results = []
        
        for pnum in pending_pages:
            page = doc[pnum - 1]
            cells, img = self.ocr.ocr_page(page)
            rows = cluster_rows(cells, y_threshold=self.cfg.ocr.y_threshold)
            full_text = '\n'.join([' '.join([c['text'] for c in r]) for r in rows])
            
            # 分类
            page_type = classify_page(full_text, len(cells))
            
            logger.info(f"Page {pnum}/{total_pages}: {page_type} ({len(cells)} cells)")
            
            result = {
                'page_number': pnum,
                'page_type': page_type,
                'cell_count': len(cells),
                'full_text': full_text,
            }
            
            # 根据页面类型处理
            if page_type in ('price_table', 'formula_table', 'rental_table', 
                             'labor_table', 'prefab_table', 'index_table'):
                # 表格页处理：先用TATR识别结构，fallback到坐标聚类
                recs = []
                if self.tatr:
                    try:
                        tatr_recs = self._extract_with_tatr(img, cells, page_type)
                        if tatr_recs:
                            recs = tatr_recs
                            logger.debug(f"Page {pnum}: TATR extracted {len(recs)} records")
                    except Exception as e:
                        logger.warning(f"TATR failed on page {pnum}: {e}")
                
                if not recs:
                    recs = parse_standard_price_table(rows, page_type)
                
                result['records'] = recs
                
            elif page_type == 'chart':
                # 保存图表图片
                chart_path = self.cfg.charts_dir / f"{doc_code}_p{pnum:03d}_chart.png"
                img.save(chart_path)
                
                # 基础OCR标签提取（标题、图例、单位等）
                chart_recs = self.chart_extractor.extract_from_image(
                    img, cells, doc_code, pnum
                )
                
                # === PDF 矢量路径提取：提取精确的数据点 ===
                vector_records = []
                if self._vector_extractor and self.cfg.enable_chart_vector:
                    subchart_configs = self._get_chart_vector_config(doc_code, pnum)
                    if subchart_configs:
                        try:
                            vector_results = self._vector_extractor.extract_from_pdf(
                                pdf_path=str(pdf_path),
                                page_num=pnum,
                                subcharts=subchart_configs,
                                month_start=self._extract_month_start(period),
                            )
                            for vr in vector_results:
                                for pt in vr.points:
                                    vector_records.append({
                                        'page_number': pnum,
                                        'chart_title': vr.chart_name,
                                        'series_name': vr.series_name,
                                        'year_month': pt.month,
                                        'price_value': pt.price,
                                        'extraction_method': 'pdf_vector_paths',
                                        'confidence': 1.0,
                                        'chart_image_path': str(chart_path),
                                        'unit': vr.unit,
                                    })
                            logger.info(
                                f"Page {pnum}: Vector extraction: {len(vector_results)} series, "
                                f"{len(vector_records)} data points"
                            )
                        except Exception as e:
                            logger.warning(f"Vector extraction failed on page {pnum}: {e}")
                    else:
                        logger.debug(
                            f"Page {pnum}: No chart_vector config found for {doc_code}, "
                            f"skipping vector extraction (OCR labels only)"
                        )
                
                # Vision LLM增强（如果启用且矢量提取未成功）
                if self.vision_llm and chart_path.exists() and not vector_records:
                    try:
                        llm_data = self.vision_llm.extract_chart_data(chart_path)
                        for item in llm_data:
                            chart_recs.append({
                                'page_number': pnum,
                                'chart_title': chart_recs[0]['chart_title'] if chart_recs else '趋势图',
                                'series_name': item.get('series_name', '未知'),
                                'year_month': item.get('x_value'),
                                'price_value': item.get('y_value'),
                                'extraction_method': 'vision_llm',
                                'confidence': 0.7,
                                'chart_image_path': str(chart_path),
                            })
                        logger.info(f"Page {pnum}: Vision LLM extracted {len(llm_data)} data points")
                    except Exception as e:
                        logger.warning(f"Vision LLM failed on page {pnum}: {e}")
                
                # 合并所有 chart records：OCR标签 + 矢量数据点
                all_chart_series.extend(chart_recs)
                all_chart_series.extend(vector_records)
                result['chart_records'] = chart_recs + vector_records
                
                # 同时保存OCR文本作为描述
                all_text_chunks.append({
                    'page_number': pnum,
                    'content': f"[图表] {full_text[:800]}",
                    'chunk_type': 'chart',
                    'doc_type': doc_type,
                })
                
            elif page_type == 'article':
                # 分段保存文章
                paragraphs = [p.strip() for p in full_text.split('\n') if len(p.strip()) > 20]
                for para in paragraphs:
                    all_text_chunks.append({
                        'page_number': pnum,
                        'content': para[:2000],
                        'chunk_type': 'article',
                        'doc_type': doc_type,
                    })
                    
            elif page_type in ('cover', 'toc'):
                all_text_chunks.append({
                    'page_number': pnum,
                    'content': full_text[:1500],
                    'chunk_type': 'meta',
                    'doc_type': doc_type,
                })
            
            page_results.append(result)
            
            # 更新任务状态
            self.pg.update_ocr_task(
                str(pdf_path), file_name, doc_code,
                total_pages, pnum, page_type, 'completed', result
            )
        
        doc.close()
        
        # 后处理：修正页面类型（续前页继承）
        page_results = infer_category_neighbors(page_results)
        
        # 收集所有表格记录（保留页面类型信息用于分类）
        for p in page_results:
            if 'records' in p:
                for r in p['records']:
                    r['page_number'] = p['page_number']
                    r['_page_type'] = p['page_type']
                all_price_records.extend(p['records'])
        
        # 解析价格指数表格（Page 13-14类型）
        for p in page_results:
            if p['page_type'] == 'article' and ('造价指数' in p['full_text'] or '材料费指数' in p['full_text']):
                rows = cluster_rows([
                    {'x': 0, 'y': 0, 'text': t} for t in p['full_text'].split('\n')
                ])
                chart_recs = self.chart_extractor.extract_index_table(
                    rows, p['page_number'],
                    chart_title='建安、市政工程造价指数' if '建安' in p['full_text'] else '材料费指数'
                )
                all_chart_series.extend(chart_recs)
        
        # 分类推理：按原始页面类型分组处理
        from collections import defaultdict
        records_by_type = defaultdict(list)
        for r in all_price_records:
            records_by_type[r.get('_page_type', 'price_table')].append(r)
        
        resolved_records = []
        for ptype, recs in records_by_type.items():
            resolved = resolve_categories(recs, page_type=ptype)
            resolved_records.extend(resolved)
        all_price_records = resolved_records
        
        # 验证
        ok_records, quarantine_records = batch_validate(
            all_price_records,
            price_max=self.cfg.price_max,
            price_min=self.cfg.price_min,
            quarantine_threshold=self.cfg.quarantine_threshold
        )
        
        # 导入数据库
        inserted_prices = self.pg.insert_price_records(doc_id, period, ok_records, file_name)
        inserted_chunks = self.pg.insert_text_chunks(doc_id, period, all_text_chunks)
        inserted_charts = self.pg.insert_chart_series(doc_id, doc_code, all_chart_series)
        inserted_quarantine = self.pg.insert_quarantine(doc_id, doc_code, quarantine_records)
        
        # Embedding生成（异步后台）
        if self.cfg.enable_embedding and self.embed._available:
            self._generate_embeddings(doc_id, period)
        
        summary = {
            'doc_id': doc_id,
            'doc_code': doc_code,
            'records': inserted_prices,
            'chunks': inserted_chunks,
            'charts': inserted_charts,
            'quarantine': inserted_quarantine,
            'pages': total_pages,
        }
        
        logger.info(f"\n✅ Complete: {file_name}")
        logger.info(f"   Price records: {inserted_prices}")
        logger.info(f"   Text chunks: {inserted_chunks}")
        logger.info(f"   Chart series: {inserted_charts}")
        logger.info(f"   Quarantine: {inserted_quarantine}")
        
        return summary

    def _generate_embeddings(self, doc_id: int, period: str):
        """为已入库的数据生成embedding"""
        logger.info("Generating embeddings...")
        
        # price_records embedding
        with self.pg.conn.cursor() as cur:
            cur.execute("""
                SELECT id, material_name, spec FROM price_records
                WHERE document_id = %s AND embedding IS NULL
            """, (doc_id,))
            rows = cur.fetchall()
        
        if rows:
            texts = [f"{r[1]} {r[2]}" for r in rows]
            vectors = self.embed.encode(texts)
            embeddings = [(r[0], v) for r, v in zip(rows, vectors)]
            self.pg.update_embeddings('price_records', 'id', embeddings)
            logger.info(f"   Updated {len(embeddings)} price embeddings")
        
        # text_chunks embedding
        with self.pg.conn.cursor() as cur:
            cur.execute("""
                SELECT id, content FROM text_chunks
                WHERE document_id = %s AND embedding IS NULL
            """, (doc_id,))
            rows = cur.fetchall()
        
        if rows:
            texts = [r[1] for r in rows]
            vectors = self.embed.encode(texts)
            embeddings = [(r[0], v) for r, v in zip(rows, vectors)]
            self.pg.update_embeddings('text_chunks', 'id', embeddings)
            logger.info(f"   Updated {len(embeddings)} text embeddings")

    def _extract_with_tatr(self, img, cells, page_type):
        """使用TATR识别表格结构并提取数据"""
        if not self.tatr:
            return []
        
        # 1. 检测表格区域
        tables = self.tatr.detect_tables(img)
        if not tables:
            return []
        
        all_records = []
        for table in tables:
            # 裁剪表格区域
            bbox = table['bbox']
            cropped = img.crop((bbox[0], bbox[1], bbox[2], bbox[3]))
            
            # 调整OCR坐标到裁剪区域
            cropped_cells = []
            for c in cells:
                if bbox[0] <= c['x'] <= bbox[2] and bbox[1] <= c['y'] <= bbox[3]:
                    cropped_cells.append({
                        **c,
                        'x': c['x'] - bbox[0],
                        'y': c['y'] - bbox[1],
                        'x1': c['x1'] - bbox[0],
                        'y1': c['y1'] - bbox[1],
                        'x2': c['x2'] - bbox[0],
                        'y2': c['y2'] - bbox[1],
                    })
            
            # 提取表格数据
            table_data = self.tatr.extract_table_data(cropped, cropped_cells)
            
            # 转换为price_records格式
            if table_data and len(table_data) > 1:
                header = table_data[0]
                for row in table_data[1:]:
                    if len(row) >= 3:
                        rec = self._parse_tatr_row(row, header, page_type)
                        if rec:
                            all_records.append(rec)
        
        return all_records
    
    def _parse_tatr_row(self, row, header, page_type):
        """将TATR表格行解析为price_record"""
        # 简化的映射：假设列顺序与标准价格表类似
        # 尝试找到序号、名称、规格、单位、价格列
        seq_no = None
        material_name = None
        spec = None
        unit = None
        price = None
        
        for i, cell in enumerate(row):
            cell_str = str(cell).strip()
            if not cell_str:
                continue
            
            # 序号列
            if i == 0 and cell_str.isdigit():
                seq_no = int(cell_str)
                continue
            
            # 价格列（最后一列，包含数字）
            if i == len(row) - 1:
                try:
                    price = float(cell_str.replace(',', ''))
                except Exception:
                    pass
                continue
            
            # 单位列（倒数第二列）
            if i == len(row) - 2:
                unit = cell_str
                continue
            
            # 规格列（倒数第三列）
            if i == len(row) - 3:
                spec = cell_str
                continue
            
            # 名称列（第二列）
            if i == 1:
                material_name = cell_str
        
        if material_name and price is not None:
            return {
                'seq_no': seq_no,
                'material_name': material_name[:200],
                'spec': (spec or '')[:200],
                'unit': unit[:20] if unit else None,
                'price': price,
            }
        return None
    
    def _get_chart_vector_config(self, doc_code: str, page_num: int) -> list:
        """
        获取指定文档和页面的 chart vector 子图配置
        
        配置来源：
        1. self.cfg.chart_vector_configs[doc_code][str(page_num)]
        2. 如果找不到，返回空列表（跳过矢量提取）
        """
        if not self.cfg.chart_vector_configs:
            return []
        doc_cfg = self.cfg.chart_vector_configs.get(doc_code, {})
        # 支持 int 和 str 两种 key 类型
        configs = doc_cfg.get(page_num) or doc_cfg.get(str(page_num), [])
        # 转换 price_range list -> tuple
        for c in configs:
            if 'price_range' in c and isinstance(c['price_range'], list):
                c['price_range'] = tuple(c['price_range'])
        return configs

    @staticmethod
    def _extract_month_start(period: str) -> tuple:
        """从 period 字符串提取起始年月，如 '2026-01' -> (2023, 1)"""
        import re
        if not period:
            return (2023, 1)
        # 趋势图通常从 2023-01 开始，与 period 无关
        # 但如果 period 是 2024-XX 格式，可以从 period 推断
        m = re.match(r'(\d{4})-(\d{2})', period)
        if m:
            year = int(m.group(1))
            month = int(m.group(2))
            # 假设数据覆盖 37 个月（3年+1月），倒推起始年月
            # 但这需要知道图表实际时间范围
            # 默认返回 (2023, 1)，大多数深圳信息价趋势图都是 2023-2026
            return (2023, 1)
        return (2023, 1)

    @staticmethod
    def _extract_period(file_name: str) -> str:
        """从文件名提取period"""
        import re
        m = re.search(r'(\d{4})年(\d{1,2})月', file_name)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}"
        m = re.search(r'(\d{4})-(\d{2})', file_name)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
        return ''


def main():
    parser = argparse.ArgumentParser(description='GPU OCR Pipeline for PDF Documents')
    parser.add_argument('input', help='PDF file or directory to process')
    parser.add_argument('--type', default='price_info', help='Document type')
    parser.add_argument('--period', default='', help='Period (e.g., 2026-01)')
    parser.add_argument('--no-embedding', action='store_true', help='Skip embedding generation')
    parser.add_argument('--no-resume', action='store_true', help='Do not resume from checkpoint')
    parser.add_argument('--gpu', action='store_true', default=True, help='Use GPU')
    parser.add_argument('--chart-config', help='Chart vector extraction config JSON file')
    parser.add_argument('--no-chart-vector', action='store_true', help='Disable chart vector extraction')
    
    args = parser.parse_args()
    
    cfg = load_config_from_env()
    if args.no_embedding:
        cfg.enable_embedding = False
    if args.no_resume:
        cfg.resume = False
    cfg.enable_gpu = args.gpu
    if args.no_chart_vector:
        cfg.enable_chart_vector = False
    
    # 加载 chart vector 配置
    if args.chart_config:
        import json
        with open(args.chart_config, 'r', encoding='utf-8') as f:
            cfg.chart_vector_configs = json.load(f)
        logger.info(f"Loaded chart vector config from {args.chart_config}")
    
    pipeline = OCRPipeline(cfg)
    
    input_path = Path(args.input)
    if input_path.is_file() and input_path.suffix.lower() == '.pdf':
        pipeline.process_pdf(
            str(input_path), doc_type=args.type, period=args.period
        )
    elif input_path.is_dir():
        pdfs = list(input_path.rglob('*.pdf'))
        logger.info(f"Found {len(pdfs)} PDF files in {input_path}")
        for pdf in pdfs:
            try:
                pipeline.process_pdf(str(pdf), doc_type=args.type)
            except Exception as e:
                logger.error(f"Failed to process {pdf}: {e}")
    else:
        logger.error(f"Invalid input: {args.input}")
        sys.exit(1)
    
    pipeline.pg.close()
    logger.info("All done!")


if __name__ == '__main__':
    main()
