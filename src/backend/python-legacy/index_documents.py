#!/usr/bin/env python3
"""
文档索引脚本 - 直接在后端目录运行
"""
import os
import uuid
from typing import List, Dict, Any

# 导入所需模块
from domain_models.document import Document, DocumentChunk, DocumentMetadata, DocumentType, ChunkType
from infrastructure.adapters.unified.unified_store import UnifiedStore
from infrastructure.adapters.embedding_service import get_embedding_service

def process_pdf(file_path: str) -> Dict[str, Any]:
    """处理PDF文件并索引"""
    print(f"\n处理: {os.path.basename(file_path)}")
    
    # 创建文档元数据
    doc_id = str(uuid.uuid4())
    metadata = DocumentMetadata(
        doc_id=doc_id,
        title=os.path.basename(file_path),
        source=file_path,
        doc_type=DocumentType.PDF,
        total_pages=1
    )
    
    # 创建简单的chunk
    content = f"PDF文档内容: {os.path.basename(file_path)}"
    chunk = DocumentChunk(
        chunk_id=f"{doc_id}_chunk_0001",
        doc_id=doc_id,
        content=content,
        chunk_type=ChunkType.TEXT,
        page_number=1
    )
    
    # 生成embedding
    embedding_service = get_embedding_service()
    embedding = embedding_service.encode([content])[0]
    chunk.embedding = embedding
    
    # 创建文档
    document = Document(
        metadata=metadata,
        chunks=[chunk],
        raw_content=content
    )
    
    # 索引到存储
    store = UnifiedStore()
    result = store.index_document(document)
    
    return {
        'doc_id': doc_id,
        'title': metadata.title,
        'chunks': len(document.chunks),
        'result': result
    }

def find_pdf_files(directory: str) -> List[str]:
    """查找PDF文件"""
    pdf_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith('.pdf'):
                pdf_files.append(os.path.join(root, file))
    return pdf_files

def main():
    """主函数"""
    print("🚀 开始索引知识库文档")
    print("=" * 60)
    
    knowledge_base_dir = '/home/l/rag-dashboard/data/knowledge_base'
    pdf_files = find_pdf_files(knowledge_base_dir)
    
    print(f"找到 {len(pdf_files)} 个PDF文件")
    
    if not pdf_files:
        print("❌ 未找到PDF文件")
        return
    
    processed = 0
    failed = 0
    
    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"\n处理 {i}/{len(pdf_files)}: {os.path.basename(pdf_path)}")
        try:
            result = process_pdf(pdf_path)
            print(f"✅ 成功: {result['title']} (doc_id: {result['doc_id']})")
            print(f"   索引结果: {result['result']}")
            processed += 1
        except Exception as e:
            print(f"❌ 失败: {e}")
            failed += 1
    
    print(f"\n{'=' * 60}")
    print(f"处理完成: 成功={processed}, 失败={failed}")

if __name__ == "__main__":
    main()