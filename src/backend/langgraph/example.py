#!/usr/bin/env python3
"""
LangGraph 示例
展示如何使用 LangGraph 构建 RAG 系统的工作流
"""

import asyncio
from typing import Dict, Any, List
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from config import get_llm_config, get_tools_config

# 定义状态类型
RAGState = Dict[str, Any]

def create_rag_workflow():
    """创建 RAG 工作流"""
    # 初始化检查点
    memory = MemorySaver()
    
    # 创建状态图
    workflow = StateGraph(RAGState)
    
    # 定义节点
    def retrieve_node(state: RAGState) -> RAGState:
        """检索节点"""
        print(f"🔍 检索: {state['query']}")
        # 模拟检索（实际应调用向量搜索、图搜索等）
        state['contexts'] = [
            {
                "chunk_id": "1",
                "content": "这是检索到的内容1",
                "score": 0.95,
                "source": "文档1"
            },
            {
                "chunk_id": "2",
                "content": "这是检索到的内容2",
                "score": 0.85,
                "source": "文档2"
            }
        ]
        state['sources'] = [ctx["source"] for ctx in state['contexts']]
        return state
    
    def generate_node(state: RAGState) -> RAGState:
        """生成节点"""
        print(f"🤖 生成回答")
        # 模拟生成（实际应调用 LLM）
        state['thought'] = "根据检索到的内容，我需要生成一个全面的回答..."
        state['answer'] = f"根据检索到的信息，关于 '{state['query']}' 的回答是：这是一个示例回答。"
        return state
    
    def validate_node(state: RAGState) -> RAGState:
        """验证节点"""
        print(f"✅ 验证回答")
        # 简单验证逻辑
        if len(state['answer']) < 10:
            state['error'] = "回答太短"
        return state
    
    # 添加节点到图
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("generate", generate_node)
    workflow.add_node("validate", validate_node)
    
    # 定义边
    workflow.set_entry_point("retrieve")
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", "validate")
    workflow.add_edge("validate", END)
    
    # 编译工作流
    app = workflow.compile(checkpointer=memory)
    return app

async def run_rag_example(query: str):
    """运行 RAG 示例"""
    print(f"🚀 运行 RAG 示例: {query}")
    
    # 创建工作流
    app = create_rag_workflow()
    
    # 初始化状态
    initial_state: RAGState = {
        "query": query,
        "contexts": [],
        "answer": "",
        "sources": [],
        "thought": "",
        "error": ""
    }
    
    # 运行工作流
    result = await app.ainvoke(
        initial_state,
        config={
            "configurable": {
                "thread_id": "test_thread",
                "checkpoint_ns": "test_namespace",
                "checkpoint_id": "test_checkpoint"
            }
        }
    )
    
    # 打印结果
    print("\n📊 结果:")
    print(f"查询: {result['query']}")
    print(f"思考: {result['thought']}")
    print(f"回答: {result['answer']}")
    print(f"来源: {result['sources']}")
    if result.get('error'):
        print(f"错误: {result['error']}")
    
    return result

if __name__ == "__main__":
    # 运行示例
    asyncio.run(run_rag_example("什么是 LangGraph？"))
    asyncio.run(run_rag_example("如何使用 RAG 系统？"))