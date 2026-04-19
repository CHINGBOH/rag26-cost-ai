"""
文档类型定义
"""

from typing import List, Dict, Optional, Any
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    PDF = "pdf"
    IMAGE = "image"
    TEXT = "text"
    MARKDOWN = "markdown"


class ChunkType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    FORMULA = "formula"
    CODE = "code"
    TITLE = "title"


class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float
    page: int = Field(default=1)


class OCRResult(BaseModel):
    text: str
    confidence: float
    bbox: Optional[BoundingBox] = None
    block_type: str = Field(default="text")


class DocumentMetadata(BaseModel):
    doc_id: str
    title: str
    source: str
    doc_type: DocumentType = Field(default=DocumentType.PDF)
    total_pages: int = Field(default=0)
    file_size: int = Field(default=0)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    author: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)


class DocumentChunk(BaseModel):
    chunk_id: str
    doc_id: str
    content: str
    chunk_type: ChunkType = Field(default=ChunkType.TEXT)
    page_number: int = Field(default=1)
    bbox: Optional[BoundingBox] = None
    section: Optional[str] = None

    # 向量相关
    embedding: Optional[List[float]] = None
    embedding_model: Optional[str] = None

    # 增强信息
    keywords: List[str] = Field(default_factory=list)
    entities: List[Dict[str, Any]] = Field(default_factory=list)
    summary: Optional[str] = None

    # 上下文
    prev_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None
    context_window: int = Field(default=2)

    # 元数据
    confidence: float = Field(default=1.0)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "content": self.content,
            "chunk_type": self.chunk_type.value,
            "page_number": self.page_number,
            "section": self.section,
            "keywords": self.keywords,
            "entities": self.entities,
            "confidence": self.confidence,
        }


class Document(BaseModel):
    metadata: DocumentMetadata
    chunks: List[DocumentChunk] = Field(default_factory=list)
    raw_content: Optional[str] = None

    def to_chunks(self) -> List[DocumentChunk]:
        return self.chunks

    def get_chunk(self, chunk_id: str) -> Optional[DocumentChunk]:
        for chunk in self.chunks:
            if chunk.chunk_id == chunk_id:
                return chunk
        return None
