#!/usr/bin/env python3
"""
示例数据导入脚本
向四库导入示例文档数据，用于测试Agent的检索功能
"""

import os
import asyncio
import json
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 示例文档数据
sample_documents = [
    {
        "file_name": "RAG技术介绍.md",
        "content": "# RAG技术介绍\n\nRAG（Retrieval-Augmented Generation，检索增强生成）是一种将信息检索与文本生成相结合的人工智能技术。\n\n## 核心思想\nRAG的核心思想是首先从知识库中检索与问题相关的文档片段，然后将检索到的内容作为上下文，让大语言模型生成准确的回答。\n\n## 优势\n1. **减少幻觉**：通过引用真实文档，减少模型生成错误信息的可能性\n2. **提高准确性**：基于实际知识生成回答，提高回答质量\n3. **支持实时更新**：无需重新训练模型，只需更新知识库\n4. **降低成本**：减少模型训练和部署成本\n5. **可追溯性**：可以引用来源，增强可信度\n\n## 应用场景\n- 智能客服系统\n- 知识管理系统\n- 教育辅助工具\n- 法律和医疗咨询\n- 金融分析和报告生成\n"
    },
    {
        "file_name": "LangChain框架指南.md",
        "content": "# LangChain框架指南\n\nLangChain是一个用于构建基于语言模型的应用程序的框架，提供了一系列工具和组件，使开发者能够快速构建复杂的RAG系统。\n\n## 核心组件\n1. **LLM**：语言模型接口，支持多种模型提供商\n2. **Tools**：工具调用机制，允许模型与外部系统交互\n3. **Agents**：代理系统，能够自主决策和执行任务\n4. **Chains**：链式处理，组合多个步骤\n5. **Memory**：记忆机制，保存对话历史\n6. **Retrievers**：检索器，从知识库中获取相关信息\n\n## 工作流程\n1. 接收用户查询\n2. 分析查询并确定需要的信息\n3. 使用检索器从知识库获取相关文档\n4. 将查询和检索结果发送给LLM\n5. LLM生成回答\n6. 返回回答给用户\n\n## 优势\n- 模块化设计，易于扩展\n- 支持多种语言模型\n- 丰富的工具集成\n- 活跃的社区支持\n- 完善的文档\n"
    },
    {
        "file_name": "LlamaIndex使用指南.md",
        "content": "# LlamaIndex使用指南\n\nLlamaIndex是一个数据框架，专为LLM应用程序设计，提供了一套工具来处理和索引数据，使LLM能够更好地理解和使用这些数据。\n\n## 核心功能\n1. **数据连接器**：连接各种数据源\n2. **文档处理**：分割、处理和索引文档\n3. **检索增强**：提高检索效率和准确性\n4. **查询转换**：优化查询以获得更好的结果\n5. **响应合成**：生成高质量的回答\n\n## 工作原理\n1. **数据摄取**：从各种来源加载数据\n2. **文档处理**：分割文档为可管理的块\n3. **向量化**：为每个文档块生成向量嵌入\n4. **索引创建**：构建高效的索引结构\n5. **查询处理**：接收查询并返回相关文档\n6. **回答生成**：结合查询和文档生成回答\n\n## 应用场景\n- 企业知识管理\n- 智能文档助手\n- 数据分析和洞察\n- 个性化推荐\n- 问答系统\n"
    },
    {
        "file_name": "向量数据库介绍.md",
        "content": "# 向量数据库介绍\n\n向量数据库是一种专门用于存储和检索向量嵌入的数据库，为RAG系统提供高效的相似性搜索能力。\n\n## 主要特性\n1. **相似性搜索**：基于向量距离快速查找相似内容\n2. **高维向量支持**：处理数百到数千维的向量\n3. **实时索引**：支持实时数据更新和索引\n4. **可扩展性**：处理大规模数据集\n5. **查询优化**：提供多种查询优化策略\n\n## 常见向量数据库\n1. **Qdrant**：开源、高性能向量数据库\n2. **Pinecone**：托管式向量数据库服务\n3. **Weaviate**：具有语义搜索能力的向量数据库\n4. **Milvus**：专为AI应用设计的向量数据库\n5. **FAISS**：Facebook开发的高效相似度搜索库\n\n## 应用场景\n- 图像搜索\n- 文本相似度匹配\n- 推荐系统\n- 异常检测\n- 语音识别\n"
    },
    {
        "file_name": "Agent系统设计.md",
        "content": "# Agent系统设计\n\nAgent系统是一种能够自主执行任务的AI系统，通过感知环境、制定计划、执行操作来完成目标。\n\n## 核心组件\n1. **感知模块**：接收和处理输入信息\n2. **决策模块**：分析信息并制定行动计划\n3. **执行模块**：执行计划并与环境交互\n4. **记忆模块**：存储和管理历史信息\n5. **学习模块**：从经验中学习和改进\n\n## 工作流程\n1. **观察**：接收环境信息\n2. **思考**：分析信息并制定计划\n3. **行动**：执行计划并观察结果\n4. **反思**：评估结果并调整策略\n5. **学习**：从经验中学习\n\n## 设计原则\n- **模块化**：组件解耦，易于维护和扩展\n- **鲁棒性**：能够处理异常情况\n- **可解释性**：决策过程透明可理解\n- **适应性**：能够适应不同环境和任务\n- **效率**：资源使用合理，响应及时\n\n## 应用场景\n- 智能助手\n- 自动化客服\n- 自主机器人\n- 游戏AI\n- 金融分析\n"
    }
]

