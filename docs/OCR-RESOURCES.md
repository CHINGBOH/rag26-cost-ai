# OCR 资源汇总 - PDF 图片格式处理方案

> 针对 RAG Dashboard 项目的 OCR 管道设计，特别整理 PDF 图片格式（图文表混排）的 OCR 解决方案

---

## 目录

1. [开源 OCR 框架对比](#1-开源-ocr-框架对比)
2. [PDF 处理工具](#2-pdf-处理工具)
3. [多模态文档理解模型](#3-多模态文档理解模型)
4. [表格识别专用方案](#4-表格识别专用方案)
5. [中文场景优化建议](#5-中文场景优化建议)
6. [推荐技术栈](#6-推荐技术栈)

---

## 1. 开源 OCR 框架对比

### 1.1 PaddleOCR (强烈推荐)

**GitHub**: https://github.com/PaddlePaddle/PaddleOCR  
**Stars**: 75.4k | **License**: Apache-2.0

#### 核心优势

- **中文场景最强**: 专门针对中文优化，支持 100+ 语言
- **PP-StructureV3**: 文档结构分析，支持表格、标题、段落识别
- **PaddleOCR-VL-1.5**: 0.9B 视觉语言模型，OmniDocBench 94.5% 准确率
- **端到端**: 检测 + 识别 + 版面分析一体化

#### 关键特性

```
- PP-OCRv5: 多语言识别模型，支持中英日韩等混合文档
- PP-StructureV3: 文档解析为 Markdown/JSON
- PP-DocLayoutV3: 不规则形状定位（扭曲、扫描、倾斜、光照、屏幕拍摄）
- 支持印章识别、公式识别、表格转 HTML
- 长文档自动跨页表格合并
```

#### 安装使用

```bash
pip install paddleocr

# 基础 OCR
from paddleocr import PaddleOCR
ocr = PaddleOCR(use_angle_cls=True, lang='ch')
result = ocr.ocr('image.jpg', cls=True)

# 文档结构分析
from paddleocr import PPStructure
engine = PPStructure(show_log=True)
result = engine(img)
```

#### 适用场景

| 场景 | 推荐模型 |
|------|----------|
| 通用文本识别 | PP-OCRv5 |
| 复杂文档解析 | PaddleOCR-VL-1.5 |
| 表格识别 | PP-StructureV3 |
| 版面分析 | PP-DocLayoutV3 |

---

### 1.2 Tesseract OCR

**GitHub**: https://github.com/tesseract-ocr/tesseract  
**Stars**: 73.4k | **License**: Apache-2.0

#### 特点

- **历史悠久**: 1985-1994 HP 开发，2005 开源
- **LSTM 引擎**: Tesseract 4+ 使用神经网络
- **100+ 语言**: 开箱即用多语言支持
- **多种输出**: 纯文本、hOCR、PDF、TSV、ALTO、PAGE

#### 局限性

```
- 中文识别准确率不如 PaddleOCR
- 复杂版面（表格、多栏）处理能力有限
- 需要图像预处理才能获得较好效果
- 对扫描件、低质量图片敏感
```

#### 安装使用

```bash
# Ubuntu
sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim

# Python
pip install pytesseract

import pytesseract
from PIL import Image

text = pytesseract.image_to_string(Image.open('image.jpg'), lang='chi_sim+eng')
```

---

### 1.3 EasyOCR

**GitHub**: https://github.com/JaidedAI/EasyOCR  
**Stars**: 29.3k | **License**: Apache-2.0

#### 特点

- **即用即走**: 两行代码完成 OCR
- **80+ 语言**: 支持拉丁、中文、阿拉伯、梵文、西里尔等
- **PyTorch 基础**: CRAFT 检测 + CRNN 识别

#### 安装使用

```python
import easyocr

# 加载模型（首次运行自动下载）
reader = easyocr.Reader(['ch_sim', 'en'])

# 识别
result = reader.readtext('image.jpg', detail=1)
# 返回: [(bbox, text, confidence), ...]
```

#### 局限性

```
- 中文准确率中等，不如 PaddleOCR
- 不支持文档结构分析
- 表格识别能力弱
- 仅适合简单场景文本识别
```

---

## 2. PDF 处理工具

### 2.1 PyMuPDF (fitz)

**GitHub**: https://github.com/pymupdf/PyMuPDF  
**Stars**: 9.4k | **License**: AGPL-3.0 / Commercial

#### 核心功能

```python
import pymupdf

# 打开 PDF
doc = pymupdf.open("example.pdf")

# 提取文本（保留布局）
for page in doc:
    text = page.get_text("dict")  # 结构化输出
    
# 转换为图片（用于 OCR）
pix = page.get_pixmap(dpi=300)
pix.save("page.png")

# 提取图片
images = page.get_images()
```

#### 优势

- **高性能**: 基于 MuPDF，速度快
- **功能全面**: 文本提取、图片提取、渲染、编辑
- **支持多种格式**: PDF、XPS、EPUB、CBZ
- **可选 OCR 集成**: 内置 Tesseract 支持

---

### 2.2 pdfplumber

**GitHub**: https://github.com/jsvine/pdfplumber  
**Stars**: 10.1k | **License**: MIT

#### 核心功能

```python
import pdfplumber

with pdfplumber.open("file.pdf") as pdf:
    page = pdf.pages[0]
    
    # 提取文本
    text = page.extract_text()
    
    # 提取表格
    tables = page.extract_tables()
    
    # 获取字符级信息
    chars = page.chars
    
    # 可视化调试
    im = page.to_image()
    im.draw_rects(page.extract_words())
    im.save("debug.png")
```

#### 优势

- **机器生成 PDF 友好**: 保留文本布局信息
- **表格提取**: 内置表格检测算法
- **可视化调试**: 便于理解 PDF 结构
- **字符级信息**: 字体、位置、颜色等

#### 局限

- 扫描版 PDF 需要配合 OCR
- 复杂表格识别能力有限

---

### 2.3 pdf2image

**用途**: 将 PDF 页面转换为图片（供 OCR 使用）

```python
from pdf2image import convert_from_path

# 转换为 PIL Image 列表
images = convert_from_path(
    'document.pdf',
    dpi=300,           # 分辨率
    fmt='png',         # 格式
    thread_count=4     # 并行处理
)

# 保存
for i, img in enumerate(images):
    img.save(f'page_{i}.png')
```

---

## 3. 多模态文档理解模型

### 3.1 LayoutLMv3

**GitHub**: https://github.com/microsoft/unilm/tree/master/layoutlmv3  
**Stars**: 22.1k (unilm) | **License**: CC BY-NC-SA 4.0

#### 特点

- **微软出品**: 文档 AI 基础模型
- **统一预训练**: 文本和图像掩码联合训练
- **多任务**: 表单理解、文档分类、布局分析、VQA

#### 预训练模型

| 模型 | 链接 |
|------|------|
| layoutlmv3-base | microsoft/layoutlmv3-base |
| layoutlmv3-large | microsoft/layoutlmv3-large |
| layoutlmv3-base-chinese | microsoft/layoutlmv3-base-chinese |

#### 适用场景

```
- 表单信息抽取（FUNSD、CORD）
- 文档布局分析（PubLayNet）
- 文档视觉问答（DocVQA）
- 文档分类（RVL-CDIP）
```

---

### 3.2 Donut

**GitHub**: https://github.com/clovaai/donut  
**Stars**: 6.8k | **License**: MIT

#### 特点

- **OCR-Free**: 无需 OCR，端到端文档理解
- **SynthDoG**: 合成文档生成器，支持中英日韩
- **统一架构**: 所有任务都是 JSON 预测问题

#### 预训练模型

| 任务 | 模型 | 准确率 |
|------|------|--------|
| 文档解析 (CORD) | donut-base-finetuned-cord-v2 | 91.3% |
| 文档分类 (RVL-CDIP) | donut-base-finetuned-rvlcdip | 95.3% |
| 文档 VQA (DocVQA) | donut-base-finetuned-docvqa | 67.5% |

#### 使用示例

```python
from transformers import DonutProcessor, VisionEncoderDecoderModel

processor = DonutProcessor.from_pretrained("naver-clova-ix/donut-base-finetuned-cord-v2")
model = VisionEncoderDecoderModel.from_pretrained("naver-clova-ix/donut-base-finetuned-cord-v2")

# 处理图片 -> 生成结构化 JSON
```

---

### 3.3 Nougat

**GitHub**: https://github.com/facebookresearch/nougat  
**Stars**: 9.9k | **License**: MIT (code) / CC-BY-NC (model)

#### 特点

- **Meta 出品**: 学术论文 PDF 解析专用
- **LaTeX 理解**: 识别数学公式和表格
- **Markdown 输出**: 生成 .mmd 格式

#### 局限

```
- 仅支持英文论文
- 中文、日文、俄文等不支持
- 需要 GPU 获得最佳效果
```

#### 使用

```bash
pip install nougat-ocr

# CLI
nougat path/to/file.pdf -o output_directory

# API
nougat_api  # 启动服务
curl -X POST 'http://127.0.0.1:8503/predict/' -F 'file=@paper.pdf'
```

---

## 4. 表格识别专用方案

### 4.1 Table Transformer (TATR)

**GitHub**: https://github.com/microsoft/table-transformer  
**Stars**: 2.9k | **License**: MIT

#### 特点

- **微软出品**: 基于 DETR 的表格检测和结构识别
- **PubTables-1M**: 百万级表格数据集训练
- **GriTS 评估**: 网格表格相似度指标

#### 预训练模型

| 模型 | 训练数据 | 用途 |
|------|----------|------|
| TATR-v1.0 | PubTables-1M | 表格检测 |
| TATR-v1.1-Pub | PubTables-1M | 表格结构识别 |
| TATR-v1.1-Fin | FinTabNet.c | 金融表格 |
| TATR-v1.1-All | 两者合并 | 通用 |

#### 使用流程

```
1. 表格检测 -> 裁剪表格区域
2. OCR 提取表格内文本
3. 表格结构识别 -> 单元格位置
4. 文本与单元格对齐 -> HTML/CSV
```

---

### 4.2 PaddleOCR 表格识别

```python
from paddleocr import PPStructure

engine = PPStructure(show_log=True)
result = engine(img)

# 输出包含
# - 表格区域坐标
# - 表格 HTML
# - 单元格文本
```

---

## 5. 中文场景优化建议

### 5.1 推荐组合方案

**方案 A: 纯中文文档（最高准确率）**

```
PDF 解析: PyMuPDF / pdfplumber
图片转换: pdf2image (300 DPI)
OCR 引擎: PaddleOCR (PP-OCRv5 + PP-StructureV3)
表格识别: PP-StructureV3
版面分析: PP-DocLayoutV3
```

**方案 B: 中英混合文档**

```
PDF 解析: PyMuPDF
OCR 引擎: PaddleOCR (lang='ch')
后处理: 正则表达式清洗
```

**方案 C: 学术论文（英文）**

```
PDF 解析: Nougat
公式识别: Nougat 内置
表格识别: Table Transformer
```

### 5.2 图像预处理建议

```python
import cv2
import numpy as np

def preprocess_for_ocr(image):
    """OCR 前图像预处理"""
    # 1. 灰度化
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # 2. 去噪
    denoised = cv2.fastNlMeansDenoising(gray)
    
    # 3. 二值化（自适应）
    binary = cv2.adaptiveThreshold(
        denoised, 255, 
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )
    
    # 4. 倾斜校正
    coords = np.column_stack(np.where(binary > 0))
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    
    (h, w) = binary.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(binary, M, (w, h),
                             flags=cv2.INTER_CUBIC,
                             borderMode=cv2.BORDER_REPLICATE)
    
    return rotated
```

### 5.3 后处理清洗

```python
import re

def clean_ocr_text(text):
    """OCR 结果清洗"""
    # 1. 去除多余空格
    text = re.sub(r'\s+', ' ', text)
    
    # 2. 修复常见 OCR 错误
    replacements = {
        '「': '"',
        '」': '"',
        '『': "'",
        '』': "'",
        '—': '-',
        '……': '...',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    # 3. 去除乱码字符
    text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s\n\.,;:!?"\'()-]', '', text)
    
    return text.strip()
```

---

## 6. 推荐技术栈

### 6.1 针对 RAG Dashboard 的建议

```yaml
# 文档处理管道
pipeline:
  # 1. PDF 解析与转换
  pdf_parser: PyMuPDF
  image_converter: pdf2image
  
  # 2. OCR 引擎（核心）
  ocr_engine: PaddleOCR
  ocr_config:
    lang: ch
    use_angle_cls: true
    use_gpu: true
    
  # 3. 文档结构分析
  layout_analysis: PP-StructureV3
  table_recognition: PP-StructureV3
  
  # 4. 文本后处理
  text_cleaner: custom_cleaner
  
  # 5. 向量化存储
  embedding: text2vec / m3e
  vector_store: Qdrant
```

### 6.2 安装依赖

```bash
# 核心 OCR
pip install paddleocr paddlepaddle-gpu

# PDF 处理
pip install pymupdf pdfplumber pdf2image

# 图像处理
pip install pillow opencv-python

# 多模态模型（可选）
pip install transformers torch

# 表格识别（可选）
pip install timm
```

### 6.3 性能优化建议

```python
# 1. GPU 加速
import paddle
paddle.utils.run_check()

# 2. 批量处理
from multiprocessing import Pool

def process_page(args):
    page_num, image = args
    result = ocr.ocr(image)
    return page_num, result

with Pool(processes=4) as pool:
    results = pool.map(process_page, page_images)

# 3. 缓存机制
from functools import lru_cache

@lru_cache(maxsize=128)
def get_ocr_result(image_hash):
    return ocr.ocr(image)
```

---

## 参考链接

| 资源 | 链接 |
|------|------|
| PaddleOCR 文档 | https://paddlepaddle.github.io/PaddleOCR/ |
| PaddleOCR 模型库 | https://www.paddleocr.com |
| PyMuPDF 文档 | https://pymupdf.readthedocs.io |
| LayoutLMv3 | https://huggingface.co/microsoft/layoutlmv3-base-chinese |
| Table Transformer | https://huggingface.co/bsmock/TATR-v1.1-All |

---

**最后更新**: 2026-04-11
