"""
OCR Pipeline 配置管理
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List


@dataclass
class OCRConfig:
    """OCR引擎配置"""
    engine: str = "rapidocr"  # rapidocr | paddleocr
    dpi: int = 200
    cuda_lib_path: str = "/usr/local/lib/ollama/cuda_v12"
    y_threshold: int = 22  # 行聚类阈值(像素)
    x_threshold: int = 30  # 列聚类阈值(像素)


@dataclass
class DBConfig:
    """数据库配置"""
    host: str = "localhost"
    port: int = 5432
    dbname: str = "rag_db"
    user: str = "rag_user"
    password: str = os.environ.get("POSTGRES_PASSWORD", "rag_password")


@dataclass
class EmbeddingConfig:
    """Embedding配置"""
    backend: str = "local"  # local | tei | ollama
    tei_url: str = "http://localhost:8003/embed"
    ollama_url: str = "http://localhost:11434/api/embeddings"
    ollama_model: str = "qwen2.5:7b-instruct"
    local_model_path: str = ""
    dimension: int = 1024
    batch_size: int = 32


@dataclass
class PipelineConfig:
    """Pipeline全局配置"""
    ocr: OCRConfig = field(default_factory=OCRConfig)
    db: DBConfig = field(default_factory=DBConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    output_dir: Path = field(default_factory=lambda: Path("/home/l/rag-dashboard/data/ocr_outputs"))
    charts_dir: Path = field(default_factory=lambda: Path("/home/l/rag-dashboard/data/ocr_outputs/charts"))
    quarantine_threshold: float = 0.6  # 置信度低于此值进入隔离区
    price_max: float = 10_000_000.0
    price_min: float = 0.0
    enable_gpu: bool = True
    enable_embedding: bool = True
    resume: bool = True  # 断点续传
    max_workers: int = 1
    # Chart Vector Extraction 配置
    enable_chart_vector: bool = True  # 启用PDF矢量路径提取趋势图数据点
    chart_vector_configs: dict = field(default_factory=dict)  # {doc_code: {page_num: [subchart_configs]}}

    def __post_init__(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.charts_dir.mkdir(parents=True, exist_ok=True)
        # 自动设置CUDA环境
        if self.ocr.cuda_lib_path and os.path.exists(self.ocr.cuda_lib_path):
            ld = os.environ.get("LD_LIBRARY_PATH", "")
            if self.ocr.cuda_lib_path not in ld:
                os.environ["LD_LIBRARY_PATH"] = f"{self.ocr.cuda_lib_path}:{ld}"


def load_config_from_env() -> PipelineConfig:
    """从环境变量加载配置"""
    cfg = PipelineConfig()
    cfg.db.host = os.getenv("POSTGRES_HOST", cfg.db.host)
    cfg.db.port = int(os.getenv("POSTGRES_PORT", cfg.db.port))
    cfg.db.dbname = os.getenv("POSTGRES_DB", cfg.db.dbname)
    cfg.db.user = os.getenv("POSTGRES_USER", cfg.db.user)
    cfg.db.password = os.getenv("POSTGRES_PASSWORD", cfg.db.password)
    cfg.embedding.tei_url = os.getenv("TEI_URL", cfg.embedding.tei_url)
    cfg.embedding.ollama_url = os.getenv("OLLAMA_URL", cfg.embedding.ollama_url)
    cfg.ocr.engine = os.getenv("OCR_ENGINE", cfg.ocr.engine)
    return cfg
