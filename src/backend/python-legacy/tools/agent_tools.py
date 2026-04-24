#!/usr/bin/env python3
"""
Agent Tools for PG Single-Database RAG System
提供价格查询和文本搜索功能
"""

import os
import sys
import json
import psycopg2
import psycopg2.extras
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 数据库配置
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "rag_db",
    "user": "rag_user",
    "password": os.environ.get("POSTGRES_PASSWORD", "rag_password")  # 直接设置密码
}

# Qdrant 配置（用于会话上下文）
QDRANT_HOST = os.environ.get("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", 6333))
QDRANT_COLLECTION = "session_context"

def get_db_connection():
    """获取数据库连接"""
    # 使用连接字符串而不是字典
    conn_string = f"host=localhost port=5432 dbname=rag_db user=rag_user password={os.environ.get('POSTGRES_PASSWORD', 'rag_password')}"
    return psycopg2.connect(conn_string)

def price_query(query: str, period: Optional[str] = None, category: Optional[str] = None,
                limit: int = 20) -> Dict[str, Any]:
    """
    价格查询：从 price_records 表查询结构化价格数据

    Args:
        query: 查询关键词（如材料名称、规格等）
        period: 时间段过滤，如 "2024-01"
        category: 类别过滤，如 "建筑材料"
        limit: 返回结果数量限制

    Returns:
        包含查询结果和元数据的字典
    """
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 构建查询
            sql = """
                SELECT
                    pr.id,
                    pr.period,
                    pr.category,
                    pr.material_name,
                    pr.unit,
                    pr.price,
                    pr.page_number,
                    pr.source_row,
                    d.file_name,
                    d.doc_type
                FROM price_records pr
                JOIN documents d ON pr.document_id = d.id
                WHERE 1=1
            """
            params = []

            # 添加查询条件
            if query:
                sql += " AND (pr.material_name ILIKE %s OR pr.category ILIKE %s)"
                params.extend([f"%{query}%", f"%{query}%"])

            if period:
                sql += " AND pr.period = %s"
                params.append(period)

            if category:
                sql += " AND pr.category ILIKE %s"
                params.append(f"%{category}%")

            # 按相关性排序（价格高的排前面，假设更重要）
            sql += " ORDER BY pr.price DESC, pr.period DESC LIMIT %s"
            params.append(limit)

            cur.execute(sql, params)
            results = cur.fetchall()

            # 转换为字典列表
            records = []
            for row in results:
                record = dict(row)
                # 解析 metadata JSON
                if record['metadata']:
                    record['metadata'] = json.loads(record['metadata'])
                records.append(record)

            return {
                "query": query,
                "period_filter": period,
                "category_filter": category,
                "total_results": len(records),
                "results": records
            }

    except Exception as e:
        logger.error(f"Price query failed: {e}")
        return {"error": str(e), "results": []}
    finally:
        conn.close()

def text_search(query: str, period: Optional[str] = None, doc_type: Optional[str] = None,
                limit: int = 10) -> Dict[str, Any]:
    """
    文本搜索：使用 pg_trgm 和向量相似度进行全文搜索

    Args:
        query: 搜索关键词
        period: 时间段过滤
        doc_type: 文档类型过滤
        limit: 返回结果数量限制

    Returns:
        包含搜索结果和相关性的字典
    """
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 使用 pg_trgm 进行相似度搜索
            sql = """
                SELECT
                    tc.id,
                    tc.document_id,
                    tc.chunk_index,
                    tc.content,
                    tc.page_number,
                    tc.period,
                    tc.doc_type,
                    d.file_name,
                    ts_rank_cd(tc.tsv, plainto_tsquery('simple', %s)) as text_rank,
                    similarity(tc.content, %s) as similarity_score
                FROM text_chunks tc
                JOIN documents d ON tc.document_id = d.id
                WHERE 1=1
            """
            params = [query, query]

            # 添加过滤条件
            if period:
                sql += " AND tc.period = %s"
                params.append(period)

            if doc_type:
                sql += " AND tc.doc_type = %s"
                params.append(doc_type)

            # 文本相似度条件
            sql += " AND similarity(tc.content, %s) > 0.1"
            params.append(query)

            # 按综合评分排序（文本排名 + 相似度）
            sql += """
                ORDER BY (ts_rank_cd(tc.tsv, plainto_tsquery('simple', %s)) +
                         similarity(tc.content, %s)) DESC
                LIMIT %s
            """
            params.extend([query, query, limit])

            cur.execute(sql, params)
            results = cur.fetchall()

            # 转换为字典列表
            chunks = []
            for row in results:
                chunk = dict(row)
                # 解析 metadata JSON
                if chunk['metadata']:
                    chunk['metadata'] = json.loads(chunk['metadata'])
                chunks.append(chunk)

            return {
                "query": query,
                "period_filter": period,
                "doc_type_filter": doc_type,
                "total_results": len(chunks),
                "results": chunks
            }

    except Exception as e:
        logger.error(f"Text search failed: {e}")
        return {"error": str(e), "results": []}
    finally:
        conn.close()

