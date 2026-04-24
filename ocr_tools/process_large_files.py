#!/usr/bin/env python3
"""
处理大文件 (>200MB) - 先拆分再处理
使用PyMuPDF进行PDF拆分
"""

import os
import json
import requests
import time
import tempfile
import shutil
import subprocess
from pathlib import Path

# 配置
OCR_SERVICE_URL = "http://localhost:8001"
OCR_PDF_SYNC_ENDPOINT = f"{OCR_SERVICE_URL}/ocr/pdf"
OUTPUT_DIR = "/home/l/rag-dashboard/data/ocr_outputs"
SOURCE_DIRS = ['"/home/l/rag-dashboard/data/knowledge_base/深圳市建设工程地方标准"', '"/home/l/rag-dashboard/data/knowledge_base/深圳信息价"']

LARGE_FILE_THRESHOLD = 200  # MB
PAGES_PER_CHUNK = 50  # 每个分块的页数

def get_large_files():
    """获取大PDF文件"""
    large_files = []
    
    for directory in SOURCE_DIRS:
        if not os.path.exists(directory):
            continue
            
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.lower().endswith('.pdf'):
                    pdf_path = os.path.join(root, file)
                    file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
                    
                    # 检查是否已处理
                    base_name = os.path.splitext(file)[0]
                    output_json = os.path.join(OUTPUT_DIR, f"{base_name}_merged_ocr.json")
                    
                    if file_size_mb >= LARGE_FILE_THRESHOLD and not os.path.exists(output_json):
                        large_files.append(pdf_path)
    
    # 按大小排序
    large_files.sort(key=lambda x: os.path.getsize(x))
    return large_files

def get_pdf_page_count(pdf_path):
    """获取PDF文件页数"""
    try:
        # 使用pdfinfo获取页数
        result = subprocess.run(['pdfinfo', pdf_path], capture_output=True, text=True)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if line.startswith('Pages:'):
                    return int(line.split(':')[1].strip())
    except Exception:
        pass
    
    # 如果pdfinfo不可用，使用估算
    file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
    return int(file_size_mb * 2)  # 粗略估算

def split_pdf(pdf_path, output_dir, pages_per_chunk=PAGES_PER_CHUNK):
    """拆分PDF文件"""
    try:
        page_count = get_pdf_page_count(pdf_path)
        
        if page_count <= pages_per_chunk:
            return [pdf_path], None  # 不需要拆分
        
        chunks = []
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        temp_dir = tempfile.mkdtemp(prefix=f"pdf_chunks_{base_name}_", dir=output_dir)
        
        print(f"  文件页数: {page_count}, 拆分为每块 {pages_per_chunk} 页")
        
        # 使用pdfseparate拆分每一页
        all_pages_dir = os.path.join(temp_dir, "all_pages")
        os.makedirs(all_pages_dir, exist_ok=True)
        
        subprocess.run(['pdfseparate', pdf_path, f"{all_pages_dir}/page-%d.pdf"], 
                      check=True, capture_output=True)
        
        # 合并页面为块
        page_files = sorted([f for f in os.listdir(all_pages_dir) if f.endswith('.pdf')])
        
        for i in range(0, len(page_files), pages_per_chunk):
            chunk_pages = page_files[i:i+pages_per_chunk]
            chunk_start = i + 1
            chunk_end = i + len(chunk_pages)
            
            chunk_name = f"{base_name}_chunk_{chunk_start:03d}_{chunk_end:03d}.pdf"
            chunk_path = os.path.join(temp_dir, chunk_name)
            
            # 合并页面
            page_paths = [os.path.join(all_pages_dir, page) for page in chunk_pages]
            subprocess.run(['pdfunite'] + page_paths + [chunk_path], 
                          check=True, capture_output=True)
            
            chunks.append(chunk_path)
            print(f"  创建块: {chunk_name} (页 {chunk_start}-{chunk_end})")
        
        return chunks, temp_dir
        
    except Exception as e:
        print(f"  拆分失败: {str(e)}")
        return [pdf_path], None

def process_pdf_sync(pdf_path):
    """处理单个PDF文件"""
    file_name = os.path.basename(pdf_path)
    
    try:
        with open(pdf_path, 'rb') as f:
            files = {'file': (file_name, f, 'application/pdf')}
            response = requests.post(OCR_PDF_SYNC_ENDPOINT, files=files, timeout=600)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"    ✗ 处理失败: HTTP {response.status_code}")
            return None
            
    except Exception as e:
        print(f"    ✗ 处理错误: {str(e)}")
        return None

