#!/usr/bin/env python3
"""
LangGraph 配置文件
配置 LangGraph 相关的参数和环境变量
"""

import os
from typing import Optional

# LangGraph 配置
LANGGRAPH_CONFIG = {
    # 检查点配置
    "checkpoint": {
        "type": os.getenv("LANGGRAPH_CHECKPOINT_TYPE", "in_memory"),  # in_memory, sqlite, redis
        "path": os.getenv("LANGGRAPH_CHECKPOINT_PATH", "./langgraph_checkpoints"),
    },
    
    # 并发配置
    "concurrency": {
        "max_workers": int(os.getenv("LANGGRAPH_MAX_WORKERS", "4")),
    },
    
    # 监控配置
    "monitoring": {
        "enabled": os.getenv("LANGGRAPH_MONITORING", "false").lower() == "true",
        "endpoint": os.getenv("LANGGRAPH_MONITORING_ENDPOINT"),
    },
}

# LLM 配置（与现有系统集成）
LLM_CONFIG = {
    "api_base": os.getenv("LLM_API_BASE", "http://localhost:8080"),
    "api_key": os.getenv("LLM_API_KEY", "empty"),  # llama.cpp 不需要 API key
    "model": os.getenv("LLM_MODEL", "DeepSeek-R1-Distill-Qwen-14B-Q4_K_M.gguf"),
    "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
    "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "1024")),
}

# 工具配置
TOOLS_CONFIG = {
    "vector_search": {
        "enabled": True,
        "endpoint": os.getenv("VECTOR_SEARCH_ENDPOINT", "http://localhost:6333"),
    },
    "graph_search": {
        "enabled": True,
        "endpoint": os.getenv("GRAPH_SEARCH_ENDPOINT", "bolt://localhost:7687"),
        "username": os.getenv("NEO4J_USER", "neo4j"),
        "password": os.getenv("NEO4J_PASSWORD", "password"),
    },
    "keyword_search": {
        "enabled": True,
        "endpoint": os.getenv("KEYWORD_SEARCH_ENDPOINT", "http://localhost:9200"),
    },
    "calculator": {
        "enabled": True,
    },
}

def get_langgraph_config() -> dict:
    """获取 LangGraph 配置"""
    return LANGGRAPH_CONFIG

def get_llm_config() -> dict:
    """获取 LLM 配置"""
    return LLM_CONFIG

def get_tools_config() -> dict:
    """获取工具配置"""
    return TOOLS_CONFIG