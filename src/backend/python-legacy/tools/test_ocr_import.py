#!/usr/bin/env python3
"""
测试OCR数据导入
先测试单个文件，验证流程是否正常
"""

import os
import sys
import json
import asyncio
from pathlib import Path

# 添加项目路径
sys.path.insert(0, '/home/l/rag-dashboard/src/backend/python-legacy')

async def test_ocr_import():
    """测试OCR导入"""
    print("=" * 60)
    print("测试OCR数据导入")
    print("=" * 60)
    
    # 1. 检查OCR文件
    ocr_dir = Path("/home/l/rag-dashboard/data/ocr_outputs")
    ocr_files = list(ocr_dir.glob("*.json"))
    
    # 过滤掉日志和chunk文件
    ocr_files = [
        f for f in ocr_files
        if f.name not in ["processing_summary.json", "processed_documents.log"]
        and ("merged" in f.name or "chunk" not in f.name)
    ]
    
    print(f"\n找到 {len(ocr_files)} 个OCR文件")
    
    if not ocr_files:
        print("没有找到OCR文件！")
        return
    
    # 选择第一个文件测试
    test_file = ocr_files[0]
    print(f"\n测试文件: {test_file.name}")
    print(f"文件大小: {test_file.stat().st_size / 1024 / 1024:.2f} MB")
    
    # 2. 读取OCR结果
    print("\n读取OCR结果...")
    with open(test_file, 'r', encoding='utf-8') as f:
        ocr_result = json.load(f)
    
    print(f"✓ OCR结果读取成功")
    print(f"  - 文档ID: {ocr_result.get('document_id', 'N/A')}")
    print(f"  - 文件名: {ocr_result.get('file_name', 'N/A')}")
    print(f"  - 总页数: {ocr_result.get('total_pages', 0)}")
    print(f"  - 页面数量: {len(ocr_result.get('pages', []))}")
    
    # 3. 测试四库服务连接
    print("\n测试四库服务连接...")
    try:
        from services.four_database_service import get_four_db_service
        four_db_service = await get_four_db_service()
        print("✓ 四库服务连接成功")
    except Exception as e:
        print(f"✗ 四库服务连接失败: {e}")
        return
    
    # 4. 测试文档处理
    print("\n测试文档处理...")
    try:
        result = await four_db_service.process_document(
            file_path=str(test_file),
            file_name=test_file.name,
            ocr_result=ocr_result
        )
        
        print("✓ 文档处理成功")
        print(f"  - 文档ID: {result.document_id}")
        print(f"  - 总页数: {result.total_chunks}")
        print(f"  - 向量化块数: {result.embedded_chunks}")
        print(f"  - 提取表格数: {result.tables_extracted}")
        print(f"  - 提取实体数: {result.entities_extracted}")
        print(f"  - 知识图谱节点: {result.knowledge_graph_nodes}")
        print(f"  - 处理时间: {result.processing_time:.2f}秒")
        
    except Exception as e:
        print(f"✗ 文档处理失败: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 5. 测试搜索功能
    print("\n测试搜索功能...")
    try:
        # 从OCR结果中提取一些关键词进行搜索
        if ocr_result.get('pages'):
            first_page_text = ocr_result['pages'][0].get('raw_text', '')
            if len(first_page_text) > 50:
                query_text = first_page_text[:30]
                print(f"  搜索查询: {query_text}...")
                
                search_results = await four_db_service.search_four_databases(
                    query_text=query_text,
                    top_k=5
                )
                
                print(f"✓ 搜索成功")
                print(f"  - 总候选数: {search_results.get('total_candidates', 0)}")
                print(f"  - 返回结果数: {len(search_results.get('final_results', []))}")
                
                if search_results.get('final_results'):
                    print(f"  - 第一个结果分数: {search_results['final_results'][0].final_score:.4f}")
        
    except Exception as e:
        print(f"✗ 搜索失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 6. 获取系统统计
    print("\n获取系统统计...")
    try:
        stats = await four_db_service.get_system_statistics()
        print("✓ 统计信息获取成功")
        print(f"  - 文档总数: {stats.get('documents', {}).get('total', 0)}")
        print(f"  - 已处理文档: {stats.get('documents', {}).get('processed', 0)}")
        print(f"  - 总块数: {stats.get('chunks', {}).get('total', 0)}")
        print(f"  - 已向量化块数: {stats.get('chunks', {}).get('embedded', 0)}")
        print(f"  - 表格总数: {stats.get('tables', 0)}")
        print(f"  - 实体总数: {stats.get('entities', 0)}")
        print(f"  - 知识图谱节点: {stats.get('knowledge_graph', {}).get('nodes', 0)}")
        
    except Exception as e:
        print(f"✗ 获取统计失败: {e}")
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_ocr_import())