def merge_chunk_results(base_name, output_dir):
    """合并分块结果"""
    # 查找所有分块结果
    chunk_files = []
    for file in os.listdir(output_dir):
        if file.startswith(base_name) and file.endswith('_chunk_') and file.endswith('_ocr.json'):
            chunk_files.append(os.path.join(output_dir, file))
    
    if not chunk_files:
        return None
    
    # 按块号排序
    chunk_files.sort()
    
    # 合并结果
    merged_result = {
        'document_id': f"merged_{base_name}",
        'file_name': f"{base_name}.pdf",
        'total_pages': 0,
        'pages': [],
        'full_text': '',
        'processing_time': 0,
        'chunks_processed': len(chunk_files)
    }
    
    for chunk_file in chunk_files:
        try:
            with open(chunk_file, 'r', encoding='utf-8') as f:
                chunk_data = json.load(f)
            
            # 合并页面
            if 'pages' in chunk_data:
                merged_result['pages'].extend(chunk_data['pages'])
                merged_result['total_pages'] += chunk_data.get('total_pages', 0)
            
            # 合并文本
            if 'full_text' in chunk_data:
                merged_result['full_text'] += chunk_data['full_text'] + "\n\n"
            
            # 累加处理时间
            merged_result['processing_time'] += chunk_data.get('processing_time', 0)
            
        except Exception as e:
            print(f"    读取块文件错误: {e}")
    
    # 保存合并结果
    merged_json = os.path.join(output_dir, f"{base_name}_merged_ocr.json")
    with open(merged_json, 'w', encoding='utf-8') as f:
        json.dump(merged_result, f, ensure_ascii=False, indent=2)
    
    merged_text = os.path.join(output_dir, f"{base_name}_merged_text.txt")
    with open(merged_text, 'w', encoding='utf-8') as f:
        f.write(merged_result['full_text'])
    
    return merged_json, merged_text

def process_large_file(pdf_path, output_dir):
    """处理大文件"""
    file_name = os.path.basename(pdf_path)
    file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
    
    print(f"处理: {file_name} ({file_size_mb:.1f} MB)")
    
    start_time = time.time()
    
    # 拆分PDF
    chunks, temp_dir = split_pdf(pdf_path, output_dir)
    
    if len(chunks) == 1 and chunks[0] == pdf_path:
        print("  文件不需要拆分，直接处理")
        result = process_pdf_sync(pdf_path)
        
        if result:
            # 保存结果
            base_name = os.path.splitext(file_name)[0]
            json_file = os.path.join(output_dir, f"{base_name}_ocr.json")
            text_file = os.path.join(output_dir, f"{base_name}_text.txt")
            
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            with open(text_file, 'w', encoding='utf-8') as f:
                f.write(result.get('full_text', ''))
            
            processing_time = time.time() - start_time
            pages = result.get('total_pages', 0)
            print(f"  ✓ 成功 - 页数: {pages}, 时间: {processing_time:.1f}秒")
            print(f"    保存到: {json_file}")
            return True
        else:
            return False
    else:
        print(f"  拆分为 {len(chunks)} 个块")
        
        # 处理每个块
        chunk_results = []
        base_name = os.path.splitext(file_name)[0]
        
        for i, chunk_path in enumerate(chunks, 1):
            chunk_name = os.path.basename(chunk_path)
            print(f"  处理块 {i}/{len(chunks)}: {chunk_name}")
            
            result = process_pdf_sync(chunk_path)
            if result:
                # 保存块结果
                chunk_base = f"{base_name}_chunk_{i:03d}"
                chunk_json = os.path.join(output_dir, f"{chunk_base}_ocr.json")
                
                with open(chunk_json, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                
                chunk_results.append(result)
                print(f"    ✓ 块 {i} 处理成功")
            else:
                print(f"    ✗ 块 {i} 处理失败")
            
            # 等待
            if i < len(chunks):
                time.sleep(3)
        
        # 清理临时目录
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        
        # 合并结果
        if chunk_results:
            print("  合并块结果...")
            merged_files = merge_chunk_results(base_name, output_dir)
            
            if merged_files:
                processing_time = time.time() - start_time
                print(f"  ✓ 成功 - 处理了 {len(chunk_results)} 个块, 总时间: {processing_time:.1f}秒")
                print(f"    保存到: {merged_files[0]}")
                return True
            else:
                print("  ✗ 合并结果失败")
                return False
        else:
            print("  ✗ 所有块都处理失败")
            return False

def main():
    """主函数"""
    print("="*60)
    print("处理大文件 (>200MB)")
    print("="*60)
    
    # 检查pdf工具
    try:
        subprocess.run(['pdfinfo', '--version'], check=True, capture_output=True)
        subprocess.run(['pdfseparate', '--version'], check=True, capture_output=True)
        subprocess.run(['pdfunite', '--version'], check=True, capture_output=True)
    except Exception:
        print("错误: 需要安装 poppler-utils 工具")
        print("  sudo apt-get install poppler-utils")
        return
    
    # 获取大文件
    large_files = get_large_files()
    
    if not large_files:
        print("没有找到需要处理的大文件")
        return
    
    print(f"找到 {len(large_files)} 个大文件")
    print()
    
    # 处理文件
    successful = 0
    failed = 0
    
    for i, pdf_file in enumerate(large_files, 1):
        print(f"[{i}/{len(large_files)}] ", end="")
        
        if process_large_file(pdf_file, OUTPUT_DIR):
            successful += 1
        else:
            failed += 1
        
        # 等待
        if i < len(large_files):
            print("  等待10秒...")
            time.sleep(10)
        
        print()
    
    print("="*60)
    print(f"处理完成: 成功 {successful}, 失败 {failed}")
    print("="*60)

if __name__ == "__main__":
    main()