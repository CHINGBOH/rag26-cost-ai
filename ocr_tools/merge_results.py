#!/usr/bin/env python3
"""
合并OCR结果工具
将分块处理的PDF结果合并为完整文档
"""

import os
import json
from pathlib import Path

OUTPUT_DIR = "/home/l/知识库测试资料/ocr_results"

def find_chunk_files():
    """查找所有分块文件"""
    chunk_files = []
    
    for file in os.listdir(OUTPUT_DIR):
        if '_chunk_' in file and file.endswith('_ocr.json'):
            chunk_files.append(file)
    
    return chunk_files

def get_base_files():
    """获取需要合并的文件列表"""
    chunk_files = find_chunk_files()
    base_files = {}
    
    for chunk_file in chunk_files:
        # 提取基础文件名
        parts = chunk_file.split('_chunk_')
        if len(parts) >= 2:
            base_name = parts[0]
            if base_name not in base_files:
                base_files[base_name] = []
            base_files[base_name].append(chunk_file)
    
    return base_files

def merge_file_results(base_name, chunk_files):
    """合并单个文件的所有分块结果"""
    print(f"合并: {base_name}")
    
    # 按块号排序
    chunk_files.sort(key=lambda x: int(x.split('_chunk_')[1].split('_')[0]))
    
    merged_result = {
        'document_id': f"merged_{base_name}",
        'file_name': f"{base_name}.pdf",
        'total_pages': 0,
        'pages': [],
        'full_text': '',
        'processing_time': 0,
        'chunks_processed': len(chunk_files),
        'chunk_files': chunk_files
    }
    
    total_confidence = 0
    confidence_count = 0
    
    for chunk_file in chunk_files:
        chunk_path = os.path.join(OUTPUT_DIR, chunk_file)
        
        try:
            with open(chunk_path, 'r', encoding='utf-8') as f:
                chunk_data = json.load(f)
            
            # 合并页面
            if 'pages' in chunk_data:
                merged_result['pages'].extend(chunk_data['pages'])
                merged_result['total_pages'] += chunk_data.get('total_pages', 0)
                
                # 统计置信度
                for page in chunk_data.get('pages', []):
                    if 'confidence' in page:
                        total_confidence += page['confidence']
                        confidence_count += 1
            
            # 合并文本
            if 'full_text' in chunk_data:
                merged_result['full_text'] += chunk_data['full_text'] + "\n\n"
            
            # 累加处理时间
            merged_result['processing_time'] += chunk_data.get('processing_time', 0)
            
        except Exception as e:
            print(f"  错误: 读取 {chunk_file} 失败: {e}")
    
    # 计算平均置信度
    if confidence_count > 0:
        merged_result['average_confidence'] = total_confidence / confidence_count
    
    # 保存合并结果
    merged_json = os.path.join(OUTPUT_DIR, f"{base_name}_merged_ocr.json")
    with open(merged_json, 'w', encoding='utf-8') as f:
        json.dump(merged_result, f, ensure_ascii=False, indent=2)
    
    merged_text = os.path.join(OUTPUT_DIR, f"{base_name}_merged_text.txt")
    with open(merged_text, 'w', encoding='utf-8') as f:
        f.write(merged_result['full_text'])
    
    print(f"  ✓ 合并完成")
    print(f"    总页数: {merged_result['total_pages']}")
    print(f"    处理块数: {merged_result['chunks_processed']}")
    print(f"    总时间: {merged_result['processing_time']:.1f}秒")
    if 'average_confidence' in merged_result:
        print(f"    平均置信度: {merged_result['average_confidence']:.2%}")
    print(f"    保存到: {merged_json}")
    
    return merged_json, merged_text

def main():
    """主函数"""
    print("="*60)
    print("合并OCR结果")
    print("="*60)
    
    # 获取需要合并的文件
    base_files = get_base_files()
    
    if not base_files:
        print("没有找到需要合并的分块文件")
        return
    
    print(f"找到 {len(base_files)} 个文件需要合并")
    print()
    
    # 合并每个文件
    successful = 0
    failed = 0
    
    for base_name, chunk_files in base_files.items():
        print(f"[{successful + failed + 1}/{len(base_files)}] ", end="")
        
        try:
            merge_file_results(base_name, chunk_files)
            successful += 1
        except Exception as e:
            print(f"  ✗ 合并失败: {str(e)}")
            failed += 1
        
        print()
    
    print("="*60)
    print(f"合并完成: 成功 {successful}, 失败 {failed}")
    print("="*60)
    
    # 清理分块文件
    print("\n是否清理原始分块文件？(y/n)")
    # 这里可以添加清理逻辑
    
    # 生成合并报告
    generate_merge_report(successful, failed)

def generate_merge_report(successful, failed):
    """生成合并报告"""
    report = {
        'timestamp': time.time(),
        'successful': successful,
        'failed': failed,
        'merged_files': []
    }
    
    # 查找所有合并文件
    for file in os.listdir(OUTPUT_DIR):
        if file.endswith('_merged_ocr.json'):
            merged_path = os.path.join(OUTPUT_DIR, file)
            try:
                with open(merged_path, 'r', encoding='utf-8') as f:
                    merged_data = json.load(f)
                report['merged_files'].append({
                    'file_name': merged_data.get('file_name'),
                    'total_pages': merged_data.get('total_pages'),
                    'chunks_processed': merged_data.get('chunks_processed'),
                    'processing_time': merged_data.get('processing_time'),
                    'average_confidence': merged_data.get('average_confidence')
                })
            except Exception:
                pass
    
    # 保存报告
    report_file = os.path.join(OUTPUT_DIR, "merge_report.json")
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"合并报告已保存: {report_file}")

import time

if __name__ == "__main__":
    main()