def hybrid_search(query: str, period: Optional[str] = None, limit: int = 15) -> Dict[str, Any]:
    """
    混合搜索：结合价格查询和文本搜索

    优先返回结构化价格数据，如果没有则返回相关文本
    """
    # 先尝试价格查询
    price_results = price_query(query, period=period, limit=limit//2)

    # 再进行文本搜索
    text_results = text_search(query, period=period, limit=limit//2)

    # 合并结果
    combined_results = []

    # 添加价格结果（优先级高）
    for result in price_results.get("results", []):
        combined_results.append({
            "type": "price_record",
            "score": 1.0,  # 价格查询结果给满分
            "data": result
        })

    # 添加文本结果
    for result in text_results.get("results", []):
        score = (result.get('text_rank', 0) + result.get('similarity_score', 0)) / 2
        combined_results.append({
            "type": "text_chunk",
            "score": score,
            "data": result
        })

    # 按分数排序
    combined_results.sort(key=lambda x: x["score"], reverse=True)

    return {
        "query": query,
        "period_filter": period,
        "total_results": len(combined_results),
        "results": combined_results[:limit]
    }

def get_price_trends(item_name: str, category: Optional[str] = None,
                     periods: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    获取价格趋势：分析特定材料在不同时期的价格变化
    """
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            sql = """
                SELECT
                    period,
                    AVG(price) as avg_price,
                    MIN(price) as min_price,
                    MAX(price) as max_price,
                    COUNT(*) as record_count
                FROM price_records
                WHERE material_name ILIKE %s
            """
            params = [f"%{item_name}%"]

            if category:
                sql += " AND category ILIKE %s"
                params.append(f"%{category}%")

            if periods:
                sql += " AND period = ANY(%s)"
                params.append(periods)

            sql += " GROUP BY period ORDER BY period"

            cur.execute(sql, params)
            results = cur.fetchall()

            trends = []
            for row in results:
                trends.append(dict(row))

            return {
                "item_name": item_name,
                "category_filter": category,
                "periods_filter": periods,
                "trends": trends
            }

    except Exception as e:
        logger.error(f"Price trends query failed: {e}")
        return {"error": str(e), "trends": []}
    finally:
        conn.close()

def get_available_periods() -> List[str]:
    """获取所有可用的时期"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT period FROM documents ORDER BY period DESC")
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Get periods failed: {e}")
        return []
    finally:
        conn.close()

def get_available_categories() -> List[str]:
    """获取所有可用的价格类别"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT category FROM price_records WHERE category IS NOT NULL ORDER BY category")
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Get categories failed: {e}")
        return []
    finally:
        conn.close()

# 测试函数
def test_tools():
    """测试工具函数"""
    print("=== 测试 Agent Tools ===")

    # 测试价格查询
    print("\n1. 测试价格查询:")
    result = price_query("钢筋", period="2024-01", limit=3)
    print(f"查询 '钢筋' 结果: {len(result.get('results', []))} 条")

    # 测试文本搜索
    print("\n2. 测试文本搜索:")
    result = text_search("建筑材料", limit=3)
    print(f"搜索 '建筑材料' 结果: {len(result.get('results', []))} 条")

    # 测试混合搜索
    print("\n3. 测试混合搜索:")
    result = hybrid_search("水泥", limit=5)
    print(f"混合搜索 '水泥' 结果: {len(result.get('results', []))} 条")

    # 测试获取可用数据
    print("\n4. 测试元数据查询:")
    periods = get_available_periods()
    categories = get_available_categories()
    print(f"可用时期: {periods[:5]}...")  # 只显示前5个
    print(f"可用类别: {categories[:5]}...")  # 只显示前5个

if __name__ == "__main__":
    test_tools()