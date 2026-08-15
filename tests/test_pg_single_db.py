#!/usr/bin/env python3
"""
测试 PG 单库增强功能
"""
import json
import os
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / 'src' / 'backend' / 'python-legacy'))

# 直接导入需要的函数，避免 sentence_transformers 依赖
def extract_period_from_filename(filename: str) -> str:
    """从文件名提取时期信息"""
    filename = filename.lower()

    # 匹配年月格式，如 2023-11, 2024年12月 等
    import re
    patterns = [
        r'(\d{4})-(\d{1,2})',  # 2023-11
        r'(\d{4})年(\d{1,2})月',  # 2024年1月
        r'(\d{4})(\d{1,2})',  # 202311
    ]

    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            year = match.group(1)
            month = match.group(2).zfill(2)  # 补齐月份
            return f"{year}-{month}"

    # 默认返回当前年月
    from datetime import datetime
    now = datetime.now()
    return f"{now.year}-{now.month:02d}"

def extract_period_from_page(page_text: str) -> str:
    """从页面文本提取时期信息"""
    import re

    # 匹配各种日期格式
    patterns = [
        r'(\d{4})年(\d{1,2})月',  # 2024年1月
        r'(\d{4})\.(\d{1,2})',   # 2024.1
        r'(\d{4})/(\d{1,2})',   # 2024/1
        r'(\d{4})-(\d{1,2})',   # 2024-1
    ]

    for pattern in patterns:
        match = re.search(pattern, page_text)
        if match:
            year = match.group(1)
            month = match.group(2).zfill(2)
            return f"{year}-{month}"

    return ""

def classify_doc_type(filename: str) -> str:
    """分类文档类型"""
    filename = filename.lower()

    # 价格相关文档
    price_keywords = ['信息价', '价格', '造价', '费用', '费率']
    if any(keyword in filename for keyword in price_keywords):
        return 'price'

    # 标准规范文档
    standard_keywords = ['标准', '规范', '规程', '办法', '指南']
    if any(keyword in filename for keyword in standard_keywords):
        return 'standard'

    # 默认分类
    return 'general'

def chunk_price_page(page_text: str, period: str, file_name: str,
                     max_chunk_size: int = 800) -> list:
    """
    信息价表格页专用分块：
    1. 每个 chunk 前缀带月份上下文
    2. 保持表格行完整性（不跨行切分）
    3. 按材料类别分组
    """
    chunks = []

    # 1. 提取表格行（假设 OCR 结果按行分割）
    lines = [line.strip() for line in page_text.split('\n') if line.strip()]

    # 2. 按材料类别分组
    current_category = ""
    category_chunks = []

    for line in lines:
        # 检测类别行（通常是标题行）
        if any(keyword in line for keyword in ['建筑材料', '安装材料', '市场劳务', '装配式构件']):
            if category_chunks:
                # 保存上一类别
                chunks.append(f"[{period}] {current_category}\n" + '\n'.join(category_chunks))
            current_category = line
            category_chunks = []
        else:
            category_chunks.append(line)

    # 保存最后一个类别
    if category_chunks:
        chunks.append(f"[{period}] {current_category}\n" + '\n'.join(category_chunks))

    # 3. 如果 chunk 太大，按材料分组切分
    final_chunks = []
    for chunk in chunks:
        if len(chunk) <= max_chunk_size:
            final_chunks.append(chunk)
        else:
            # 按材料行切分
            lines = chunk.split('\n')
            sub_chunk = ""
            for line in lines:
                if len(sub_chunk + line) > max_chunk_size and sub_chunk:
                    final_chunks.append(sub_chunk)
                    sub_chunk = f"[{period}] 续\n{line}"
                else:
                    sub_chunk += line + '\n'
            if sub_chunk:
                final_chunks.append(sub_chunk.rstrip())

    return final_chunks

def test_metadata_extraction():
    """测试元数据提取功能"""
    print("=== 测试元数据提取功能 ===")

    test_files = [
        "《深圳建设工程价格信息》2024年1月.pdf",
        "深圳市建设工程计价费率标准（2023）.pdf",
        "2025-02_ocr.json",
        "《市政工程造价文件分部分项和措施项目划分标准》.pdf"
    ]

    for filename in test_files:
        period = extract_period_from_filename(filename)
        doc_type = classify_doc_type(filename)
        print(f"文件: {filename}")
        print(f"  时期: {period}")
        print(f"  类型: {doc_type}")
        print()

