"""
文档处理服务
完整流程: OCR → 质量验证 → 分段 → Embedding → 索引

文件归属: 业务服务层
依赖:
  - config/loader.py (配置加载)
  - services/ocr_quality_validator.py (OCR质量验证)
  - infrastructure/adapters/structured_store.py (结构化存储)
  - domain_models/document.py (数据模型)
被依赖:
  - api/routes.py (API调用)
  - application/usecases.py (用例层)
输出协议: DocumentProcessingResult
"""

import os
import uuid
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
import requests

# 添加路径
import sys
import os

# 添加项目根目录到路径，支持相对导入
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
)  # ../../../../ -> rag-dashboard
sys.path.insert(0, project_root)

from domain_models.document_models import (
    Document,
    DocumentChunk,
    DocumentMetadata,
    DocumentType,
    ChunkType,
)
from infrastructure.adapters.unified import UnifiedStore
from infrastructure.adapters.embedding_service import get_embedding_service

# 可选导入 - 配置加载器
try:
    from config.loader import get_config
except ImportError as e:
    # 备用导入：尝试从项目根目录导入
    import sys
    import os

    # 计算项目根目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
    )  # ../../../../ -> rag-dashboard
    config_path = os.path.join(project_root, "config", "loader.py")
    if os.path.exists(config_path):
        # 使用 importlib 直接导入
        import importlib.util

        spec = importlib.util.spec_from_file_location("config.loader", config_path)
        config_loader = importlib.util.module_from_spec(spec)
        sys.modules["config.loader"] = config_loader
        spec.loader.exec_module(config_loader)
        from config.loader import get_config
    else:
        # 如果找不到配置文件，创建一个虚拟的 get_config
        import logging

        logging.warning("config.loader not found, using default config")
        from typing import Any

        def get_config() -> Any:
            class DefaultConfig:
                class query_analysis:
                    enable_intent_classification = True
                    enable_entity_extraction = True
                    enable_subquery_decomposition = True
                    max_subqueries = 5

                query_analysis = query_analysis()

            return DefaultConfig()

        get_config = get_config

try:
    from services.ocr_quality_validator import OCRQualityValidator

    OCR_VALIDATOR_AVAILABLE = True
except ImportError:
    OCR_VALIDATOR_AVAILABLE = False

try:
    from infrastructure.adapters.structured_store import get_structured_store

    STRUCTURED_STORE_AVAILABLE = True
except ImportError:
    STRUCTURED_STORE_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class DocumentProcessingResult:
    """文档处理结果"""

    doc_id: str
    chunks_count: int
    ocr_quality_report: Optional[Any] = None
    retry_attempts: int = 0
    structured_tables_count: int = 0
    success: bool = True
    error_message: Optional[str] = None