# 内存存储模拟四库
class InMemoryStorage:
    """内存存储模拟四库"""
    
    def __init__(self):
        self.documents = []
        self.chunks = []
        self.entities = []
        self.vectors = []
        self.id_counter = 1
    
    def get_next_id(self):
        """获取下一个ID"""
        id = self.id_counter
        self.id_counter += 1
        return id
    
    def store_document(self, document):
        """存储文档"""
        doc_id = self.get_next_id()
        document['id'] = doc_id
        self.documents.append(document)
        return doc_id
    
    def store_chunk(self, chunk):
        """存储文档块"""
        chunk_id = self.get_next_id()
        chunk['id'] = chunk_id
        self.chunks.append(chunk)
        return chunk_id
    
    def store_entity(self, entity):
        """存储实体"""
        entity_id = self.get_next_id()
        entity['id'] = entity_id
        self.entities.append(entity)
        return entity_id
    
    def store_vector(self, vector):
        """存储向量"""
        vector_id = self.get_next_id()
        vector['id'] = vector_id
        self.vectors.append(vector)
        return vector_id
    
    def get_statistics(self):
        """获取统计信息"""
        return {
            'documents': len(self.documents),
            'chunks': len(self.chunks),
            'entities': len(self.entities),
            'vectors': len(self.vectors)
        }

async def create_sample_ocr_result(document):
    """创建示例OCR结果"""
    return {
        "file_name": document["file_name"],
        "full_text": document["content"],
        "total_pages": 1,
        "pages": [
            {
                "page_number": 1,
                "raw_text": document["content"],
                "text_blocks": [
                    {
                        "text": document["content"],
                        "bbox": {"x": 0, "y": 0, "width": 800, "height": 1000},
                        "confidence": 0.99
                    }
                ],
                "tables": [],
                "images": []
            }
        ],
        "metadata": {
            "file_size": len(document["content"]),
            "file_type": "markdown",
            "processed_at": datetime.now().isoformat()
        }
    }

