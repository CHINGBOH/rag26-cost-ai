"""
Layer 3 Executor - Issue #96
执行修复补丁，验证效果，更新数据库状态

执行器是闭环学习系统的"行动者"：
1. 应用修复补丁（Patch）到系统配置/代码
2. 运行验证测试（test_agent_16.py）
3. 对比优化前后的成功率
4. 更新数据库状态记录
"""

import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg2
import yaml
from app.agent.event_ledger import insert_improvement_event
from app.agent.learning_state import (
    DEFAULT_OBSERVATION_WINDOW_DAYS,
    coerce_json_dict,
    update_knowledge_gap_status,
)

logger = logging.getLogger(__name__)


class PatchStatus(Enum):
    """补丁状态"""
    PENDING = "pending"
    APPLYING = "applying"
    APPLIED = "applied"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    REVERTED = "reverted"
    FAILED = "failed"


@dataclass
class PatchApplication:
    """补丁应用信息"""
    patch_id: str  # UUID
    event_id: int  # improvement_events.id
    affected_route: str  # R1-R5
    patch_type: str  # 'prompt' | 'weight' | 'tool_order' | 'path' | 'feature'
    patch_payload: Dict[str, Any]
    status: PatchStatus
    applied_at: Optional[float] = None
    verified_at: Optional[float] = None
    verification_result: Optional[Dict] = None
    error_msg: Optional[str] = None
    reversible: bool = True
    recovery_point: Optional[str] = None  # git commit sha or snapshot id


