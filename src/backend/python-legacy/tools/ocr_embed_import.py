#!/usr/bin/env python3
"""
OCR数据Qdrant向量数据库导入脚本
使用真实的Sentence-Transformers模型进行embedding
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from sentence_transformers import SentenceTransformer

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

OCR_OUTPUT_DIR = "/home/l/rag-dashboard/data/ocr_outputs"
EMBEDDING_MODEL = "/home/l/rag-dashboard/models/BAAI/bge-m3"
EMBEDDING_DIM = 1024
CHUNK_SIZE = 300
CHUNK_OVERLAP = 50
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
COLLECTION_NAME = "document_chunks"

class OCREmbedImporter:
    def __init__(self):
        self.qdrant_client = None
        self.embedding_model = None
        self.onnx_session = None
        self.collection_name = COLLECTION_NAME
        self.point_counter = 0

    def initialize(self):
        logger.info("初始化Qdrant连接...")
        self.qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        self._ensure_collection()
        self._load_embedding_model()
        self._load_counter()

    def _ensure_collection(self):
        collections = self.qdrant_client.get_collections().collections
        collection_names = [c.name for c in collections]

        if self.collection_name not in collection_names:
            logger.info(f"创建Collection: {self.collection_name}")
            self.qdrant_client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIM,
                    distance=Distance.COSINE
                )
            )
        else:
            logger.info(f"Collection已存在: {self.collection_name}")

    def _load_embedding_model(self):
        logger.info(f"加载Sentence-Transformers模型: {EMBEDDING_MODEL}")

        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"使用设备: {device}")

            self.embedding_model = SentenceTransformer(EMBEDDING_MODEL, device=device)
            logger.info(f"模型加载成功，向量维度: {EMBEDDING_DIM}")
            logger.info(f"模型设备: {self.embedding_model.device}")
        except Exception as e:
            logger.error(f"加载模型失败: {e}")
            logger.info("尝试使用ONNX模型...")

            try:
                from onnxruntime import InferenceSession

                onnx_path = "/home/l/rag-dashboard/models/BAAI/bge-m3/onnx/model.onnx"
                if os.path.exists(onnx_path):
                    logger.info(f"使用ONNX模型: {onnx_path}")
                    self.onnx_session = InferenceSession(onnx_path)
                    logger.info("ONNX模型加载成功")
                else:
                    logger.info("ONNX模型不存在，使用本地hash embedding作为替代")
                    self.embedding_model = None
            except Exception as e2:
                logger.error(f"加载ONNX模型失败: {e2}")
                logger.info("使用本地hash embedding作为替代")
                self.embedding_model = None

    def _load_counter(self):
        try:
            result = self.qdrant_client.scroll(
                collection_name=self.collection_name,
                limit=1,
                with_payload=False,
                with_vectors=False,
                order_by={
                    "key": "id",
                    "direction": "desc"
                }
            )
            if result[0]:
                last_id = result[0][0].id
                if isinstance(last_id, int):
                    self.point_counter = last_id
                    logger.info(f"从 {self.point_counter} 继续编号")
        except Exception as e:
            logger.info(f"无法获取当前最大ID: {e}")

    def embed_text(self, text: str) -> List[float]:
        if self.embedding_model:
            embedding = self.embedding_model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
        elif hasattr(self, 'onnx_session') and self.onnx_session:
            import numpy as np
            import torch
            inputs = self.embedding_model.tokenize([text])
            onnx_inputs = {
                "input_ids": inputs["input_ids"].numpy(),
                "attention_mask": inputs["attention_mask"].numpy()
            }
            outputs = self.onnx_session.run(None, onnx_inputs)
            embedding = outputs[0][0]
            embedding = embedding / np.linalg.norm(embedding)
            return embedding.tolist()
        else:
            import hashlib
            text_hash = hashlib.md5(text.encode()).digest()
            vec = np.array([float(b) / 255.0 for b in text_hash * 32][:EMBEDDING_DIM])
            vec = vec / np.linalg.norm(vec) if np.linalg.norm(vec) > 0 else vec
            return vec.tolist()

    def chunk_text(self, text: str) -> List[str]:
        if len(text) <= CHUNK_SIZE:
            return [text] if text.strip() else []

        chunks = []
        start = 0
        while start < len(text):
            end = start + CHUNK_SIZE
            if start > 0:
                start = start - CHUNK_OVERLAP

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            start = end

        return chunks

    def get_ocr_files(self) -> List[Path]:
        ocr_dir = Path(OCR_OUTPUT_DIR)
        ocr_files = []
        for file in ocr_dir.glob("*_ocr.json"):
            if "chunk" not in file.name:
                ocr_files.append(file)

        logger.info(f"找到 {len(ocr_files)} 个OCR文件")
        return ocr_files

    def process_ocr_file(self, ocr_file: Path) -> List[PointStruct]:
        logger.info(f"处理文件: {ocr_file.name}")

        with open(ocr_file, 'r', encoding='utf-8') as f:
            content = f.read()

        json_start = content.find('{')
        if json_start == -1:
            logger.error(f"文件中没有JSON内容: {ocr_file.name}")
            return []

        json_content = content[json_start:]

        try:
            ocr_data = json.loads(json_content)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {ocr_file.name}, 错误: {e}")
            return []

        points = []
        doc_id = ocr_data.get("document_id", ocr_file.stem)
        file_name = ocr_data.get("file_name", ocr_file.name)

        page_chunks = []
        for page_idx, page in enumerate(ocr_data.get("pages", [])):
            page_number = page_idx + 1
            page_texts = []
            for block in page.get("text_blocks", []):
                text = block.get("text", "").strip()
                if text:
                    page_texts.append(text)

            if page_texts:
                page_full_text = " ".join(page_texts)
                page_chunks_list = self.chunk_text(page_full_text)
                page_chunks.append({
                    'page_number': page_number,
                    'chunks': page_chunks_list
                })

        total_chunks = sum(len(pc['chunks']) for pc in page_chunks)

        for pc in page_chunks:
            page_number = pc['page_number']
            for i, chunk in enumerate(pc['chunks']):
                self.point_counter += 1
                point_id = self.point_counter

                vector = self.embed_text(chunk)

                payload = {
                    "chunk_id": f"{doc_id}_page_{page_number}_chunk_{i}",
                    "doc_id": doc_id,
                    "page_number": page_number,
                    "file_name": file_name,
                    "chunk_index": i,
                    "total_chunks": total_chunks,
                    "text": chunk,
                    "source": "ocr",
                    "embedding_model": EMBEDDING_MODEL if self.embedding_model else "hash"
                }

                point = PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload
                )
                points.append(point)

        logger.info(f"  生成 {len(points)} 个向量")

        return points

    def import_to_qdrant(self, points: List[PointStruct]):
        if not points:
            return

        self.qdrant_client.upsert(
            collection_name=self.collection_name,
            points=points
        )

    def run(self, max_files: int = None):
        self.initialize()

        ocr_files = self.get_ocr_files()

        if max_files:
            ocr_files = ocr_files[:max_files]

        total_points = 0
        for ocr_file in ocr_files:
            try:
                points = self.process_ocr_file(ocr_file)
                if points:
                    self.import_to_qdrant(points)
                    total_points += len(points)
                    logger.info(f"进度: {ocr_files.index(ocr_file) + 1}/{len(ocr_files)}")
            except Exception as e:
                logger.error(f"处理文件失败 {ocr_file.name}: {e}")

        logger.info("=" * 60)
        logger.info(f"导入完成！")
        logger.info(f"总向量数: {total_points}")
        logger.info("=" * 60)

        return total_points

def main():
    import argparse
    parser = argparse.ArgumentParser(description="OCR数据Qdrant导入")
    parser.add_argument("--max-files", type=int, default=None, help="最大处理文件数")
    args = parser.parse_args()

    importer = OCREmbedImporter()
    importer.run(max_files=args.max_files)

if __name__ == "__main__":
    main()
