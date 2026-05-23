#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
将 Excel 文件转换为 Markdown 格式
适用于 /home/l/rag-dashboard/data/knowledge_base/智能体问答.xlsx
"""

import pandas as pd
import os
from pathlib import Path

def excel_to_markdown(excel_path, output_path):
    """
    将 Excel 文件转换为 Markdown 表格格式
    """
    # 读取 Excel 文件
    df = pd.read_excel(excel_path)
    
    # 转换为 Markdown 表格格式
    md_content = []
    
    # 添加标题
    md_content.append("# 智能体问答知识库\n")
    
    # 添加表格
    # 表头
    headers = df.columns.tolist()
    header_row = "| " + " | ".join(str(h) for h in headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    
    md_content.append(header_row)
    md_content.append(separator)
    
    # 数据行
    for _, row in df.iterrows():
        data_row = "| " + " | ".join(str(cell).replace('\n', '<br>') if pd.notna(cell) else '' for cell in row.values) + " |"
        md_content.append(data_row)
    
    # 写入文件
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md_content))
    
    print(f"转换完成！输出文件: {output_path}")

if __name__ == "__main__":
    # 定义输入输出路径
    excel_file = "/home/l/rag-dashboard/data/knowledge_base/智能体问答.xlsx"
    output_file = "/home/l/rag-dashboard/data/knowledge_base/智能体问答.md"
    
    # 检查输入文件是否存在
    if not os.path.exists(excel_file):
        print(f"错误: 找不到文件 {excel_file}")
    else:
        excel_to_markdown(excel_file, output_file)