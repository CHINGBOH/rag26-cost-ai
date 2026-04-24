#!/usr/bin/env python3
"""
OCR处理报告生成工具
生成详细的处理报告和统计信息
"""

import os
import json
import time
from pathlib import Path
from datetime import datetime

OUTPUT_DIR = "/home/l/知识库测试资料/ocr_results"
SOURCE_DIRS = [
    "/home/l/知识库测试资料/深圳市建设工程地方标准",
    "/home/l/知识库测试资料/深圳信息价"
]

def get_all_pdfs():
    """获取所有PDF文件"""
    all_pdfs = []
    
    for directory in SOURCE_DIRS:
        if not os.path.exists(directory):
            continue
            
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.lower().endswith('.pdf'):
                    pdf_path = os.path.join(root, file)
                    file_size = os.path.getsize(pdf_path)
                    all_pdfs.append({
                        'path': pdf_path,
                        'name': file,
                        'size': file_size,
                        'size_mb': file_size / (1024 * 1024)
                    })
    
    return all_pdfs

def get_processed_files():
    """获取已处理的文件"""
    processed_files = []
    
    for file in os.listdir(OUTPUT_DIR):
        if file.endswith('_ocr.json') and not file.startswith('processing'):
            file_path = os.path.join(OUTPUT_DIR, file)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                processed_files.append({
                    'file_name': file,
                    'data': data,
                    'size': os.path.getsize(file_path),
                    'size_kb': os.path.getsize(file_path) / 1024
                })
            except Exception:
                pass
    
    return processed_files

def categorize_files(all_pdfs, processed_files):
    """分类文件"""
    processed_names = set()
    for pf in processed_files:
        base_name = pf['file_name'].replace('_ocr.json', '')
        processed_names.add(base_name)
    
    categories = {
        'small': [],      # < 50MB
        'medium': [],     # 50-200MB
        'large': []       # > 200MB
    }
    
    unprocessed = {
        'small': [],
        'medium': [],
        'large': []
    }
    
    for pdf in all_pdfs:
        base_name = pdf['name'].replace('.pdf', '')
        size_mb = pdf['size_mb']
        
        # 分类
        if size_mb < 50:
            category = 'small'
        elif size_mb < 200:
            category = 'medium'
        else:
            category = 'large'
        
        # 检查是否已处理
        is_processed = any(base_name in pf['file_name'] for pf in processed_files)
        
        if is_processed:
            categories[category].append(pdf)
        else:
            unprocessed[category].append(pdf)
    
    return categories, unprocessed, processed_files

def generate_statistics(categories, unprocessed, processed_files):
    """生成统计信息"""
    # 总文件数
    total_pdfs = sum(len(files) for files in categories.values()) + \
                 sum(len(files) for files in unprocessed.values())
    
    # 已处理文件数
    total_processed = sum(len(files) for files in categories.values())
    
    # 未处理文件数
    total_unprocessed = sum(len(files) for files in unprocessed.values())
    
    # 处理成功率
    success_rate = (total_processed / total_pdfs * 100) if total_pdfs > 0 else 0
    
    # 文件大小统计
    total_size = sum(f['size'] for f in sum(categories.values() + list(unprocessed.values()), []))
    processed_size = sum(f['size'] for f in sum(categories.values(), []))
    
    # 页数统计
    total_pages = sum(pf['data'].get('total_pages', 0) for pf in processed_files)
    avg_pages_per_file = total_pages / total_processed if total_processed > 0 else 0
    
    # 处理时间统计
    total_time = sum(pf['data'].get('processing_time', 0) for pf in processed_files)
    avg_time = total_time / total_processed if total_processed > 0 else 0
    avg_time_per_page = total_time / total_pages if total_pages > 0 else 0
    
    # 输出文件大小
    total_output_size = sum(pf['size'] for pf in processed_files)
    
    return {
        'total_files': total_pdfs,
        'processed_files': total_processed,
        'unprocessed_files': total_unprocessed,
        'success_rate': success_rate,
        'total_size_mb': total_size / (1024 * 1024),
        'processed_size_mb': processed_size / (1024 * 1024),
        'total_pages': total_pages,
        'avg_pages_per_file': avg_pages_per_file,
        'total_time_seconds': total_time,
        'avg_time_per_file_seconds': avg_time,
        'avg_time_per_page_seconds': avg_time_per_page,
        'total_output_size_mb': total_output_size / (1024 * 1024),
        'categories': {
            'small': {
                'total': len(categories['small']) + len(unprocessed['small']),
                'processed': len(categories['small']),
                'unprocessed': len(unprocessed['small'])
            },
            'medium': {
                'total': len(categories['medium']) + len(unprocessed['medium']),
                'processed': len(categories['medium']),
                'unprocessed': len(unprocessed['medium'])
            },
            'large': {
                'total': len(categories['large']) + len(unprocessed['large']),
                'processed': len(categories['large']),
                'unprocessed': len(unprocessed['large'])
            }
        }
    }

