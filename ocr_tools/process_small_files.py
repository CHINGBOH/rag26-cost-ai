#!/usr/bin/env python3
"""
处理小文件 (<50MB) 使用同步端点
"""

import os
import json
import requests
import time
from pathlib import Path

# 配置
OCR_SERVICE_URL = "http://localhost:8001"
OCR_PDF_SYNC_ENDPOINT = f"{OCR_SERVICE_URL}/ocr/pdf"
OUTPUT_DIR = "/home/l/rag-dashboard/data/ocr_outputs"
SOURCE_DIRS = ['"/home/l/rag-dashboard/data/knowledge_base/深圳市建设工程地方标准"', '"/home/l/rag-dashboard/data/knowledge_base/深圳信息价"']

SMALL_FILE_THRESHOLD = 50  # MB

def get_small_files():
    """获取所有小于阈值的PDF文件"""
    small_files = []
    
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
                    output_json = os.path.join(OUTPUT_DIR, f"{base_name}_ocr.json")
                    
                    if file_size_mb < SMALL_FILE_THRESHOLD and not os.path.exists(output_json):
                        small_files.append(pdf_path)
    
    # 按大小排序
    small_files.sort(key=lambda x: os.path.getsize(x))
    return small_files

def process_pdf(pdf_path):
    """处理单个PDF文件"""
    file_name = os.path.basename(pdf_path)
    file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
    
    print(f"处理: {file_name} ({file_size_mb:.1f} MB)")
    
    try:
        with open(pdf_path, 'rb') as f:
            files = {'file': (file_name, f, 'application/pdf')}
            start_time = time.time()
            
            response = requests.post(OCR_PDF_SYNC_ENDPOINT, files=files, timeout=600)
            processing_time = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                
                # 保存结果
                base_name = os.path.splitext(file_name)[0]
                json_file = os.path.join(OUTPUT_DIR, f"{base_name}_ocr.json")
                text_file = os.path.join(OUTPUT_DIR, f"{base_name}_text.txt")
                
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                
                with open(text_file, 'w', encoding='utf-8') as f:
                    f.write(result.get('full_text', ''))
                
                pages = result.get('total_pages', 0)
                print(f"  ✓ 成功 - 页数: {pages}, 时间: {processing_time:.1f}秒")
                print(f"    保存到: {json_file}")
                
                return True
            else:
                print(f"  ✗ 失败 - HTTP {response.status_code}")
                return False
                
    except Exception as e:
        print(f"  ✗ 错误: {str(e)}")
        return False

def main():
    """主函数"""
    print("="*60)
    print("处理小文件 (<50MB)")
    print("="*60)
    
    # 获取小文件
    small_files = get_small_files()
    
    if not small_files:
        print("没有找到需要处理的小文件")
        return
    
    print(f"找到 {len(small_files)} 个小文件")
    print()
    
    # 处理文件
    successful = 0
    failed = 0
    
    for i, pdf_file in enumerate(small_files, 1):
        print(f"[{i}/{len(small_files)}] ", end="")
        
        if process_pdf(pdf_file):
            successful += 1
        else:
            failed += 1
        
        # 等待
        if i < len(small_files):
            time.sleep(3)
        
        print()
    
    print("="*60)
    print(f"处理完成: 成功 {successful}, 失败 {failed}")
    print("="*60)

if __name__ == "__main__":
    main()