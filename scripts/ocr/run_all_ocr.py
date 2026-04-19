#!/usr/bin/env python3
"""
批量 OCR 处理所有资料
处理项目中的所有 PDF 文档
"""

import os
import sys
import json
import uuid
from datetime import datetime
from pathlib import Path

# 设置环境
os.environ["PATH"] = "/home/l/miniconda3/envs/paddleocr/bin:" + os.environ.get("PATH", "")

# 文档目录
DOC_DIRS = [
    "/home/l/rag-dashboard/文档资料和别的ai写的后端代码参考/深圳市建设工程地方标准",
    "/home/l/rag-dashboard/文档资料和别的ai写的后端代码参考/深圳信息价",
]

OUTPUT_DIR = "/home/l/rag-dashboard/ocr_outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def find_all_pdfs():
    """查找所有 PDF 文件"""
    pdf_files = []
    for doc_dir in DOC_DIRS:
        if os.path.exists(doc_dir):
            for root, dirs, files in os.walk(doc_dir):
                for f in files:
                    if f.endswith('.pdf'):
                        pdf_files.append(os.path.join(root, f))
    return sorted(pdf_files)


def process_with_ocr_service(pdf_path):
    """使用 OCR 服务处理 PDF"""
    import requests
    import time
    
    url = "http://localhost:8001/ocr/pdf"
    
    try:
        with open(pdf_path, 'rb') as f:
            files = {'file': (os.path.basename(pdf_path), f, 'application/pdf')}
            response = requests.post(url, files=files, timeout=600)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"   ❌ OCR 服务错误: {response.status_code}")
            return None
    except Exception as e:
        print(f"   ❌ 请求失败: {e}")
        return None


def save_ocr_result(pdf_path, ocr_result):
    """保存 OCR 结果到文件"""
    filename = os.path.basename(pdf_path)
    base_name = os.path.splitext(filename)[0]
    output_file = os.path.join(OUTPUT_DIR, f"{base_name}.json")
    
    # 保存完整 JSON 结果
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(ocr_result, f, ensure_ascii=False, indent=2)
    
    # 同时保存 Markdown 格式
    md_file = os.path.join(OUTPUT_DIR, f"{base_name}.md")
    markdown = generate_markdown(ocr_result, filename)
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(markdown)
    
    return output_file, md_file


def generate_markdown(ocr_result, filename):
    """生成 Markdown 格式文档"""
    lines = [
        f"# {filename}",
        "",
        f"处理时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        ""
    ]
    
    if not ocr_result.get("success"):
        lines.append(f"处理失败: {ocr_result.get('error', 'Unknown error')}")
        return "\n".join(lines)
    
    pages = ocr_result.get("pages", [])
    lines.append(f"总页数: {len(pages)}")
    lines.append("")
    
    for page in pages:
        page_num = page.get("page_number", 0)
        lines.append(f"## 第 {page_num} 页")
        lines.append("")
        
        # 添加文本内容
        text = page.get("text", "")
        if text:
            lines.append(text)
            lines.append("")
        
        # 添加表格
        tables = page.get("tables", [])
        if tables:
            lines.append(f"*检测到 {len(tables)} 个表格*")
            lines.append("")
        
        lines.append("---")
        lines.append("")
    
    return "\n".join(lines)


def process_single_pdf(pdf_path, idx, total):
    """处理单个 PDF"""
    filename = os.path.basename(pdf_path)
    print(f"\n[{idx}/{total}] 处理: {filename}")
    
    # 检查是否已处理
    base_name = os.path.splitext(filename)[0]
    output_file = os.path.join(OUTPUT_DIR, f"{base_name}.json")
    if os.path.exists(output_file):
        print(f"   ⏭️  已处理过，跳过")
        return True
    
    try:
        # OCR 识别
        print(f"   → OCR 识别中...")
        ocr_result = process_with_ocr_service(pdf_path)
        
        if not ocr_result:
            print(f"   ❌ OCR 失败")
            return False
        
        if not ocr_result.get("success"):
            print(f"   ❌ OCR 失败: {ocr_result.get('error', 'Unknown')}")
            return False
        
        pages = ocr_result.get("pages", [])
        print(f"   ✓ 识别完成: {len(pages)} 页")
        
        # 保存结果
        json_file, md_file = save_ocr_result(pdf_path, ocr_result)
        print(f"   ✓ 结果保存: {os.path.basename(md_file)}")
        
        return True
        
    except Exception as e:
        print(f"   ❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("批量 OCR 处理所有资料")
    print("=" * 60)
    
    # 查找所有 PDF
    pdf_files = find_all_pdfs()
    total = len(pdf_files)
    
    print(f"\n找到 {total} 个 PDF 文件")
    print("-" * 60)
    
    for i, pdf in enumerate(pdf_files[:5], 1):  # 只显示前5个
        print(f"  {i}. {os.path.basename(pdf)}")
    if total > 5:
        print(f"  ... 还有 {total - 5} 个文件")
    
    print()
    
    # 处理统计
    success_count = 0
    failed_files = []
    
    # 批量处理
    for idx, pdf_path in enumerate(pdf_files, 1):
        if process_single_pdf(pdf_path, idx, total):
            success_count += 1
        else:
            failed_files.append(os.path.basename(pdf_path))
    
    # 统计
    print("\n" + "=" * 60)
    print("处理完成!")
    print("=" * 60)
    print(f"总计: {total}")
    print(f"成功: {success_count}")
    print(f"失败: {len(failed_files)}")
    print(f"输出目录: {OUTPUT_DIR}")
    
    if failed_files:
        print(f"\n失败文件:")
        for f in failed_files:
            print(f"  - {f}")
    
    return 0 if success_count == total else 1


if __name__ == "__main__":
    sys.exit(main())