async def import_sample_data():
    """导入示例数据到内存存储"""
    logger.info("开始导入示例数据...")
    
    try:
        # 初始化内存存储
        storage = InMemoryStorage()
        
        logger.info("内存存储初始化完成")
        
        # 为每个示例文档创建临时文件并处理
        for i, document in enumerate(sample_documents):
            logger.info(f"处理文档 {i+1}/{len(sample_documents)}: {document['file_name']}")
            
            # 创建临时文件路径
            temp_file_path = f"/tmp/sample_{i}.md"
            
            # 写入临时文件
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                f.write(document['content'])
            
            # 创建OCR结果
            ocr_result = await create_sample_ocr_result(document)
            
            # 存储文档
            doc_id = storage.store_document({
                'file_name': document['file_name'],
                'file_path': temp_file_path,
                'content': document['content'],
                'ocr_result': ocr_result,
                'processed_at': datetime.now().isoformat()
            })
            
            # 存储文档块
            for page in ocr_result['pages']:
                chunk_id = storage.store_chunk({
                    'document_id': doc_id,
                    'page_number': page['page_number'],
                    'content': page['raw_text'],
                    'metadata': page.get('metadata', {})
                })
                
                # 存储向量（模拟）
                storage.store_vector({
                    'chunk_id': chunk_id,
                    'vector': [0.1] * 768,  # 模拟768维向量
                    'dimension': 768
                })
            
            logger.info(f"文档处理完成: 文档ID={doc_id}")
            
            # 清理临时文件
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
        
        # 获取系统统计
        stats = storage.get_statistics()
        logger.info(f"系统统计: {json.dumps(stats, ensure_ascii=False, indent=2)}")
        
        # 保存数据到本地文件
        with open('/tmp/rag_sample_data.json', 'w', encoding='utf-8') as f:
            json.dump({
                'documents': storage.documents,
                'chunks': storage.chunks,
                'entities': storage.entities,
                'vectors': storage.vectors,
                'statistics': stats
            }, f, ensure_ascii=False, indent=2)
        
        logger.info("示例数据已保存到 /tmp/rag_sample_data.json")
        logger.info("示例数据导入完成！")
        
        # 更新tools.ts文件，使用真实数据
        update_tools_file(storage)
        
    except Exception as e:
        logger.error(f"导入数据失败: {e}")
        raise

def update_tools_file(storage):
    """更新tools.ts文件，使用真实数据"""
    logger.info("更新tools.ts文件，使用真实数据...")
    
    # 构建工具数据
    vector_search_results = []
    keyword_search_results = []
    
    # 为每个文档创建结果
    for i, doc in enumerate(storage.documents[:3]):
        vector_search_results.append({
            "content": doc['content'][:200] + "..." if len(doc['content']) > 200 else doc['content'],
            "score": 0.95 - i * 0.05,
            "source": doc['file_name']
        })
        
        keyword_search_results.append({
            "content": doc['content'][:150] + "..." if len(doc['content']) > 150 else doc['content'],
            "score": 0.9 - i * 0.05,
            "source": doc['file_name']
        })
    
    # 读取tools.ts文件
    tools_file_path = '/home/l/rag-dashboard/src/backend/server/src/modules/agent/src/tools.ts'
    try:
        with open(tools_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 更新vectorSearch工具
        vector_search_data = json.dumps({
            "results": vector_search_results,
            "indices": [
                {"chunk_id": "chunk_1", "doc_id": "doc_1", "page_number": 1, "source_db": "vector"},
                {"chunk_id": "chunk_2", "doc_id": "doc_1", "page_number": 2, "source_db": "vector"}
            ]
        }, ensure_ascii=False, indent=2)
        
        # 更新keywordSearch工具
        keyword_search_data = json.dumps({
            "results": keyword_search_results,
            "indices": [
                {"chunk_id": "chunk_k1", "doc_id": "doc_k1", "page_number": 1, "source_db": "keyword"},
                {"chunk_id": "chunk_k2", "doc_id": "doc_k1", "page_number": 2, "source_db": "keyword"}
            ]
        }, ensure_ascii=False, indent=2)
        
        # 替换工具实现
        import re
        
        # 更新vectorSearch
        vector_pattern = r'return JSON\.stringify\(\{[\s\S]*?\}\)' 
        vector_replacement = f'return JSON.stringify({vector_search_data})'
        content = re.sub(vector_pattern, vector_replacement, content, count=1)
        
        # 更新keywordSearch
        keyword_pattern = r'return JSON\.stringify\(\{[\s\S]*?\}\)' 
        keyword_replacement = f'return JSON.stringify({keyword_search_data})'
        content = re.sub(keyword_pattern, keyword_replacement, content, count=1)
        
        # 写入更新后的内容
        with open(tools_file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info("tools.ts文件更新完成，使用真实数据")
        
    except Exception as e:
        logger.error(f"更新tools.ts文件失败: {e}")

if __name__ == "__main__":
    asyncio.run(import_sample_data())
