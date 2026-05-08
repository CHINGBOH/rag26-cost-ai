"""
Feature Flag Repository - 数据库访问层
提供 feature flags 的 CRUD 操作
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import asyncpg
import logging

logger = logging.getLogger(__name__)


class FeatureFlagModel:
    """Feature Flag 数据模型"""
    
    def __init__(
        self,
        flag_name: str,
        enabled: bool,
        description: Optional[str] = None,
        rollout_percentage: int = 100,
        target_users: List[str] = None,
        target_environments: List[str] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        updated_by: Optional[str] = None,
        metadata: Dict[str, Any] = None
    ):
        self.flag_name = flag_name
        self.enabled = enabled
        self.description = description
        self.rollout_percentage = rollout_percentage
        self.target_users = target_users or []
        self.target_environments = target_environments or ["production", "staging", "development"]
        self.created_at = created_at
        self.updated_at = updated_at
        self.updated_by = updated_by
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "flag_name": self.flag_name,
            "enabled": self.enabled,
            "description": self.description,
            "rollout_percentage": self.rollout_percentage,
            "target_users": self.target_users,
            "target_environments": self.target_environments,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "updated_by": self.updated_by,
            "metadata": self.metadata
        }


class FeatureFlagRepository:
    """
    Feature Flag 数据库访问层
    
    示例用法:
        ```python
        from config.feature_flag_repository import FeatureFlagRepository
        from config.loader import get_config
        
        config = get_config()
        repo = FeatureFlagRepository(config.database.url)
        
        # 获取所有 flags
        flags = await repo.get_all()
        
        # 更新 flag
        await repo.update("FOLLOWUP_STRICT_COVERAGE", enabled=True, updated_by="admin")
        ```
    """
    
    def __init__(self, database_url: str):
        """
        初始化 Repository
        
        Args:
            database_url: PostgreSQL 连接字符串
        """
        self.database_url = database_url
        self._pool: Optional[asyncpg.Pool] = None
    
    async def _get_pool(self) -> asyncpg.Pool:
        """获取连接池（懒加载）"""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=10)
        return self._pool
    
    async def close(self):
        """关闭连接池"""
        if self._pool:
            await self._pool.close()
            self._pool = None
    
    async def get_all(self) -> List[FeatureFlagModel]:
        """获取所有 feature flags"""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM feature_flags ORDER BY flag_name")
            return [self._row_to_model(row) for row in rows]
    
    async def get(self, flag_name: str) -> Optional[FeatureFlagModel]:
        """获取单个 feature flag"""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM feature_flags WHERE flag_name = $1",
                flag_name
            )
            return self._row_to_model(row) if row else None
    
    async def update(
        self,
        flag_name: str,
        enabled: Optional[bool] = None,
        description: Optional[str] = None,
        rollout_percentage: Optional[int] = None,
        target_users: Optional[List[str]] = None,
        target_environments: Optional[List[str]] = None,
        updated_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[FeatureFlagModel]:
        """
        更新 feature flag
        
        Args:
            flag_name: Flag 名称
            enabled: 是否启用
            description: 描述
            rollout_percentage: 灰度百分比
            target_users: 目标用户列表
            target_environments: 目标环境列表
            updated_by: 更新人
            metadata: 附加元数据
        
        Returns:
            更新后的 FeatureFlagModel，如果 flag 不存在则返回 None
        """
        pool = await self._get_pool()
        
        # 构建更新 SQL
        updates = []
        values = []
        param_idx = 1
        
        if enabled is not None:
            updates.append(f"enabled = ${param_idx}")
            values.append(enabled)
            param_idx += 1
        
        if description is not None:
            updates.append(f"description = ${param_idx}")
            values.append(description)
            param_idx += 1
        
        if rollout_percentage is not None:
            updates.append(f"rollout_percentage = ${param_idx}")
            values.append(rollout_percentage)
            param_idx += 1
        
        if target_users is not None:
            updates.append(f"target_users = ${param_idx}")
            values.append(target_users)
            param_idx += 1
        
        if target_environments is not None:
            updates.append(f"target_environments = ${param_idx}")
            values.append(target_environments)
            param_idx += 1
        
        if updated_by is not None:
            updates.append(f"updated_by = ${param_idx}")
            values.append(updated_by)
            param_idx += 1
        
        if metadata is not None:
            updates.append(f"metadata = ${param_idx}")
            values.append(metadata)
            param_idx += 1
        
        if not updates:
            # 没有更新字段
            return await self.get(flag_name)
        
        sql = f"""
            UPDATE feature_flags
            SET {', '.join(updates)}
            WHERE flag_name = ${param_idx}
            RETURNING *
        """
        values.append(flag_name)
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, *values)
            if row:
                logger.info(f"[FeatureFlagRepository] Updated flag: {flag_name}")
                return self._row_to_model(row)
            else:
                logger.warning(f"[FeatureFlagRepository] Flag not found: {flag_name}")
                return None
    
    async def create(
        self,
        flag_name: str,
        enabled: bool = False,
        description: Optional[str] = None,
        rollout_percentage: int = 0,
        target_users: Optional[List[str]] = None,
        target_environments: Optional[List[str]] = None,
        updated_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> FeatureFlagModel:
        """创建新的 feature flag"""
        pool = await self._get_pool()
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO feature_flags (
                    flag_name, enabled, description, rollout_percentage,
                    target_users, target_environments, updated_by, metadata
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING *
                """,
                flag_name,
                enabled,
                description,
                rollout_percentage,
                target_users or [],
                target_environments or ["production", "staging", "development"],
                updated_by,
                metadata or {}
            )
            logger.info(f"[FeatureFlagRepository] Created flag: {flag_name}")
            return self._row_to_model(row)
    
    async def delete(self, flag_name: str) -> bool:
        """删除 feature flag"""
        pool = await self._get_pool()
        
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM feature_flags WHERE flag_name = $1",
                flag_name
            )
            deleted = result == "DELETE 1"
            if deleted:
                logger.info(f"[FeatureFlagRepository] Deleted flag: {flag_name}")
            return deleted
    
    async def get_history(self, flag_name: str, limit: int = 50) -> List[Dict[str, Any]]:
        """获取 feature flag 变更历史"""
        pool = await self._get_pool()
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT *
                FROM feature_flag_history
                WHERE flag_name = $1
                ORDER BY changed_at DESC
                LIMIT $2
                """,
                flag_name,
                limit
            )
            return [dict(row) for row in rows]
    
    @staticmethod
    def _row_to_model(row) -> FeatureFlagModel:
        """将数据库行转换为模型"""
        return FeatureFlagModel(
            flag_name=row["flag_name"],
            enabled=row["enabled"],
            description=row["description"],
            rollout_percentage=row["rollout_percentage"],
            target_users=row["target_users"],
            target_environments=row["target_environments"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            updated_by=row["updated_by"],
            metadata=row["metadata"]
        )
