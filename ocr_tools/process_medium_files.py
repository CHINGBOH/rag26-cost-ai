#!/usr/bin/env python3
"""
处理中等文件 (50-200MB) 使用异步端点
"""

import os
import json
import requests
import time
from pathlib import Path

# 配置
OCR_SERVICE_URL = "http://localhost:8001"
OCR_PDF_SYNC_ENDPOINT = f"{OCR_SERVICE_URL}/ocr/pdf"
OCR_PDF_ASYNC_ENDPOINT = f"{OCR_SERVICE_URL}/ocr/pdf/async"
OUTPUT_DIR = "/home/l/rag-dashboard/data/ocr_outputs"
SOURCE_DIRS = ['"/home/l/rag-dashboard/data/knowledge_base/深圳市建设工程地方标准"', '"/home/l/rag-dashboard/data/knowledge_base/深圳信息价"']

MIN_FILE_SIZE = 50  # MB
MAX_FILE_SIZE = 200  # MB

def get_medium_files():
    """获取中等大小的PDF文件"""
    medium_files = []
    
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
                    
                    if (MIN_FILE_SIZE <= file_size_mb < MAX_FILE_SIZE and 
                        not os.path.exists(output_json)):
                        medium_files.append(pdf_path)
    
    # 按大小排序
    medium_files.sort(key=lambda x: os.path.getsize(x))
    return medium_files

def process_pdf_async(pdf_path):
    """使用异步端点处理PDF"""
    file_name = os.path.basename(pdf_path)
    file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
    
    print(f"处理: {file_name} ({file_size_mb:.1f} MB)")
    print("  启动异步任务...")
    
    try:
        # 启动异步任务
        with open(pdf_path, 'rb') as f:
            files = {'file': (file_name, f, 'application/pdf')}
            response = requests.post(OCR_PDF_ASYNC_ENDPOINT, files=files, timeout=30)
        
        if response.status_code != 200:
            print(f"  ✗ 启动失败: HTTP {response.status_code}")
            return False
        
        job_data = response.json()
        job_id = job_data.get('job_id')
        
        if not job_id:
            print(f"  ✗ 未获得任务ID")
            return False
        
        print(f"  任务ID: {job_id}")
        print("  等待处理完成...")
        
        # 轮询任务状态
        start_time = time.time()
        max_attempts = 120  # 10分钟
        
        for attempt in range(max_attempts):
            time.sleep(5)
            
            try:
                status_response = requests.get(f"{OCR_SERVICE_URL}/ocr/pdf/async/{job_id}", timeout=10)
                if status_response.status_code != 200:
                    continue
                
                status_data = status_response.json()
                status = status_data.get('status')
                
                if status == 'completed':
                    result = status_data.get('result')
                    processing_time = time.time() - start_time
                    
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
                    
                elif status == 'failed':
                    error = status_data.get('error', '未知错误')
                    print(f"  ✗ 任务失败: {error}")
                    return False
                    
                else:
                    elapsed = time.time() - start_time
                    print(f"  处理中... ({elapsed:.0f}秒)")
                    
            except Exception as e:
                print(f"  状态检查错误: {str(e)}")
                continue
        
        print(f"  ✗ 超时 (10分钟)")
        return False
        
    except Exception as e:
        print(f"  ✗ 处理错误: {str(e)}")
        return False

def main():
    """主函数"""
    print("="*60)
    print("处理中等文件 (50-200MB)")
    print("="*60)
    
    # 获取中等文件
    medium_files = get_medium_files()
    
    if not medium_files:
        print("没有找到需要处理的中等文件")
        return
    
    print(f"找到 {len(medium_files)} 个中等文件")
    print()
    
    # 处理文件
    successful = 0
    failed = 0
    
    for i, pdf_file in enumerate(medium_files, 1):
        print(f"[{i}/{len(medium_files)}] ", end="")
        
        if process_pdf_async(pdf_file):
            successful += 1
        else:
            failed += 1
        
        # 等待
        if i < len(medium_files):
            print("  等待10秒...")
            time.sleep(10)
        
        print()
    
    print("="*60)
    print(f"处理完成: 成功 {successful}, 失败 {failed}")
    print("="*60)

if __name__ == "__main__":
    main()