class PatchExecutor:
    """执行修复补丁，验证效果，更新状态"""

    def __init__(self, pool=None):
        """
        初始化执行器

        Args:
            pool: psycopg2.pool.ThreadedConnectionPool，若为None则使用工具的默认池
        """
        self.pool = pool
        # Tolerant path resolution: container layout has fewer parents than host (#154)
        parents = Path(__file__).resolve().parents
        self.repo_root = parents[5] if len(parents) > 5 else parents[-1]
        self.test_script = self.repo_root / "tests" / "test_agent_16.py"
        self.config_path = self.repo_root / "config" / "config.yaml"

    def _get_pool(self):
        """获取数据库连接池"""
        if self.pool is not None:
            return self.pool

        from app.agent.tools import _get_pool
        return _get_pool()

    def _get_db_conn(self):
        """从池获取数据库连接"""
        return self._get_pool().getconn()

    def _put_db_conn(self, conn, error: bool = False):
        """返回数据库连接到池"""
        try:
            self._get_pool().putconn(conn, close=error)
        except Exception as e:
            logger.warning(f"Failed to return connection to pool: {e}")

    async def apply_patch(self, patch: PatchApplication) -> PatchApplication:
        """
        应用单个补丁

        步骤：
        1. 检查补丁合法性
        2. 创建恢复点（git commit）
        3. 应用补丁（修改配置/prompt）
        4. 验证系统仍可运行
        5. 记录 improvement_events.applied_at
        """
        try:
            patch.status = PatchStatus.APPLYING

            # Step 1: 验证补丁格式
            self._validate_patch(patch)

            # Step 2: 创建恢复点
            if patch.reversible:
                patch.recovery_point = await self._create_recovery_point(patch)

            # Step 3: 应用补丁（根据 affected_route）
            await self._apply_by_route(patch)

            # Step 4: 快速健康检查
            await self._health_check()

            # Step 5: 更新数据库
            await self._record_application(patch)

            patch.status = PatchStatus.APPLIED
            patch.applied_at = time.time()

            logger.info(f"✅ Patch applied successfully: {patch.patch_id}")
            return patch

        except Exception as e:
            patch.status = PatchStatus.FAILED
            patch.error_msg = str(e)
            logger.error(f"❌ Patch application failed: {e}", exc_info=True)
            raise

    async def _apply_by_route(self, patch: PatchApplication):
        """根据 affected_route 应用不同的补丁"""
        route = patch.affected_route
        payload = patch.patch_payload

        if route == "R1_navigator_dict":
            # 修改 navigator 的问题类型判别规则
            await self._patch_navigator_dict(payload)

        elif route == "R2_path_default":
            # 修改默认路径选择
            await self._patch_path_default(payload)

        elif route == "R3_planner_examples":
            # 补充 few-shot examples
            await self._patch_planner_examples(payload)

        elif route == "R4_rerank_weights":
            # 调整重排权重
            await self._patch_rerank_weights(payload)

        elif route == "R5_tool_priority":
            # 调整工具优先级
            await self._patch_tool_priority(payload)

        else:
            raise ValueError(f"Unknown route: {route}")

    async def _patch_navigator_dict(self, payload: Dict[str, Any]):
        """R1: 修改问题类型判别规则"""
        config = await self._load_yaml()

        if "navigator_dict" in payload:
            if "navigator" not in config:
                config["navigator"] = {}
            config["navigator"].update(payload["navigator_dict"])

        await self._save_yaml(config)
        logger.info(f"Applied R1 navigator patch: {list(payload.keys())}")

    async def _patch_path_default(self, payload: Dict[str, Any]):
        """R2: 修改默认路径选择"""
        config = await self._load_yaml()

        if "path" in payload:
            if "retrieval" not in config:
                config["retrieval"] = {}
            config["retrieval"]["default_path"] = payload["path"]

        await self._save_yaml(config)
        logger.info(f"Applied R2 path patch: {payload.get('path')}")

    async def _patch_planner_examples(self, payload: Dict[str, Any]):
        """R3: 补充 few-shot examples"""
        config = await self._load_yaml()

        if "examples" in payload:
            if "planner" not in config:
                config["planner"] = {}
            if "examples" not in config["planner"]:
                config["planner"]["examples"] = []
            config["planner"]["examples"].extend(payload["examples"])

        await self._save_yaml(config)
        logger.info(f"Applied R3 planner examples patch: +{len(payload.get('examples', []))} examples")

    async def _patch_rerank_weights(self, payload: Dict[str, Any]):
        """R4: 调整重排权重"""
        config = await self._load_yaml()

        if "weights" in payload:
            if "reranker" not in config:
                config["reranker"] = {}
            config["reranker"]["weights"] = payload["weights"]

        await self._save_yaml(config)
        logger.info(f"Applied R4 rerank weights: {payload['weights']}")

    async def _patch_tool_priority(self, payload: Dict[str, Any]):
        """R5: 调整工具优先级"""
        config = await self._load_yaml()

        if "priority" in payload:
            if "tools" not in config:
                config["tools"] = {}
            config["tools"]["priority"] = payload["priority"]

        await self._save_yaml(config)
        logger.info(f"Applied R5 tool priority patch: {payload['priority']}")

    async def _health_check(self):
        """快速健康检查：确保系统还能启动"""
        try:
            # Compile or fetch the current agent graph to validate config/runtime wiring.
            from app.agent.graph import get_agent_graph

            get_agent_graph()
            logger.info("✅ Health check passed")
        except Exception as e:
            raise Exception(f"❌ Health check failed: {e}")

    async def verify_patch(self, patch: PatchApplication) -> PatchApplication:
        """
        验证补丁效果：运行 test_agent_16.py，对比修改前后

        步骤：
        1. 运行测试获取修改后的成功率
        2. 从数据库读取修改前的基准
        3. 计算改进
        4. 如果改进不足，自动还原
        5. 记录验证结果
        """
        try:
            patch.status = PatchStatus.VERIFYING

            # Step 1: 运行测试
            test_result = await self._run_test_suite()
            after_rate = test_result["success_rate"]

            # Step 2: 读取基准
            before_rate = await self._get_baseline_success_rate()

            # Step 3: 计算改进
            delta = after_rate - before_rate
            improvement_pct = (delta / before_rate * 100) if before_rate > 0 else 0

            # Step 4: 判断是否成功
            IMPROVEMENT_THRESHOLD = 0.02  # 2% 改进阈值
            success = delta >= IMPROVEMENT_THRESHOLD

            if not success:
                logger.warning(
                    f"⚠️ Patch didn't meet improvement threshold. "
                    f"Before: {before_rate:.1%}, After: {after_rate:.1%}, Delta: {delta:.1%}"
                )
                if patch.reversible:
                    await self.revert_patch(patch)
                    patch.status = PatchStatus.REVERTED
                    patch.verification_result = {
                        "before_rate": before_rate,
                        "after_rate": after_rate,
                        "delta": delta,
                        "success": False,
                        "reason": "Insufficient improvement",
                    }
                    return patch

            # Step 5: 记录验证结果
            await self._record_verification(patch, test_result, before_rate, after_rate)

            patch.status = PatchStatus.VERIFIED
            patch.verified_at = time.time()
            patch.verification_result = {
                "before_rate": before_rate,
                "after_rate": after_rate,
                "delta": delta,
                "improvement_pct": improvement_pct,
                "success": True,
                "test_result": test_result,
            }

            logger.info(
                f"✅ Patch verified successfully: "
                f"Before={before_rate:.1%}, After={after_rate:.1%}, Delta={delta:.1%}"
            )

            return patch

        except Exception as e:
            patch.status = PatchStatus.FAILED
            patch.error_msg = str(e)
            logger.error(f"❌ Patch verification failed: {e}", exc_info=True)
            raise

    async def revert_patch(self, patch: PatchApplication):
        """还原补丁：回到恢复点"""
        if not patch.reversible or not patch.recovery_point:
            raise Exception("Patch is not reversible")

        try:
            # git reset --hard <recovery_point>
            result = await self._run_command(
                f"git -C {self.repo_root} reset --hard {patch.recovery_point}"
            )
            logger.info(f"✅ Reverted patch {patch.patch_id} to {patch.recovery_point}")
        except Exception as e:
            logger.error(f"❌ Revert failed: {e}")
            raise

    async def _run_test_suite(self) -> Dict[str, Any]:
        """
        运行 test_agent_16.py，获取成功率

        返回：
        {
            'success_rate': 0.75,  # 12/16
            'total': 16,
            'passed': 12,
            'failed': 4,
            'duration': 120.5,
        }
        """
        try:
            if not self.test_script.exists():
                raise FileNotFoundError(f"Test script not found: {self.test_script}")

            cmd = f"cd {self.repo_root} && python {self.test_script}"
            output = await self._run_command(cmd, timeout=600)

            # 解析输出和结果文件
            result = await self._parse_test_output(output)
            return result

        except subprocess.TimeoutExpired:
            raise Exception("Test suite timeout (>10min)")
        except Exception as e:
            raise Exception(f"Test execution failed: {e}")

    async def _parse_test_output(self, output: str) -> Dict[str, Any]:
        """
        解析 test_agent_16.py 的输出和结果文件

        test_agent_16.py 会输出结果到 logs/agent_test_16_results.json
        """
        results_file = self.repo_root / "logs" / "agent_test_16_results.json"

        if not results_file.exists():
            raise Exception(f"Test results file not found: {results_file}")

        try:
            with open(results_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            summary = data.get("summary", {})
            total = summary.get("total", 0)
            passed = summary.get("passed", 0)

            if total == 0:
                raise Exception("Test returned 0 total questions")

            success_rate = passed / total

            return {
                "success_rate": success_rate,
                "total": total,
                "passed": passed,
                "failed": total - passed,
                "avg_confidence": summary.get("avg_confidence", 0),
                "raw_output": output,
            }

        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse test results JSON: {e}")

    async def _get_baseline_success_rate(self) -> float:
        """
        从数据库读取修改前的基准成功率

        查询逻辑：
        1. 查询最新已验证的 improvement_event（verified_at 不为 null）
        2. 如果没有，查询最新的 test_agent_16 结果
        3. 如果还没有，假设基准为 0.5 (50%)
        """
        conn = None
        try:
            conn = self._get_db_conn()
            cursor = conn.cursor()

            # 查询最新的已验证修复
            cursor.execute(
                """
                SELECT verification_result->>'after_rate' as rate
                FROM improvement_events
                WHERE applied_at IS NOT NULL AND verified_at IS NOT NULL
                ORDER BY verified_at DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()

            if row and row[0]:
                rate = float(row[0])
                logger.info(f"Baseline rate from verified event: {rate:.1%}")
                cursor.close()
                return rate

            # 否则查询最新的 learning_summary（如果表存在）
            try:
                cursor.execute(
                    """
                    SELECT success_rate FROM learning_summary
                    ORDER BY created_at DESC LIMIT 1
                    """
                )
                row = cursor.fetchone()

                if row:
                    rate = float(row[0])
                    logger.info(f"Baseline rate from learning_summary: {rate:.1%}")
                    cursor.close()
                    return rate
            except psycopg2.ProgrammingError:
                # learning_summary 表不存在，继续
                pass

            cursor.close()

            # 默认基准
            logger.warning("No baseline found, using default 0.5")
            return 0.5

        except Exception as e:
            logger.warning(f"Failed to get baseline: {e}, using 0.5")
            return 0.5
        finally:
            if conn:
                self._put_db_conn(conn, error=False)

    async def _record_application(self, patch: PatchApplication):
        """在数据库记录补丁应用"""
        conn = None
        try:
            conn = self._get_db_conn()
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE improvement_events
                SET applied_at = NOW(), actor = 'auto_executor'
                WHERE id = %s
                """,
                (patch.event_id,),
            )
            insert_improvement_event(
                cursor,
                event_id=patch.event_id,
                patch_id=patch.patch_id,
                affected_route=patch.affected_route,
                patch_type=patch.patch_type,
                status="applied",
                event_type="improvement.event.applied",
                gap_key=patch.patch_payload.get("gap_key"),
                recovery_point=patch.recovery_point,
            )

            conn.commit()
            cursor.close()
            logger.info(f"Recorded patch application in DB: event_id={patch.event_id}")

            gap_key = patch.patch_payload.get("gap_key")
            if gap_key:
                try:
                    update_knowledge_gap_status(
                        gap_key,
                        "in_progress",
                        f"Applying strategy: {patch.patch_payload.get('description') or patch.patch_type}",
                        metadata_patch={"event_id": patch.event_id, "last_execution_phase": "applied"},
                        linked_event_id=patch.event_id,
                        owner="auto_executor",
                        pool=self.pool,
                    )
                except Exception:
                    logger.warning("Failed to mark knowledge gap in progress", exc_info=True)

        except Exception as e:
            logger.error(f"Failed to record application: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                self._put_db_conn(conn, error=False)

    async def _record_verification(self, patch, test_result, before_rate, after_rate):
        """在数据库记录验证结果"""
        conn = None
        try:
            conn = self._get_db_conn()
            cursor = conn.cursor()

            verification_result = {
                "test_result": test_result,
                "before_rate": before_rate,
                "after_rate": after_rate,
                "delta": after_rate - before_rate,
                "improved": after_rate > before_rate,
            }

            cursor.execute(
                """
                UPDATE improvement_events
                SET verified_at = NOW(),
                    verification_result = %s::jsonb
                WHERE id = %s
                """,
                (json.dumps(verification_result), patch.event_id),
            )
            insert_improvement_event(
                cursor,
                event_id=patch.event_id,
                patch_id=patch.patch_id,
                affected_route=patch.affected_route,
                patch_type=patch.patch_type,
                status="verified" if after_rate > before_rate else "blocked",
                event_type="improvement.event.verified",
                gap_key=patch.patch_payload.get("gap_key"),
                verification_result=verification_result,
                recovery_point=patch.recovery_point,
            )

            conn.commit()
            cursor.close()
            logger.info(f"Recorded verification result in DB: event_id={patch.event_id}")

            gap_key = patch.patch_payload.get("gap_key")
            if gap_key:
                final_status = "observing" if after_rate > before_rate else "blocked"
                try:
                    update_knowledge_gap_status(
                        gap_key,
                        final_status,
                        (
                            f"{patch.patch_payload.get('description') or patch.patch_type}: "
                            f"{before_rate:.1%} -> {after_rate:.1%} "
                            f"(delta {after_rate - before_rate:+.1%})"
                        ),
                        metadata_patch={
                            "event_id": patch.event_id,
                            "verification_result": verification_result,
                            "last_execution_phase": "verified",
                            "observation_window_days": DEFAULT_OBSERVATION_WINDOW_DAYS,
                        },
                        linked_event_id=patch.event_id,
                        owner="auto_executor",
                        observation_window_days=DEFAULT_OBSERVATION_WINDOW_DAYS,
                        pool=self.pool,
                    )
                except Exception:
                    logger.warning("Failed to update final knowledge gap state", exc_info=True)

        except Exception as e:
            logger.error(f"Failed to record verification: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                self._put_db_conn(conn, error=False)

    async def _record_failure(self, patch: PatchApplication, error: Exception):
        """Persist executor failures so event status does not remain stuck in applied/approved."""
        conn = None
        try:
            conn = self._get_db_conn()
            cursor = conn.cursor()

            verification_result = {
                "success": False,
                "status": "failed",
                "error": str(error),
                "failed_at": datetime.utcnow().isoformat() + "Z",
            }

            cursor.execute(
                """
                UPDATE improvement_events
                SET verification_result = COALESCE(verification_result, '{}'::jsonb) || %s::jsonb
                WHERE id = %s
                """,
                (json.dumps(verification_result), patch.event_id),
            )

            conn.commit()
            cursor.close()
            logger.info("Recorded executor failure in DB: event_id=%s", patch.event_id)
        except Exception as exc:
            logger.error("Failed to record executor failure: %s", exc)
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                self._put_db_conn(conn, error=False)

    # ─── 辅助方法 ─────────────────────────────────

    async def _load_yaml(self) -> Dict[str, Any]:
        """异步加载 YAML 配置"""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            return config
        except Exception as e:
            raise Exception(f"Failed to load config: {e}")

    async def _save_yaml(self, config: Dict[str, Any]):
        """异步保存 YAML 配置"""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
            logger.info(f"Saved config to {self.config_path}")
        except Exception as e:
            raise Exception(f"Failed to save config: {e}")

    async def _create_recovery_point(self, patch: PatchApplication) -> str:
        """创建恢复点（git commit）"""
        try:
            cmd = f'git -C {self.repo_root} commit -m "Recovery point for patch {patch.patch_id}" --allow-empty'
            output = await self._run_command(cmd)

            # 从 output 提取 commit sha
            # 输出格式: [branch hash] Recovery point...
            match = re.search(r"\[[\w\-]+\s+([a-f0-9]{7,40})", output)
            if match:
                sha = match.group(1)
            else:
                # 尝试另一种格式
                match = re.search(r"([a-f0-9]{7,40})", output)
                sha = match.group(1) if match else "HEAD"

            logger.info(f"Created recovery point: {sha}")
            return sha

        except Exception as e:
            logger.warning(f"Failed to create recovery point: {e}")
            # 不失败，只是无法回滚
            return "HEAD"

    async def _run_command(self, cmd: str, timeout: int = 30) -> str:
        """执行 shell 命令"""
        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.communicate(), timeout=5)
                except Exception:
                    pass
                raise subprocess.TimeoutExpired(cmd, timeout)

            if process.returncode != 0:
                stderr_msg = stderr.decode() if stderr else ""
                raise Exception(f"Command failed (rc={process.returncode}): {stderr_msg[:500]}")

            return stdout.decode()

        except asyncio.TimeoutError as e:
            raise subprocess.TimeoutExpired(cmd, timeout)

    def _validate_patch(self, patch: PatchApplication):
        """验证补丁格式"""
        if not patch.patch_id:
            raise ValueError("patch_id is required")
        if not patch.event_id:
            raise ValueError("event_id is required")
        if not patch.affected_route:
            raise ValueError("affected_route is required")
        if patch.affected_route not in [
            "R1_navigator_dict",
            "R2_path_default",
            "R3_planner_examples",
            "R4_rerank_weights",
            "R5_tool_priority",
        ]:
            raise ValueError(f"Invalid affected_route: {patch.affected_route}")
        if not isinstance(patch.patch_payload, dict):
            raise ValueError("patch_payload must be a dictionary")


# ─── 对外 API ────────────────────────────────


async def execute_improvement_event(event_id: int, pool=None) -> Dict[str, Any]:
    """
    执行单个 improvement_event：应用补丁 → 验证 → 更新状态

    Args:
        event_id: improvement_events 表中的 ID
        pool: 可选的 psycopg2 连接池

    Returns:
        执行结果字典
    """
    executor = PatchExecutor(pool=pool)

    # 从数据库读取 event
    conn = None
    try:
        conn = executor._get_db_conn()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, affected_route, patch_payload, applied_at, reverted_at, verified_at, verification_result
            FROM improvement_events
            WHERE id = %s
            """,
            (event_id,),
        )
        row = cursor.fetchone()
        cursor.close()

    finally:
        if conn:
            executor._put_db_conn(conn, error=False)

    if not row:
        raise ValueError(f"Event not found: {event_id}")

    (
        event_id_db,
        affected_route,
        patch_payload,
        applied_at,
        reverted_at,
        verified_at,
        verification_result,
    ) = row
    patch_payload = coerce_json_dict(patch_payload)
    verification_result = coerce_json_dict(verification_result)
    review_status = patch_payload.get("review", {}).get("status")

    if review_status == "rejected":
        return {
            "patch_id": f"patch_{event_id}",
            "status": "rejected",
            "verification_result": verification_result or None,
            "error": "Event was rejected and cannot be executed",
            "success": False,
        }

    if reverted_at:
        return {
            "patch_id": f"patch_{event_id}",
            "status": "reverted",
            "verification_result": verification_result or None,
            "error": "Event was reverted and cannot be executed",
            "success": False,
        }

    if verified_at:
        return {
            "patch_id": f"patch_{event_id}",
            "status": "verified",
            "verification_result": verification_result or None,
            "error": None,
            "success": True,
        }

    if verification_result.get("status") == "failed" or verification_result.get("success") is False:
        return {
            "patch_id": f"patch_{event_id}",
            "status": "failed",
            "verification_result": verification_result or None,
            "error": verification_result.get("error"),
            "success": False,
        }

    if review_status not in {None, "approved"}:
        return {
            "patch_id": f"patch_{event_id}",
            "status": review_status,
            "verification_result": verification_result or None,
            "error": "Event is not approved for execution",
            "success": False,
        }

    # 构建补丁对象
    patch = PatchApplication(
        patch_id=f"patch_{event_id}",
        event_id=event_id_db,
        affected_route=affected_route,
        patch_type=patch_payload.get("type", "unknown") if isinstance(patch_payload, dict) else "unknown",
        patch_payload=patch_payload if isinstance(patch_payload, dict) else {},
        status=PatchStatus.PENDING,
    )

    try:
        if applied_at:
            patch.status = PatchStatus.APPLIED
            patch.applied_at = applied_at.timestamp()
        else:
            patch = await executor.apply_patch(patch)
        patch = await executor.verify_patch(patch)

        return {
            "patch_id": patch.patch_id,
            "status": patch.status.value,
            "verification_result": patch.verification_result,
            "error": patch.error_msg,
            "success": patch.status == PatchStatus.VERIFIED,
        }

    except Exception as e:
        patch.status = PatchStatus.FAILED
        patch.error_msg = str(e)
        try:
            await executor._record_failure(patch, e)
        except Exception:
            logger.warning("Failed to persist executor failure state", exc_info=True)
        gap_key = patch.patch_payload.get("gap_key") if isinstance(patch.patch_payload, dict) else None
        if gap_key:
            try:
                update_knowledge_gap_status(
                    gap_key,
                    "blocked",
                    f"Execution failed: {e}",
                    metadata_patch={"event_id": patch.event_id, "execution_error": str(e)},
                    linked_event_id=patch.event_id,
                    owner="auto_executor",
                    pool=pool,
                )
            except Exception:
                logger.warning("Failed to update knowledge gap after executor error", exc_info=True)
        logger.error(f"Execution failed: {e}", exc_info=True)
        return {
            "patch_id": patch.patch_id,
            "status": patch.status.value,
            "error": str(e),
            "success": False,
        }