def generate_markdown_report(stats, categories, unprocessed, processed_files):
    """生成Markdown格式报告"""
    report = []
    report.append("# OCR处理报告")
    report.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")
    
    # 概览
    report.append("## 处理概览")
    report.append(f"- **总文件数**: {stats['total_files']}")
    report.append(f"- **已处理文件**: {stats['processed_files']} ({stats['success_rate']:.1f}%)")
    report.append(f"- **未处理文件**: {stats['unprocessed_files']}")
    report.append(f"- **总页数**: {stats['total_pages']}")
    report.append(f"- **总处理时间**: {stats['total_time_seconds']:.1f}秒")
    report.append("")
    
    # 按类别统计
    report.append("## 文件分类统计")
    report.append("### 小文件 (<50MB)")
    report.append(f"- 总数: {stats['categories']['small']['total']}")
    report.append(f"- 已处理: {stats['categories']['small']['processed']}")
    report.append(f"- 未处理: {stats['categories']['small']['unprocessed']}")
    report.append("")
    
    report.append("### 中等文件 (50-200MB)")
    report.append(f"- 总数: {stats['categories']['medium']['total']}")
    report.append(f"- 已处理: {stats['categories']['medium']['processed']}")
    report.append(f"- 未处理: {stats['categories']['medium']['unprocessed']}")
    report.append("")
    
    report.append("### 大文件 (>200MB)")
    report.append(f"- 总数: {stats['categories']['large']['total']}")
    report.append(f"- 已处理: {stats['categories']['large']['processed']}")
    report.append(f"- 未处理: {stats['categories']['large']['unprocessed']}")
    report.append("")
    
    # 性能统计
    report.append("## 性能统计")
    report.append(f"- 平均每页处理时间: {stats['avg_time_per_page_seconds']:.2f}秒")
    report.append(f"- 平均每文件处理时间: {stats['avg_time_per_file_seconds']:.1f}秒")
    report.append(f"- 输出文件总大小: {stats['total_output_size_mb']:.2f}MB")
    report.append(f"- 平均每页输出大小: {stats['total_output_size_mb']/stats['total_pages']:.2f}KB" if stats['total_pages'] > 0 else "N/A")
    report.append("")
    
    # 已处理文件列表
    report.append("## 已处理文件列表")
    for category, files in categories.items():
        if files:
            report.append(f"### {category.capitalize()} Files")
            for pdf in files:
                # 查找对应的处理结果
                base_name = pdf['name'].replace('.pdf', '')
                processed = next((p for p in processed_files if base_name in p['file_name']), None)
                
                if processed:
                    pages = processed['data'].get('total_pages', 0)
                    time_sec = processed['data'].get('processing_time', 0)
                    report.append(f"- **{pdf['name']}** ({pdf['size_mb']:.1f}MB)")
                    report.append(f"  - 页数: {pages}, 时间: {time_sec:.1f}秒")
            report.append("")
    
    # 未处理文件列表
    report.append("## 未处理文件列表")
    for category, files in unprocessed.items():
        if files:
            report.append(f"### {category.capitalize()} Files")
            for pdf in files:
                report.append(f"- **{pdf['name']}** ({pdf['size_mb']:.1f}MB)")
            report.append("")
    
    # 输出文件位置
    report.append("## 输出文件")
    report.append(f"所有OCR结果保存在: `{OUTPUT_DIR}`")
    report.append("文件格式:")
    report.append("- `{文件名}_ocr.json`: 完整OCR结果")
    report.append("- `{文件名}_text.txt`: 提取的纯文本")
    report.append("- `{文件名}_merged_ocr.json`: 合并后的结果 (分块处理文件)")
    report.append("")
    
    return "\n".join(report)

def main():
    """主函数"""
    print("="*60)
    print("生成OCR处理报告")
    print("="*60)
    
    # 获取文件信息
    print("扫描PDF文件...")
    all_pdfs = get_all_pdfs()
    
    print("加载已处理文件...")
    processed_files = get_processed_files()
    
    # 分类文件
    print("分析文件...")
    categories, unprocessed, _ = categorize_files(all_pdfs, processed_files)
    
    # 生成统计
    stats = generate_statistics(categories, unprocessed, processed_files)
    
    # 生成报告
    print("生成报告...")
    
    # Markdown报告
    markdown_report = generate_markdown_report(stats, categories, unprocessed, processed_files)
    markdown_file = os.path.join(OUTPUT_DIR, "ocr_report.md")
    with open(markdown_file, 'w', encoding='utf-8') as f:
        f.write(markdown_report)
    
    # JSON报告
    json_report = {
        'timestamp': time.time(),
        'generated_at': datetime.now().isoformat(),
        'statistics': stats,
        'categories': {
            category: {
                'processed': [f['name'] for f in files],
                'unprocessed': [f['name'] for f in unprocessed[category]]
            }
            for category, files in categories.items()
        }
    }
    
    json_file = os.path.join(OUTPUT_DIR, "ocr_report.json")
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(json_report, f, ensure_ascii=False, indent=2)
    
    # 控制台输出
    print("\n" + "="*60)
    print("报告统计")
    print("="*60)
    print(f"总文件数: {stats['total_files']}")
    print(f"已处理: {stats['processed_files']} ({stats['success_rate']:.1f}%)")
    print(f"未处理: {stats['unprocessed_files']}")
    print(f"总页数: {stats['total_pages']}")
    print(f"总时间: {stats['total_time_seconds']:.1f}秒")
    print()
    
    print("分类统计:")
    for category, data in stats['categories'].items():
        print(f"  {category}:")
        print(f"    总数: {data['total']}, 已处理: {data['processed']}, 未处理: {data['unprocessed']}")
    print()
    
    print(f"报告已生成:")
    print(f"  Markdown: {markdown_file}")
    print(f"  JSON: {json_file}")
    print("="*60)

if __name__ == "__main__":
    main()