class DocumentProcessor:
    """
    文档处理器 - 端到端文档处理

    增强功能:
    - OCR质量验证 (OCRQualityValidator)
    - 表格双轨存储 (结构化存储)
    - 自动重试机制
    """

    def __init__(self, store: Optional[UnifiedStore] = None):
        print("[DocumentProcessor] 初始化开始...")

        self.store = store or UnifiedStore()
        self.embedding_service = get_embedding_service()
        self.ocr_service_url = "http://localhost:8001"

        # 可选服务
        self.ocr_validator = OCRQualityValidator() if OCR_VALIDATOR_AVAILABLE else None
        self.structured_store = get_structured_store() if STRUCTURED_STORE_AVAILABLE else None

        print(f"[DocumentProcessor] OCR验证器: {'可用' if self.ocr_validator else '不可用'}")
        print(f"[DocumentProcessor] 结构化存储: {'可用' if self.structured_store else '不可用'}")

        # 配置
        config = get_config()
        self.ocr_quality_enabled = (
            config.ocr_quality.enable_llm_verify if hasattr(config, "ocr_quality") else True
        )
        self.max_ocr_retries = (
            config.ocr_quality.max_retries if hasattr(config, "ocr_quality") else 3
        )
        self.ocr_timeout = (
            getattr(getattr(config.services, "ocr", None), "timeout_seconds", 300)
            if hasattr(config, "services")
            else 300
        )

        print(
            f"[DocumentProcessor] 配置: max_retries={self.max_ocr_retries}, timeout={self.ocr_timeout}"
        )
        print("[DocumentProcessor] 初始化完成 ✓")

    def process_pdf(self, file_path: str, title: Optional[str] = None) -> Document:
        """处理 PDF 文档 - 带完整埋点"""
        import time

        print(f"\n{'=' * 60}")
        print(f"[ProcessPDF] 开始处理: {file_path}")
        print(f"[ProcessPDF] 文档标题: {title or os.path.basename(file_path)}")
        print(f"{'=' * 60}")

        total_start = time.time()

        # 1. OCR 识别
        print("\n[Step 1/6] OCR 识别...")
        step_start = time.time()
        ocr_result = self._call_ocr(file_path)
        ocr_time = time.time() - step_start
        page_count = len(ocr_result.get("pages", []))
        text_block_count = sum(len(p.get("text_blocks", [])) for p in ocr_result.get("pages", []))
        table_count = sum(len(p.get("tables", [])) for p in ocr_result.get("pages", []))
        print(
            f"[Step 1/6] ✓ OCR完成: {page_count}页, {text_block_count}文本块, {table_count}表格 (耗时{ocr_time:.2f}s)"
        )

        # 2. 创建文档元数据
        print("\n[Step 2/6] 创建文档元数据...")
        doc_id = str(uuid.uuid4())
        metadata = DocumentMetadata(
            doc_id=doc_id,
            title=title or os.path.basename(file_path),
            source=file_path,
            doc_type=DocumentType.PDF,
            total_pages=ocr_result.get("total_pages", 1),
        )
        print(f"[Step 2/6] ✓ 元数据创建: doc_id={doc_id}")

        # 3. 分段
        print("\n[Step 3/6] 文档分段...")
        step_start = time.time()
        chunks = self._create_chunks(doc_id, ocr_result)
        chunk_time = time.time() - step_start
        text_chunks = len([c for c in chunks if c.chunk_type == ChunkType.TEXT])
        table_chunks = len([c for c in chunks if c.chunk_type == ChunkType.TABLE])
        print(
            f"[Step 3/6] ✓ 分段完成: {len(chunks)}总段 (文本{text_chunks}, 表格{table_chunks}) (耗时{chunk_time:.2f}s)"
        )

        # 4. 生成 Embedding
        print("\n[Step 4/6] 生成 Embedding...")
        step_start = time.time()
        embed_success = self._generate_embeddings(chunks)
        embed_time = time.time() - step_start
        if embed_success:
            print(f"[Step 4/6] ✓ Embedding完成: {len(chunks)}个向量 (耗时{embed_time:.2f}s)")
        else:
            print(f"[Step 4/6] ⚠ Embedding部分失败，继续索引...")

        # 5. 构建文档
        print("\n[Step 5/6] 构建文档对象...")
        document = Document(
            metadata=metadata, chunks=chunks, raw_content=ocr_result.get("full_text", "")
        )
        print(f"[Step 5/6] ✓ 文档对象创建完成")

        # 6. 索引到四库
        print("\n[Step 6/6] 索引到四库...")
        step_start = time.time()
        try:
            self.store.index_document(document)
            index_time = time.time() - step_start
            print(f"[Step 6/6] ✓ 索引完成 (耗时{index_time:.2f}s)")
        except Exception as e:
            print(f"[Step 6/6] ✗ 索引失败: {e}")
            raise

        total_time = time.time() - total_start
        print(f"\n{'=' * 60}")
        print(f"[ProcessPDF] 处理完成 ✓")
        print(f"  doc_id: {doc_id}")
        print(f"  总分段: {len(chunks)}")
        print(f"  总耗时: {total_time:.2f}s")
        print(f"{'=' * 60}\n")

        return document

    def _call_ocr(self, file_path: str) -> Dict[str, Any]:
        """调用 OCR 服务并进行质量验证 - 增强版带埋点和退避策略"""
        import time

        attempt = 0
        best_result = None
        best_quality = 0.0
        last_error = None

        print(f"\n  [OCR] 开始OCR识别: {os.path.basename(file_path)}")
        print(f"  [OCR] 最大重试次数: {self.max_ocr_retries}, 超时: {self.ocr_timeout}s")

        while attempt < self.max_ocr_retries:
            attempt += 1

            # 退避策略: 第2次起等待1秒，第3次起等待2秒
            if attempt > 1:
                wait_time = min(attempt - 1, 3)
                print(f"  [OCR] 退避等待 {wait_time}s...")
                time.sleep(wait_time)

            print(f"  [OCR] 尝试 {attempt}/{self.max_ocr_retries}...")

            try:
                with open(file_path, "rb") as f:
                    files = {"file": (os.path.basename(file_path), f, "application/pdf")}
                    response = requests.post(
                        f"{self.ocr_service_url}/ocr/pdf", files=files, timeout=self.ocr_timeout
                    )

                    if response.status_code == 200:
                        ocr_result = response.json()
                        pages = len(ocr_result.get("pages", []))
                        print(f"  [OCR] 请求成功: 获得{pages}页数据")

                        # OCR质量验证
                        if self.ocr_validator and self.ocr_quality_enabled:
                            print("  [OCR] 执行质量验证...")
                            quality_report = self.ocr_validator.validate(ocr_result, attempt)

                            score = quality_report.overall_score
                            grade = quality_report.grade.value
                            needs_retry = quality_report.needs_retry

                            print(f"  [OCR] 质量评分: {score:.3f} ({grade})")

                            if score > best_quality:
                                best_result = ocr_result
                                best_quality = score
                                print(f"  [OCR] 更新最佳结果: quality={best_quality:.3f}")

                            # 质量达标直接返回
                            if not needs_retry:
                                print("  [OCR] 质量达标，返回结果")
                                return best_result

                            # 已达最大重试次数
                            if attempt >= self.max_ocr_retries:
                                print(
                                    f"  [OCR] 已达最大重试次数，返回最佳结果 (quality={best_quality:.3f})"
                                )
                                if best_result:
                                    return best_result
                                break

                            print(f"  [OCR] 需要重试，问题: {', '.join(quality_report.issues[:2])}")
                        else:
                            print("  [OCR] 质量验证跳过，直接返回")
                            return ocr_result
                    else:
                        error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                        print(f"  [OCR] ✗ 请求失败: {error_msg}")
                        last_error = error_msg

            except requests.exceptions.Timeout:
                print(f"  [OCR] ✗ 请求超时 (> {self.ocr_timeout}s)")
                last_error = f"Timeout after {self.ocr_timeout}s"
            except requests.exceptions.ConnectionError:
                print(f"  [OCR] ✗ 连接失败: 无法连接到OCR服务 {self.ocr_service_url}")
                last_error = "Connection refused"
            except Exception as e:
                print(f"  [OCR] ✗ 异常: {type(e).__name__}: {str(e)[:100]}")
                last_error = str(e)

        # 所有重试失败
        if best_result:
            print(f"  [OCR] ⚠ 使用最佳结果返回 (quality={best_quality:.3f})")
            return best_result

        # 彻底失败
        error_detail = f"OCR failed after {self.max_ocr_retries} attempts. Last error: {last_error}"
        print(f"  [OCR] ✗ 彻底失败: {error_detail}")
        raise RuntimeError(error_detail)

    def _create_chunks(self, doc_id: str, ocr_result: Dict) -> List[DocumentChunk]:
        """
        从 OCR 结果创建分段 - 增强版支持表格双轨存储

        双轨存储:
        - JSON: 表格原始结构
        - Markdown: 展示格式
        - 摘要: 用于Embedding
        """
        print("\n  [Chunk] 开始分段处理...")

        chunks = []
        chunk_index = 0
        tables_for_structured_store = []

        pages = ocr_result.get("pages", [])
        total_text_blocks = 0
        total_tables = 0

        print(f"  [Chunk] 处理{len(pages)}页...")
        for page in pages:
            page_num = page.get("page_number", 1)

            # 处理文本块
            text_blocks = page.get("text_blocks", [])
            total_text_blocks += len(text_blocks)

            for block in text_blocks:
                text = block.get("text", "").strip()
                if not text:  # 跳过空文本
                    continue

                chunk = DocumentChunk(
                    chunk_id=f"{doc_id}_chunk_{chunk_index:04d}",
                    doc_id=doc_id,
                    content=text,
                    chunk_type=ChunkType.TEXT,
                    page_number=page_num,
                    confidence=block.get("confidence", 1.0),
                    keywords=self._extract_keywords(text),
                )
                chunks.append(chunk)
                chunk_index += 1

            # 处理表格 - 双轨存储
            tables = page.get("tables", [])
            total_tables += len(tables)

            for table in tables:
                print(f"    [Chunk] 处理表格 (第{page_num}页)...")

                # 1. 解析表格结构
                table_structure = self._parse_table_structure(table)
                row_count = table_structure.get("row_count", 0)
                col_count = table_structure.get("col_count", 0)
                print(f"      [Chunk] 表格结构: {row_count}行 x {col_count}列")

                # 2. 生成 Markdown
                markdown_table = self._generate_markdown_table(table_structure)
                print(f"      [Chunk] Markdown生成: {len(markdown_table)}字符")

                # 3. 生成摘要 (用于向量化)
                table_summary = self._generate_table_summary(table_structure, page_num)
                print(f"      [Chunk] 摘要生成: {len(table_summary)}字符")

                chunk_id = f"{doc_id}_table_{chunk_index:04d}"
                chunk = DocumentChunk(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    content=table_summary,  # 摘要用于Embedding
                    chunk_type=ChunkType.TABLE,
                    page_number=page_num,
                    keywords=["表格", "数据"] + (table_structure.get("headers", [])[:3]),
                    extra={
                        "table_structure": table_structure,
                        "markdown": markdown_table,
                        "html": table.get("html", ""),
                    },
                )
                chunks.append(chunk)

                # 收集表格供结构化存储
                tables_for_structured_store.append(
                    {"chunk_id": chunk_id, "table_structure": table_structure}
                )

                chunk_index += 1

        print(f"  [Chunk] 文本块: {total_text_blocks}个, 表格: {total_tables}个")

        # 写入结构化存储
        if self.structured_store and tables_for_structured_store:
            print(f"  [Chunk] 写入结构化存储: {len(tables_for_structured_store)}个表格...")
            stored_count = self._store_tables_to_structured_db(doc_id, tables_for_structured_store)
            print(
                f"  [Chunk] 结构化存储完成: {stored_count}/{len(tables_for_structured_store)}个表格"
            )
        else:
            if not self.structured_store:
                print("  [Chunk] 结构化存储不可用，跳过")
            elif not tables_for_structured_store:
                print("  [Chunk] 无表格需要存储")

        print(f"  [Chunk] 分段完成: 共{len(chunks)}个chunk")
        return chunks

    def _parse_table_structure(self, table: Dict) -> Dict:
        """解析表格为结构化数据 - 增强版带异常处理"""
        html = table.get("html", "")
        if not html:
            print("      [Parse] 警告: 表格HTML为空")
            return {"headers": [], "rows": [], "row_count": 0, "col_count": 0}

        import re  # noqa: F401

        try:
            # 提取行
            rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE)

            if not rows:
                print("      [Parse] 警告: 未找到表格行")
                return {"headers": [], "rows": [], "row_count": 0, "col_count": 0}

            parsed_rows = []
            headers = []

            for i, row_html in enumerate(rows):
                # 支持 th 和 td
                cells = re.findall(
                    r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.DOTALL | re.IGNORECASE
                )
                # 清理HTML标签
                cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]

                if i == 0:
                    headers = cells
                    print(f"      [Parse] 表头: {cells[:3]}...")
                else:
                    parsed_rows.append({"cells": cells, "row_index": i})

            result = {
                "headers": headers,
                "rows": parsed_rows,
                "row_count": len(parsed_rows),
                "col_count": len(headers),
            }

            print(f"      [Parse] 解析完成: {result['row_count']}行 x {result['col_count']}列")
            return result

        except Exception as e:
            print(f"      [Parse] ✗ 表格解析失败: {type(e).__name__}: {str(e)[:50]}")
            return {"headers": [], "rows": [], "row_count": 0, "col_count": 0}

    def _generate_markdown_table(self, structure: Dict) -> str:
        """生成 Markdown 表格"""
        headers = structure.get("headers", [])
        rows = structure.get("rows", [])

        if not headers:
            return ""

        md = "| " + " | ".join(headers) + " |\n"
        md += "|" + "|".join(["---"] * len(headers)) + "|\n"

        for row in rows:
            cells = row.get("cells", [])
            md += "| " + " | ".join(cells) + " |\n"

        return md

    def _generate_table_summary(self, structure: Dict, page_num: int) -> str:
        """生成表格摘要用于 Embedding"""
        headers = structure.get("headers", [])
        row_count = structure.get("row_count", 0)

        # 提取关键列用于关键词
        _ = [
            h
            for h in headers
            if any(k in h for k in ["价格", "名称", "规格", "型号", "月份", "时间"])
        ]

        parts = [
            f"表格数据，第{page_num}页",
            f"包含列: {', '.join(headers[:5])}" if headers else "",
            f"共{row_count}行数据",
            "数据类型: 建设工程信息价" if "价格" in str(headers) else "",
        ]

        return "；".join(filter(None, parts))

    def _store_tables_to_structured_db(self, doc_id: str, tables: List[Dict]) -> int:
        """将表格存储到 PostgreSQL - 增强版带埋点"""
        if not self.structured_store:
            print("    [Store] 结构化存储未初始化")
            return 0

        stored_count = 0
        for i, table_data in enumerate(tables):
            try:
                chunk_id = table_data["chunk_id"]
                structure = table_data["table_structure"]

                print(f"    [Store] 存储表格 {i + 1}/{len(tables)}: chunk_id={chunk_id}")

                self.structured_store.store_table(
                    doc_id=doc_id, chunk_id=chunk_id, table_structure=structure
                )
                stored_count += 1
                print(f"    [Store] ✓ 表格 {i + 1} 存储成功")

            except Exception as e:
                print(f"    [Store] ✗ 表格 {i + 1} 存储失败: {type(e).__name__}: {str(e)[:100]}")
                # 继续处理其他表格，不中断流程

        return stored_count

    def _extract_keywords(self, text: str) -> List[str]:
        """简单关键词提取"""
        # 实际应该用 TF-IDF 或 TextRank
        # 这里简化处理
        words = text.split()
        # 过滤短词和数字
        keywords = [w for w in words if len(w) >= 2 and not w.isdigit()]
        return keywords[:10]  # 返回前10个

    def _generate_embeddings(self, chunks: List[DocumentChunk]) -> bool:
        """为分段生成 Embedding - 增强版带降级处理"""
        if not chunks:
            print("  [Embed] 无chunks需要处理")
            return True

        total = len(chunks)
        print(f"  [Embed] 生成{total}个Embedding...")
        print(f"  [Embed] 使用模型: {self.embedding_service.model_name}")

        texts = [chunk.content for chunk in chunks]

        try:
            embeddings = self.embedding_service.encode(texts)

            success_count = 0
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                if embedding is not None and len(embedding) > 0:
                    chunk.embedding = embedding
                    chunk.embedding_model = self.embedding_service.model_name
                    success_count += 1
                else:
                    print(f"    [Embed] ⚠ chunk {i} 返回空向量")
                    # 标记为失败但不中断
                    chunk.embedding = None

            print(f"  [Embed] 完成: {success_count}/{total}个成功")
            return success_count == total

        except Exception as e:
            print(f"  [Embed] ✗ Embedding生成失败: {type(e).__name__}: {str(e)[:100]}")
            print("  [Embed] ⚠ 将尝试使用零向量降级...")

            # 降级：使用零向量或跳过
            for chunk in chunks:
                chunk.embedding = None  # 下游需要处理None

            return False

    def process_text(self, text: str, title: str = "Text Document") -> Document:
        """处理纯文本"""
        doc_id = str(uuid.uuid4())

        metadata = DocumentMetadata(
            doc_id=doc_id, title=title, source="text_input", doc_type=DocumentType.TEXT
        )

        # 简单分段
        chunks = self._chunk_text(doc_id, text)
        self._generate_embeddings(chunks)

        document = Document(metadata=metadata, chunks=chunks)
        self.store.index_document(document)

        return document

    def _chunk_text(
        self, doc_id: str, text: str, chunk_size: int = 500, overlap: int = 50
    ) -> List[DocumentChunk]:
        """文本分段"""
        chunks = []
        start = 0
        chunk_index = 0

        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk_text = text[start:end]

            chunk = DocumentChunk(
                chunk_id=f"{doc_id}_chunk_{chunk_index:04d}",
                doc_id=doc_id,
                content=chunk_text,
                chunk_type=ChunkType.TEXT,
                page_number=1,
            )
            chunks.append(chunk)

            start = end - overlap
            chunk_index += 1

        return chunks
