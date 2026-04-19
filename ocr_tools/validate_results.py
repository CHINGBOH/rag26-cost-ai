#!/usr/bin/env python3
"""
OCR结果质量验证工具
检查OCR结果的准确性和完整性
"""

import os
import json
import re
from pathlib import Path
from collections import defaultdict

OUTPUT_DIR = "/home/l/知识库测试资料/ocr_results"

def load_ocr_results():
    """加载所有OCR结果"""
    results = []
    
    for file in os.listdir(OUTPUT_DIR):
        if file.endswith('_ocr.json') and not file.startswith('processing'):
            file_path = os.path.join(OUTPUT_DIR, file)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                results.append({
                    'file_name': file,
                    'data': data
                })
            except Exception as e:
                print(f"错误: 无法读取 {file}: {e}")
    
    return results

def validate_result(result):
    """验证单个OCR结果"""
    data = result['data']
    file_name = result['file_name']
    
    issues = []
    warnings = []
    
    # 检查基本字段
    required_fields = ['document_id', 'file_name', 'total_pages', 'pages', 'full_text']
    for field in required_fields:
        if field not in data:
            issues.append(f"缺少必需字段: {field}")
    
    # 检查页数一致性
    if 'total_pages' in data and 'pages' in data:
        total_pages = data['total_pages']
        pages_count = len(data['pages'])
        if total_pages != pages_count:
            warnings.append(f"页数不一致: total_pages={total_pages}, pages数组长度={pages_count}")
    
    # 检查每页数据
    if 'pages' in data:
        for i, page in enumerate(data['pages']):
            if 'text_blocks' not in page:
                issues.append(f"第{i+1}页缺少text_blocks")
            elif len(page['text_blocks']) == 0:
                warnings.append(f"第{i+1}页没有检测到文本")
            
            # 检查置信度
            if 'text_blocks' in page:
                for j, block in enumerate(page['text_blocks']):
                    if 'confidence' not in block:
                        warnings.append(f"第{i+1}页第{j+1}个文本块缺少置信度")
                    elif block['confidence'] < 0.7:
                        warnings.append(f"第{i+1}页第{j+1}个文本块置信度低: {block['confidence']:.2%}")
            
            # 检查边界框
            if 'text_blocks' in page:
                for j, block in enumerate(page['text_blocks']):
                    if 'bbox' not in block:
                        warnings.append(f"第{i+1}页第{j+1}个文本块缺少边界框")
                    elif not all(k in block['bbox'] for k in ['x', 'y', 'width', 'height']):
                        warnings.append(f"第{i+1}页第{j+1}个文本块边界框不完整")
    
    # 检查文本质量
    if 'full_text' in data:
        text = data['full_text']
        
        # 检查空文本
        if len(text.strip()) == 0:
            issues.append("full_text为空")
        
        # 检查文本长度
        total_blocks = sum(len(page.get('text_blocks', [])) for page in data.get('pages', []))
        if total_blocks > 0 and len(text) < total_blocks * 10:
            warnings.append("full_text可能不完整")
        
        # 检查特殊字符
        if '■' in text and text.count('■') > 100:
            warnings.append("文本中包含大量方框字符，可能有识别问题")
        
        # 检查异常字符
        abnormal_chars = re.findall(r'[^\x00-\x7F\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]', text)
        if len(abnormal_chars) > len(text) * 0.1:
            warnings.append(f"包含大量异常字符: {len(abnormal_chars)}个")
    
    # 检查表格数据
    if 'pages' in data:
        table_count = sum(len(page.get('tables', [])) for page in data['pages'])
        if table_count > 0:
            print(f"  检测到 {table_count} 个表格")
    
    # 检查处理时间
    if 'processing_time' in data:
        processing_time = data['processing_time']
        total_pages = data.get('total_pages', 1)
        avg_time_per_page = processing_time / total_pages
        
        if avg_time_per_page > 30:
            warnings.append(f"处理时间较长: 平均每页 {avg_time_per_page:.1f}秒")
    
    return {
        'file_name': file_name,
        'issues': issues,
        'warnings': warnings,
        'total_pages': data.get('total_pages', 0),
        'processing_time': data.get('processing_time', 0),
        'text_length': len(data.get('full_text', '')),
        'has_issues': len(issues) > 0,
        'has_warnings': len(warnings) > 0
    }

def generate_quality_report(validations):
    """生成质量报告"""
    total_files = len(validations)
    files_with_issues = sum(1 for v in validations if v['has_issues'])
    files_with_warnings = sum(1 for v in validations if v['has_warnings'])
    
    print("\n" + "="*60)
    print("质量验证报告")
    print("="*60)
    print(f"总文件数: {total_files}")
    print(f"有问题文件: {files_with_issues}")
    print(f"有警告文件: {files_with_warnings}")
    print(f"完全正常: {total_files - files_with_issues - files_with_warnings}")
    print()
    
    # 统计总页数和处理时间
    total_pages = sum(v['total_pages'] for v in validations)
    total_time = sum(v['processing_time'] for v in validations)
    total_text = sum(v['text_length'] for v in validations)
    
    print(f"总页数: {total_pages}")
    print(f"总处理时间: {total_time:.1f}秒")
    print(f"平均每页时间: {total_time/total_pages:.2f}秒" if total_pages > 0 else "N/A")
    print(f"总文本长度: {total_text:,} 字符")
    print()
    
    # 显示有问题和警告的文件
    if files_with_issues > 0:
        print("有问题的文件:")
        for v in validations:
            if v['has_issues']:
                print(f"  {v['file_name']}:")
                for issue in v['issues']:
                    print(f"    - {issue}")
        print()
    
    if files_with_warnings > 0:
        print("有警告的文件:")
        for v in validations:
            if v['has_warnings']:
                print(f"  {v['file_name']}:")
                for warning in v['warnings'][:3]:  # 只显示前3个警告
                    print(f"    - {warning}")
                if len(v['warnings']) > 3:
                    print(f"    - ... 还有 {len(v['warnings']) - 3} 个警告")
        print()
    
    # 保存详细报告
    report = {
        'total_files': total_files,
        'files_with_issues': files_with_issues,
        'files_with_warnings': files_with_warnings,
        'total_pages': total_pages,
        'total_time': total_time,
        'total_text_length': total_text,
        'validations': validations
    }
    
    report_file = os.path.join(OUTPUT_DIR, "quality_report.json")
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"详细报告已保存: {report_file}")

def main():
    """主函数"""
    print("="*60)
    print("OCR结果质量验证")
    print("="*60)
    
    # 加载OCR结果
    print("加载OCR结果...")
    results = load_ocr_results()
    
    if not results:
        print("没有找到OCR结果文件")
        return
    
    print(f"找到 {len(results)} 个OCR结果文件")
    print()
    
    # 验证每个结果
    validations = []
    
    for i, result in enumerate(results, 1):
        file_name = result['file_name']
        print(f"[{i}/{len(results)}] 验证: {file_name}")
        
        validation = validate_result(result)
        validations.append(validation)
        
        if validation['has_issues']:
            print(f"  ✗ 发现 {len(validation['issues'])} 个问题")
        elif validation['has_warnings']:
            print(f"  ⚠ 发现 {len(validation['warnings'])} 个警告")
        else:
            print(f"  ✓ 验证通过")
    
    # 生成质量报告
    generate_quality_report(validations)
    
    print("="*60)
    print("质量验证完成")
    print("="*60)

if __name__ == "__main__":
    main()