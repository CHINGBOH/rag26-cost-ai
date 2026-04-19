"""
结构化存储适配器 (PostgreSQL)
负责: 表格原始数据、时间序列的精确存储和查询

功能:
- 表格结构化存储 (JSONB + 关系型)
- 时间序列数值存储
- 实体-表格-数值关联
- 高效查询接口
"""

import json
import logging
import re
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 尝试导入 PostgreSQL 驱动
try:
    import psycopg2
    from psycopg2.extras import Json
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    logging.warning("psycopg2 not installed, structured store will be unavailable")

from config.loader import get_config, StructuredStoreConfig

logger = logging.getLogger(__name__)


@dataclass
class TableMetadata:
    """表格元数据"""
    table_id: str
    doc_id: str
    chunk_id: str
    table_name: str
    page_number: int
    headers: List[str] = field(default_factory=list)
    row_count: int = 0
    col_count: int = 0
    table_type: str = "data"  # data | price | specification
    created_at: Optional[datetime] = None


@dataclass
class TableRow:
    """表格行数据"""
    row_id: Optional[int] = None
    table_id: str = ""
    row_index: int = 0
    row_data: Dict[str, Any] = field(default_factory=dict)
    numeric_values: Dict[str, float] = field(default_factory=dict)


@dataclass
class TimeSeriesPoint:
    """时间序列数据点"""
    series_id: Optional[int] = None
    table_id: str = ""
    entity_name: str = ""  # 如: 钢筋_HRB400_Φ12
    entity_type: str = ""  # material | price | index
    time_period: str = ""  # 如: 2024-01, 2024-Q1
    value: float = 0.0
    unit: str = ""
    region: Optional[str] = None  # 地区
    metadata: Dict[str, Any] = field(default_factory=dict)