def test_price_chunking():
    """测试价格分块功能"""
    print("=== 测试价格分块功能 ===")

    sample_price_text = """
建筑材料
钢筋 吨 4500.00
水泥 吨 380.00
砂子 立方米 120.00

安装材料
电线 米 15.00
水管 米 25.00

市场劳务
砌筑工 日 350.00
电工 日 400.00
"""

    chunks = chunk_price_page(sample_price_text, "2024-01", "深圳信息价2024年1月.pdf")
    print(f"生成了 {len(chunks)} 个分块:")
    for i, chunk in enumerate(chunks):
        print(f"分块 {i+1}:")
        print(chunk)
        print("-" * 50)

def test_ocr_parsing():
    """测试 OCR 数据解析"""
    print("=== 测试 OCR 数据解析 ===")

    ocr_dir = Path("data/ocr_outputs")
    if not ocr_dir.exists():
        print("OCR 数据目录不存在")
        return

    # 找一个小的 OCR 文件测试
    json_files = list(ocr_dir.glob("*.json"))
    if not json_files:
        print("没有找到 OCR JSON 文件")
        return

    # 选择第一个文件
    test_file = json_files[0]
    print(f"测试文件: {test_file.name}")

    try:
        with open(test_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        print(f"文档ID: {data.get('document_id', 'N/A')}")
        print(f"文件名: {data.get('file_name', 'N/A')}")

        pages = data.get("pages", [])
        print(f"页面数: {len(pages)}")

        if pages:
            page = pages[0]
            page_num = page.get("page_number", 0)
            print(f"第一页 (页码 {page_num}):")

            # 提取文本
            texts = []
            for block in page.get("text_blocks", []):
                txt = block.get("text", "").strip()
                if txt:
                    texts.append(txt)

            if texts:
                combined_text = "\n".join(texts[:5])  # 只显示前5个块
                print(f"文本预览:\n{combined_text}")
                if len(texts) > 5:
                    print("...")

                # 测试时期提取
                period = extract_period_from_page(combined_text)
                if period:
                    print(f"提取的时期: {period}")
                else:
                    print("未提取到时期信息")

    except Exception as e:
        print(f"解析失败: {e}")

if __name__ == "__main__":
    test_metadata_extraction()
    print()
    test_price_chunking()
    print()
    test_ocr_parsing()#!/usr/bin/env python3
"""
测试 PG 单库写入功能
"""
import sys
import os
sys.path.append('/home/l/rag-dashboard/src/backend/python-legacy')

from tools.unified_four_db_import import extract_period_from_filename, classify_doc_type, chunk_price_page
import json

def test_metadata_extraction():
    """测试元数据提取函数"""
    print("=== 测试元数据提取 ===")

    test_files = [
        "《深圳建设工程价格信息》2026年1月.pdf",
        "深圳市建设工程计价费率标准（2025）.pdf",
        "2025-01.json",
        "2023-11_chunk_001_ocr.json"
    ]

    for file_name in test_files:
        period = extract_period_from_filename(file_name)
        doc_type = classify_doc_type(file_name)
        print(f"文件: {file_name}")
        print(f"  时期: {period}")
        print(f"  类型: {doc_type}")
        print()

def test_price_chunking():
    """测试价格页面分块"""
    print("=== 测试价格页面分块 ===")

    sample_page = """
    建筑材料
    钢筋 Φ12 4.5 元/kg
    钢筋 Φ16 4.6 元/kg
    钢筋 Φ20 4.7 元/kg

    水泥
    425号水泥 450 元/吨
    525号水泥 480 元/吨

    安装材料
    水管 DN50 25 元/米
    电线 2.5平方 8 元/米
    """

    chunks = chunk_price_page(sample_page, "2026-01", "test.pdf")
    print(f"生成 {len(chunks)} 个块:")
    for i, chunk in enumerate(chunks):
        print(f"块 {i+1}: {chunk[:100]}...")
        print()

if __name__ == "__main__":
    test_metadata_extraction()
    test_price_chunking()
    print("测试完成!")