class StructuredStoreAdapter:
    """
    结构化存储适配器
    
    使用方式:
        store = StructuredStoreAdapter()
        
        # 存储表格
        store.store_table(doc_id, chunk_id, table_structure)
        
        # 查询时间序列
        results = store.query_time_series("钢筋", "2024-01", "2024-12")
    """
    
    def __init__(self, config: Optional[StructuredStoreConfig] = None):
        """
        初始化结构化存储
        
        Args:
            config: PostgreSQL配置
        """
        if not POSTGRES_AVAILABLE:
            raise ImportError("psycopg2 is required for structured store")
        
        self.config = config or get_config().structured_store
        self._conn = None
        self._pool = None
        
        self._init_connection()
        self._init_tables()
        
        logger.info(f"结构化存储初始化完成: {self.config.host}:{self.config.port}/{self.config.database}")
    
    def _init_connection(self):
        """初始化数据库连接"""
        try:
            self._conn = psycopg2.connect(
                host=self.config.host,
                port=self.config.port,
                database=self.config.database,
                user=self.config.username,
                password=self.config.password.get_secret_value() if hasattr(self.config.password, 'get_secret_value') else self.config.password
            )
            self._conn.autocommit = False
            logger.info("✅ PostgreSQL连接成功")
        except Exception as e:
            logger.error(f"❌ PostgreSQL连接失败: {e}")
            raise
    
    def _get_cursor(self):
        """获取游标"""
        if self._conn is None or self._conn.closed:
            self._init_connection()
        return self._conn.cursor()
    
    def _init_tables(self):
        """初始化数据库表结构"""
        try:
            cursor = self._get_cursor()
            
            # 1. 表格元数据表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS table_metadata (
                    table_id VARCHAR(128) PRIMARY KEY,
                    doc_id VARCHAR(128) NOT NULL,
                    chunk_id VARCHAR(128) NOT NULL,
                    table_name VARCHAR(255),
                    page_number INTEGER,
                    headers JSONB,
                    row_count INTEGER DEFAULT 0,
                    col_count INTEGER DEFAULT 0,
                    table_type VARCHAR(50) DEFAULT 'data',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    INDEX idx_doc_id (doc_id),
                    INDEX idx_chunk_id (chunk_id)
                )
            """)
            
            # 2. 表格行数据表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS table_rows (
                    row_id SERIAL PRIMARY KEY,
                    table_id VARCHAR(128) NOT NULL REFERENCES table_metadata(table_id) ON DELETE CASCADE,
                    row_index INTEGER NOT NULL,
                    row_data JSONB NOT NULL,
                    numeric_values JSONB,
                    
                    INDEX idx_table_id (table_id),
                    INDEX idx_row_index (table_id, row_index)
                )
            """)
            
            # 3. 时间序列数值表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS time_series (
                    series_id SERIAL PRIMARY KEY,
                    table_id VARCHAR(128) NOT NULL REFERENCES table_metadata(table_id) ON DELETE CASCADE,
                    entity_name VARCHAR(255) NOT NULL,  -- 如: 钢筋_HRB400_Φ12_深圳
                    entity_type VARCHAR(50),  -- material | price | index
                    time_period VARCHAR(50) NOT NULL,  -- 如: 2024-01, 2024-Q1, 2024
                    value DECIMAL(15, 4) NOT NULL,
                    unit VARCHAR(50),
                    region VARCHAR(100),  -- 地区
                    metadata JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    INDEX idx_entity_time (entity_name, time_period),
                    INDEX idx_time_period (time_period),
                    INDEX idx_region (region)
                )
            """)
            
            # 4. 实体-表格关联表 (用于快速查找实体相关表格)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entity_table_mapping (
                    id SERIAL PRIMARY KEY,
                    entity_name VARCHAR(255) NOT NULL,
                    entity_type VARCHAR(50),
                    table_id VARCHAR(128) NOT NULL REFERENCES table_metadata(table_id) ON DELETE CASCADE,
                    confidence FLOAT DEFAULT 1.0,
                    
                    INDEX idx_entity (entity_name),
                    UNIQUE(entity_name, table_id)
                )
            """)
            
            self._conn.commit()
            logger.info("✅ 数据库表初始化完成")
            
        except Exception as e:
            self._conn.rollback()
            logger.error(f"❌ 数据库表初始化失败: {e}")
            raise
    
    def store_table(self, doc_id: str, chunk_id: str, 
                    table_structure: Dict[str, Any],
                    table_name: Optional[str] = None) -> bool:
        """
        存储表格数据
        
        Args:
            doc_id: 文档ID
            chunk_id: 块ID (作为table_id)
            table_structure: 表格结构 {
                'headers': [...],
                'rows': [{'cells': [...], 'row_index': n}, ...],
                'page_number': n
            }
            table_name: 表格名称 (可选)
        
        Returns:
            是否成功
        """
        try:
            cursor = self._get_cursor()
            table_id = chunk_id
            
            headers = table_structure.get('headers', [])
            rows = table_structure.get('rows', [])
            page_number = table_structure.get('page_number', 0)
            
            # 1. 插入/更新表格元数据
            cursor.execute("""
                INSERT INTO table_metadata 
                    (table_id, doc_id, chunk_id, table_name, page_number, headers, row_count, col_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (table_id) DO UPDATE SET
                    headers = EXCLUDED.headers,
                    row_count = EXCLUDED.row_count,
                    col_count = EXCLUDED.col_count,
                    table_name = EXCLUDED.table_name
            """, (
                table_id, doc_id, chunk_id,
                table_name or f"Table_{doc_id}_{page_number}",
                page_number,
                Json(headers),
                len(rows),
                len(headers)
            ))
            
            # 2. 删除旧行数据
            cursor.execute("DELETE FROM table_rows WHERE table_id = %s", (table_id,))
            
            # 3. 插入新行数据
            for row in rows:
                cells = row.get('cells', [])
                row_index = row.get('row_index', 0)
                
                # 构建行数据字典
                row_data = {}
                numeric_values = {}
                
                for i, cell in enumerate(cells):
                    if i < len(headers):
                        col_name = headers[i]
                        row_data[col_name] = cell
                        
                        # 尝试提取数值
                        num_val = self._extract_numeric(cell)
                        if num_val is not None:
                            numeric_values[col_name] = num_val
                
                cursor.execute("""
                    INSERT INTO table_rows (table_id, row_index, row_data, numeric_values)
                    VALUES (%s, %s, %s, %s)
                """, (table_id, row_index, Json(row_data), Json(numeric_values)))
            
            # 4. 提取并存储实体关联
            entities = self._extract_entities_from_table(headers, rows)
            for entity_name, entity_type in entities:
                cursor.execute("""
                    INSERT INTO entity_table_mapping (entity_name, entity_type, table_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (entity_name, table_id) DO NOTHING
                """, (entity_name, entity_type, table_id))
            
            self._conn.commit()
            logger.info(f"✅ 表格存储完成: {table_id} ({len(rows)}行)")
            return True
            
        except Exception as e:
            self._conn.rollback()
            logger.error(f"❌ 表格存储失败: {e}")
            return False
    
    def store_time_series(self, table_id: str, entity_name: str,
                          time_period: str, value: float,
                          unit: str = "",
                          region: Optional[str] = None,
                          entity_type: str = "price",
                          metadata: Optional[Dict] = None) -> bool:
        """
        存储时间序列数据点
        
        Args:
            table_id: 来源表格ID
            entity_name: 实体名称 (如: 钢筋_HRB400_Φ12)
            time_period: 时间周期 (如: 2024-01, 2024-Q1, 2024)
            value: 数值
            unit: 单位
            region: 地区 (可选)
            entity_type: 实体类型
            metadata: 附加元数据
        
        Returns:
            是否成功
        """
        try:
            cursor = self._get_cursor()
            
            cursor.execute("""
                INSERT INTO time_series 
                    (table_id, entity_name, entity_type, time_period, value, unit, region, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (table_id, entity_name, time_period) DO UPDATE SET
                    value = EXCLUDED.value,
                    unit = EXCLUDED.unit,
                    region = EXCLUDED.region,
                    metadata = EXCLUDED.metadata
            """, (
                table_id, entity_name, entity_type, time_period, value, unit, region,
                Json(metadata or {})
            ))
            
            self._conn.commit()
            return True
            
        except Exception as e:
            self._conn.rollback()
            logger.error(f"❌ 时间序列存储失败: {e}")
            return False
    
    def query_time_series(self, entity_name: str,
                          start_period: Optional[str] = None,
                          end_period: Optional[str] = None,
                          region: Optional[str] = None,
                          limit: int = 100) -> List[Dict[str, Any]]:
        """
        查询时间序列数据
        
        Args:
            entity_name: 实体名称 (支持模糊匹配)
            start_period: 开始时间 (如: 2024-01)
            end_period: 结束时间
            region: 地区过滤
            limit: 最大返回数量
        
        Returns:
            时间序列数据点列表
        """
        try:
            cursor = self._get_cursor()
            
            query = """
                SELECT ts.*, tm.doc_id, tm.table_name
                FROM time_series ts
                JOIN table_metadata tm ON ts.table_id = tm.table_id
                WHERE ts.entity_name ILIKE %s
            """
            params = [f"%{entity_name}%"]
            
            if start_period:
                query += " AND ts.time_period >= %s"
                params.append(start_period)
            
            if end_period:
                query += " AND ts.time_period <= %s"
                params.append(end_period)
            
            if region:
                query += " AND ts.region = %s"
                params.append(region)
            
            query += " ORDER BY ts.time_period LIMIT %s"
            params.append(limit)
            
            cursor.execute(query, params)
            
            columns = [desc[0] for desc in cursor.description]
            results = []
            
            for row in cursor.fetchall():
                result = dict(zip(columns, row))
                # 转换 metadata JSONB
                if 'metadata' in result and result['metadata']:
                    result['metadata'] = json.loads(result['metadata']) if isinstance(result['metadata'], str) else result['metadata']
                results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"❌ 时间序列查询失败: {e}")
            return []
    
    def query_table_by_entity(self, entity_name: str,
                              limit: int = 10) -> List[Dict[str, Any]]:
        """
        通过实体查询相关表格
        
        Args:
            entity_name: 实体名称
            limit: 最大返回数量
        
        Returns:
            表格元数据列表
        """
        try:
            cursor = self._get_cursor()
            
            cursor.execute("""
                SELECT DISTINCT tm.*
                FROM table_metadata tm
                JOIN entity_table_mapping etm ON tm.table_id = etm.table_id
                WHERE etm.entity_name ILIKE %s
                ORDER BY tm.created_at DESC
                LIMIT %s
            """, (f"%{entity_name}%", limit))
            
            columns = [desc[0] for desc in cursor.description]
            results = []
            
            for row in cursor.fetchall():
                result = dict(zip(columns, row))
                if 'headers' in result and result['headers']:
                    result['headers'] = json.loads(result['headers']) if isinstance(result['headers'], str) else result['headers']
                results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"❌ 实体表格查询失败: {e}")
            return []
    
    def get_table_data(self, table_id: str) -> Optional[Dict[str, Any]]:
        """
        获取完整表格数据
        
        Args:
            table_id: 表格ID
        
        Returns:
            包含元数据和行数据的字典
        """
        try:
            cursor = self._get_cursor()
            
            # 获取元数据
            cursor.execute("SELECT * FROM table_metadata WHERE table_id = %s", (table_id,))
            meta_row = cursor.fetchone()
            
            if not meta_row:
                return None
            
            columns = [desc[0] for desc in cursor.description]
            metadata = dict(zip(columns, meta_row))
            
            # 解析 headers JSONB
            if 'headers' in metadata and metadata['headers']:
                metadata['headers'] = json.loads(metadata['headers']) if isinstance(metadata['headers'], str) else metadata['headers']
            
            # 获取行数据
            cursor.execute("""
                SELECT row_index, row_data, numeric_values
                FROM table_rows
                WHERE table_id = %s
                ORDER BY row_index
            """, (table_id,))
            
            rows = []
            for row in cursor.fetchall():
                row_data = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                numeric_values = json.loads(row[2]) if isinstance(row[2], str) else row[2]
                rows.append({
                    'row_index': row[0],
                    'data': row_data,
                    'numeric_values': numeric_values
                })
            
            return {
                'metadata': metadata,
                'rows': rows
            }
            
        except Exception as e:
            logger.error(f"❌ 表格数据获取失败: {e}")
            return None
    
    def delete_document_tables(self, doc_id: str) -> bool:
        """
        删除文档的所有表格数据
        
        Args:
            doc_id: 文档ID
        
        Returns:
            是否成功
        """
        try:
            cursor = self._get_cursor()
            cursor.execute("DELETE FROM table_metadata WHERE doc_id = %s", (doc_id,))
            self._conn.commit()
            logger.info(f"✅ 删除文档表格: {doc_id}")
            return True
        except Exception as e:
            self._conn.rollback()
            logger.error(f"❌ 删除文档表格失败: {e}")
            return False
    
    def close(self):
        """关闭连接"""
        if self._conn and not self._conn.closed:
            self._conn.close()
            logger.info("✅ PostgreSQL连接已关闭")
    
    def _extract_numeric(self, value: Any) -> Optional[float]:
        """从单元格值中提取数值"""
        if value is None:
            return None
        
        # 转换为字符串并清理
        text = str(value).replace(',', '').replace('，', '')
        
        # 提取数字
        import re
        numbers = re.findall(r'-?\d+\.?\d*', text)
        
        if numbers:
            try:
                return float(numbers[0])
            except ValueError:
                pass
        
        return None
    
    def _extract_entities_from_table(self, headers: List[str], 
                                      rows: List[Dict]) -> List[Tuple[str, str]]:
        """从表格中提取实体"""
        entities = []
        
        # 材料实体模式
        material_pattern = r'(钢筋|混凝土|水泥|砂石|木材|沥青|钢材|铝材|玻璃|砖|瓦|涂料|防水材料|保温材料|管材|线材|电缆|电气设备|机械)(?:[A-Z0-9]*)?(?:[_\s]?[Φφ]?\d+)?'
        
        # 从所有文本中提取
        all_text = ' '.join(headers)
        for row in rows:
            all_text += ' ' + ' '.join(str(cell) for cell in row.get('cells', []))
        
        # 查找材料
        for match in re.finditer(material_pattern, all_text):
            material = match.group(0)
            if len(material) >= 2:
                entities.append((material, 'material'))
        
        # 去重
        seen = set()
        unique_entities = []
        for name, type_ in entities:
            key = (name, type_)
            if key not in seen:
                seen.add(key)
                unique_entities.append((name, type_))
        
        return unique_entities


# 便捷函数
def get_structured_store() -> Optional[StructuredStoreAdapter]:
    """
    获取结构化存储实例
    
    Returns:
        StructuredStoreAdapter 实例，如果不可用则返回 None
    """
    if not POSTGRES_AVAILABLE:
        return None
    
    try:
        return StructuredStoreAdapter()
    except Exception as e:
        logger.error(f"结构化存储初始化失败: {e}")
        return None


if __name__ == "__main__":
    # 测试代码
    print("=" * 70)
    print("结构化存储适配器测试")
    print("=" * 70)
    
    if not POSTGRES_AVAILABLE:
        print("\n⚠️ psycopg2 未安装，跳过测试")
        print("请运行: pip install psycopg2-binary")
        sys.exit(0)
    
    try:
        store = StructuredStoreAdapter()
        
        # 测试表格存储
        test_table = {
            'headers': ['月份', '规格', '价格(元/吨)', '地区'],
            'rows': [
                {'cells': ['2024-01', 'HRB400 Φ12', '3850', '深圳'], 'row_index': 0},
                {'cells': ['2024-02', 'HRB400 Φ12', '3880', '深圳'], 'row_index': 1},
                {'cells': ['2024-03', 'HRB400 Φ12', '3920', '深圳'], 'row_index': 2},
            ],
            'page_number': 1
        }
        
        success = store.store_table(
            doc_id="test_doc_001",
            chunk_id="test_table_001",
            table_structure=test_table,
            table_name="2024年深圳钢筋价格表"
        )
        print(f"\n✅ 表格存储: {'成功' if success else '失败'}")
        
        # 测试时间序列存储
        store.store_time_series(
            table_id="test_table_001",
            entity_name="钢筋_HRB400_Φ12_深圳",
            time_period="2024-01",
            value=3850.0,
            unit="元/吨",
            region="深圳",
            entity_type="price"
        )
        print("✅ 时间序列存储: 成功")
        
        # 测试查询
        results = store.query_time_series("钢筋", "2024-01", "2024-12", region="深圳")
        print(f"\n✅ 时间序列查询: 找到 {len(results)} 条记录")
        for r in results[:3]:
            print(f"   {r['time_period']}: {r['value']} {r['unit']}")
        
        # 测试实体查询
        tables = store.query_table_by_entity("钢筋")
        print(f"\n✅ 实体表格查询: 找到 {len(tables)} 个表格")
        
        store.close()
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
    
    print("\n" + "=" * 70)
    print("测试完成!")
    print("=" * 70)
