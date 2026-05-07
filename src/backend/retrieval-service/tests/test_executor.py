"""
集成测试：Layer 3 Executor - Issue #96

测试补丁应用、验证、数据库更新等核心逻辑
"""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch as mock_patch
from datetime import datetime

from app.agent.executor import (
    PatchExecutor,
    PatchApplication,
    PatchStatus,
    execute_improvement_event,
)


class TestPatchValidation:
    """补丁验证测试"""

    def test_executor_resolves_repo_paths_from_repo_root(self):
        """Executor should resolve repo-relative paths from the actual repository root."""
        executor = PatchExecutor()

        expected_repo_root = Path(__file__).resolve().parents[4]
        assert executor.repo_root == expected_repo_root
        assert executor.config_path == expected_repo_root / "config" / "config.yaml"
        assert executor.test_script == expected_repo_root / "tests" / "test_agent_16.py"

    def test_validate_patch_missing_id(self):
        """测试缺少 patch_id 的补丁"""
        executor = PatchExecutor()
        patch = PatchApplication(
            patch_id="",
            event_id=1,
            affected_route="R1_navigator_dict",
            patch_type="prompt",
            patch_payload={"key": "value"},
            status=PatchStatus.PENDING,
        )

        with pytest.raises(ValueError, match="patch_id is required"):
            executor._validate_patch(patch)

    def test_validate_patch_invalid_route(self):
        """测试无效的 affected_route"""
        executor = PatchExecutor()
        patch = PatchApplication(
            patch_id="test_1",
            event_id=1,
            affected_route="R99_invalid",
            patch_type="prompt",
            patch_payload={"key": "value"},
            status=PatchStatus.PENDING,
        )

        with pytest.raises(ValueError, match="Invalid affected_route"):
            executor._validate_patch(patch)

    def test_validate_patch_invalid_payload(self):
        """测试无效的 patch_payload"""
        executor = PatchExecutor()
        patch = PatchApplication(
            patch_id="test_1",
            event_id=1,
            affected_route="R1_navigator_dict",
            patch_type="prompt",
            patch_payload="invalid_string",  # 应该是 dict
            status=PatchStatus.PENDING,
        )

        with pytest.raises(ValueError, match="patch_payload must be a dictionary"):
            executor._validate_patch(patch)

    def test_validate_patch_success(self):
        """测试有效的补丁验证"""
        executor = PatchExecutor()
        patch = PatchApplication(
            patch_id="test_1",
            event_id=1,
            affected_route="R1_navigator_dict",
            patch_type="prompt",
            patch_payload={"key": "value"},
            status=PatchStatus.PENDING,
        )

        # 不应该抛出异常
        executor._validate_patch(patch)


@pytest.mark.asyncio
class TestPatchApplication:
    """补丁应用测试"""

    async def test_apply_navigator_patch(self):
        """测试 R1 navigator 补丁应用"""
        executor = PatchExecutor()

        # Mock 配置文件操作
        with mock_patch.object(executor, "_load_yaml") as mock_load:
            with mock_patch.object(executor, "_save_yaml") as mock_save:
                with mock_patch.object(executor, "_health_check") as mock_health:
                    with mock_patch.object(executor, "_record_application") as mock_record:
                        mock_load.return_value = {"navigator": {}}

                        patch = PatchApplication(
                            patch_id="test_1",
                            event_id=1,
                            affected_route="R1_navigator_dict",
                            patch_type="prompt",
                            patch_payload={"navigator_dict": {"comparison": "if 对比 in query"}},
                            status=PatchStatus.PENDING,
                        )

                        # 应用补丁
                        result = await executor.apply_patch(patch)

                        assert result.status == PatchStatus.APPLIED
                        assert result.applied_at is not None
                        mock_save.assert_called_once()
                        mock_health.assert_called_once()
                        mock_record.assert_called_once()

    async def test_apply_rerank_weights_patch(self):
        """测试 R4 重排权重补丁"""
        executor = PatchExecutor()

        with mock_patch.object(executor, "_load_yaml") as mock_load:
            with mock_patch.object(executor, "_save_yaml") as mock_save:
                with mock_patch.object(executor, "_health_check") as mock_health:
                    with mock_patch.object(executor, "_record_application") as mock_record:
                        mock_load.return_value = {"reranker": {}}

                        patch = PatchApplication(
                            patch_id="test_2",
                            event_id=2,
                            affected_route="R4_rerank_weights",
                            patch_type="weight",
                            patch_payload={"weights": {"bm25": 0.3, "semantic": 0.7}},
                            status=PatchStatus.PENDING,
                        )

                        result = await executor.apply_patch(patch)

                        assert result.status == PatchStatus.APPLIED
                        mock_save.assert_called_once()

    async def test_apply_patch_health_check_fails(self):
        """测试健康检查失败时补丁应用失败"""
        executor = PatchExecutor()

        with mock_patch.object(executor, "_load_yaml") as mock_load:
            with mock_patch.object(executor, "_save_yaml") as mock_save:
                with mock_patch.object(executor, "_health_check") as mock_health:
                    mock_load.return_value = {"navigator": {}}
                    mock_health.side_effect = Exception("Config syntax error")

                    patch = PatchApplication(
                        patch_id="test_3",
                        event_id=3,
                        affected_route="R1_navigator_dict",
                        patch_type="prompt",
                        patch_payload={"navigator_dict": {"key": "value"}},
                        status=PatchStatus.PENDING,
                    )

                    with pytest.raises(Exception, match="Config syntax error"):
                        await executor.apply_patch(patch)

                    assert patch.status == PatchStatus.FAILED
                    assert patch.error_msg is not None

    async def test_health_check_uses_current_graph_entrypoint(self):
        """Executor health check should use the current graph factory."""
        executor = PatchExecutor()

        with mock_patch("app.agent.graph.get_agent_graph", return_value=MagicMock()) as mock_get_graph:
            await executor._health_check()

        mock_get_graph.assert_called_once()


@pytest.mark.asyncio
class TestPatchVerification:
    """补丁验证测试"""

    async def test_verify_patch_improvement(self):
        """测试补丁验证 - 有改进"""
        executor = PatchExecutor()

        with mock_patch.object(executor, "_run_test_suite") as mock_test:
            with mock_patch.object(executor, "_get_baseline_success_rate") as mock_baseline:
                with mock_patch.object(executor, "_record_verification") as mock_record:
                    # Mock test 结果：成功率从 50% 提升到 75%
                    mock_test.return_value = {
                        "success_rate": 0.75,
                        "total": 16,
                        "passed": 12,
                        "failed": 4,
                    }
                    mock_baseline.return_value = 0.5

                    patch = PatchApplication(
                        patch_id="test_4",
                        event_id=4,
                        affected_route="R4_rerank_weights",
                        patch_type="weight",
                        patch_payload={"weights": {"bm25": 0.3, "semantic": 0.7}},
                        status=PatchStatus.APPLIED,
                        applied_at=1234567890.0,
                    )

                    result = await executor.verify_patch(patch)

                    assert result.status == PatchStatus.VERIFIED
                    assert result.verification_result["success"] is True
                    assert result.verification_result["delta"] == 0.25  # 75% - 50%
                    assert result.verification_result["improvement_pct"] == 50.0  # 25% / 50%
                    mock_record.assert_called_once()

    async def test_verify_patch_no_improvement(self):
        """测试补丁验证 - 无改进，自动还原"""
        executor = PatchExecutor()

        with mock_patch.object(executor, "_run_test_suite") as mock_test:
            with mock_patch.object(executor, "_get_baseline_success_rate") as mock_baseline:
                with mock_patch.object(executor, "revert_patch") as mock_revert:
                    # Mock test 结果：成功率没有改进
                    mock_test.return_value = {
                        "success_rate": 0.48,
                        "total": 16,
                        "passed": 8,
                        "failed": 8,
                    }
                    mock_baseline.return_value = 0.5

                    patch = PatchApplication(
                        patch_id="test_5",
                        event_id=5,
                        affected_route="R2_path_default",
                        patch_type="path",
                        patch_payload={"path": "new_path"},
                        status=PatchStatus.APPLIED,
                        applied_at=1234567890.0,
                        recovery_point="abc123def456",
                    )

                    result = await executor.verify_patch(patch)

                    assert result.status == PatchStatus.REVERTED
                    assert result.verification_result["success"] is False
                    assert result.verification_result["reason"] == "Insufficient improvement"
                    mock_revert.assert_called_once()

    async def test_verify_patch_improvement_marginal(self):
        """测试补丁验证 - 改进不足 2% 阈值，自动还原"""
        executor = PatchExecutor()

        with mock_patch.object(executor, "_run_test_suite") as mock_test:
            with mock_patch.object(executor, "_get_baseline_success_rate") as mock_baseline:
                with mock_patch.object(executor, "revert_patch") as mock_revert:
                    # Mock test 结果：成功率只提升 1%（不足 2% 阈值）
                    mock_test.return_value = {
                        "success_rate": 0.51,
                        "total": 16,
                        "passed": 8,
                        "failed": 8,
                    }
                    mock_baseline.return_value = 0.5

                    patch = PatchApplication(
                        patch_id="test_6",
                        event_id=6,
                        affected_route="R5_tool_priority",
                        patch_type="tool_order",
                        patch_payload={"priority": ["tool_a", "tool_b"]},
                        status=PatchStatus.APPLIED,
                        applied_at=1234567890.0,
                        recovery_point="xyz789",
                    )

                    result = await executor.verify_patch(patch)

                    assert result.status == PatchStatus.REVERTED
                    mock_revert.assert_called_once()


@pytest.mark.asyncio
class TestPatchReversion:
    """补丁还原测试"""

    async def test_revert_patch_success(self):
        """测试补丁还原成功"""
        executor = PatchExecutor()

        with mock_patch.object(executor, "_run_command") as mock_cmd:
            mock_cmd.return_value = "✓ reset"

            patch = PatchApplication(
                patch_id="test_7",
                event_id=7,
                affected_route="R1_navigator_dict",
                patch_type="prompt",
                patch_payload={"navigator_dict": {"key": "value"}},
                status=PatchStatus.APPLIED,
                recovery_point="abc123def456",
                reversible=True,
            )

            await executor.revert_patch(patch)
            mock_cmd.assert_called_once()

    async def test_revert_patch_not_reversible(self):
        """测试不可还原的补丁"""
        executor = PatchExecutor()

        patch = PatchApplication(
            patch_id="test_8",
            event_id=8,
            affected_route="R1_navigator_dict",
            patch_type="prompt",
            patch_payload={"navigator_dict": {"key": "value"}},
            status=PatchStatus.APPLIED,
            reversible=False,
        )

        with pytest.raises(Exception, match="not reversible"):
            await executor.revert_patch(patch)


@pytest.mark.asyncio
class TestTestSuiteExecution:
    """测试脚本执行测试"""

    async def test_run_test_suite_success(self):
        """测试成功运行测试脚本"""
        executor = PatchExecutor()

        # 创建 mock 的测试结果文件
        results_data = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": 16,
                "ok": 16,
                "errors": 0,
                "passed": 12,
                "avg_confidence": 0.85,
                "llm_unconfigured": 0,
            },
            "results": [],
        }

        with mock_patch.object(executor, "_run_command") as mock_cmd:
            with mock_patch("builtins.open", create=True) as mock_open:
                mock_cmd.return_value = "✓ tests passed"

                # Mock 文件读取
                mock_open.return_value.__enter__.return_value.read.return_value = json.dumps(
                    results_data
                )

                with mock_patch("pathlib.Path.exists", return_value=True):
                    with mock_patch(
                        "builtins.open",
                        create=True,
                    ) as mock_file:
                        mock_file.return_value.__enter__.return_value.read = (
                            lambda: json.dumps(results_data)
                        )

                        # 需要使用真实的文件操作来测试解析逻辑
                        # 这里我们直接测试解析函数
                        output = "test output"
                        result = await executor._parse_test_output(output)

                        # 验证解析结果
                        assert "success_rate" in result
                        assert "total" in result
                        assert "passed" in result


@pytest.mark.asyncio
class TestDatabaseOperations:
    """数据库操作测试"""

    async def test_get_baseline_success_rate_from_event(self):
        """测试从已验证事件获取基准"""
        executor = PatchExecutor()

        # Mock 数据库连接
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("0.75",)

        with mock_patch.object(executor, "_get_db_conn", return_value=mock_conn):
            with mock_patch.object(executor, "_put_db_conn"):
                rate = await executor._get_baseline_success_rate()

                assert rate == 0.75
                mock_cursor.execute.assert_called()
                mock_cursor.close.assert_called()

    async def test_get_baseline_success_rate_default(self):
        """测试使用默认基准"""
        executor = PatchExecutor()

        # Mock 数据库连接返回 None
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        with mock_patch.object(executor, "_get_db_conn", return_value=mock_conn):
            with mock_patch.object(executor, "_put_db_conn"):
                rate = await executor._get_baseline_success_rate()

                assert rate == 0.5  # 默认值

    async def test_record_application_writes_improvement_event_to_ledger(self):
        executor = PatchExecutor()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        patch = PatchApplication(
            patch_id="test_apply_event",
            event_id=8,
            affected_route="R1_navigator_dict",
            patch_type="prompt",
            patch_payload={"gap_key": "gap_001", "description": "Apply safer navigator rule"},
            status=PatchStatus.APPLIED,
        )

        with mock_patch.object(executor, "_get_db_conn", return_value=mock_conn), mock_patch.object(
            executor, "_put_db_conn"
        ), mock_patch("app.agent.executor.update_knowledge_gap_status"):
            await executor._record_application(patch)

        sql_calls = [call.args[0] for call in mock_cursor.execute.call_args_list]
        assert any("UPDATE improvement_events" in sql for sql in sql_calls)
        assert any("INSERT INTO event_ledger" in sql for sql in sql_calls)

    async def test_record_verification_moves_gap_to_observing(self):
        """Successful verification should move the gap into observing, not resolved."""
        executor = PatchExecutor()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        patch = PatchApplication(
            patch_id="test_gap_observing",
            event_id=9,
            affected_route="R4_rerank_weights",
            patch_type="weight",
            patch_payload={"gap_key": "gap_001", "description": "Rebalance rerank weights"},
            status=PatchStatus.APPLIED,
            applied_at=1234567890.0,
        )

        with mock_patch.object(executor, "_get_db_conn", return_value=mock_conn), mock_patch.object(
            executor, "_put_db_conn"
        ), mock_patch("app.agent.executor.update_knowledge_gap_status") as mock_update:
            await executor._record_verification(
                patch,
                {"success_rate": 0.75, "passed": 12, "failed": 4},
                0.5,
                0.75,
            )

        assert mock_update.call_args.args[1] == "observing"
        assert (
            mock_update.call_args.kwargs["metadata_patch"]["observation_window_days"] == 7
        )
        sql_calls = [call.args[0] for call in mock_cursor.execute.call_args_list]
        assert any("INSERT INTO event_ledger" in sql for sql in sql_calls)


@pytest.mark.asyncio
class TestPatchRoutes:
    """补丁应用到各路由的测试"""

    async def test_patch_navigator_dict(self):
        """测试 R1 navigator_dict 补丁"""
        executor = PatchExecutor()
        payload = {
            "navigator_dict": {
                "comparison": 'if "对比" in query or "区别" in query'
            }
        }

        with mock_patch.object(executor, "_load_yaml") as mock_load:
            with mock_patch.object(executor, "_save_yaml") as mock_save:
                mock_load.return_value = {"navigator": {}}

                await executor._patch_navigator_dict(payload)

                # 验证配置被更新
                call_args = mock_save.call_args
                saved_config = call_args[0][0]
                assert "navigator" in saved_config
                assert "comparison" in saved_config["navigator"]

    async def test_patch_path_default(self):
        """测试 R2 path_default 补丁"""
        executor = PatchExecutor()
        payload = {"path": "semantic+bm25"}

        with mock_patch.object(executor, "_load_yaml") as mock_load:
            with mock_patch.object(executor, "_save_yaml") as mock_save:
                mock_load.return_value = {"retrieval": {}}

                await executor._patch_path_default(payload)

                call_args = mock_save.call_args
                saved_config = call_args[0][0]
                assert saved_config["retrieval"]["default_path"] == "semantic+bm25"

    async def test_patch_planner_examples(self):
        """测试 R3 planner_examples 补丁"""
        executor = PatchExecutor()
        examples = [{"input": "q1", "output": "a1"}, {"input": "q2", "output": "a2"}]
        payload = {"examples": examples}

        with mock_patch.object(executor, "_load_yaml") as mock_load:
            with mock_patch.object(executor, "_save_yaml") as mock_save:
                mock_load.return_value = {"planner": {}}

                await executor._patch_planner_examples(payload)

                call_args = mock_save.call_args
                saved_config = call_args[0][0]
                assert len(saved_config["planner"]["examples"]) >= len(examples)

    async def test_patch_rerank_weights(self):
        """测试 R4 rerank_weights 补丁"""
        executor = PatchExecutor()
        weights = {"bm25": 0.3, "semantic": 0.5, "graph": 0.2}
        payload = {"weights": weights}

        with mock_patch.object(executor, "_load_yaml") as mock_load:
            with mock_patch.object(executor, "_save_yaml") as mock_save:
                mock_load.return_value = {"reranker": {}}

                await executor._patch_rerank_weights(payload)

                call_args = mock_save.call_args
                saved_config = call_args[0][0]
                assert saved_config["reranker"]["weights"] == weights

    async def test_patch_tool_priority(self):
        """测试 R5 tool_priority 补丁"""
        executor = PatchExecutor()
        priority = ["retriever", "planner", "verifier"]
        payload = {"priority": priority}

        with mock_patch.object(executor, "_load_yaml") as mock_load:
            with mock_patch.object(executor, "_save_yaml") as mock_save:
                mock_load.return_value = {"tools": {}}

                await executor._patch_tool_priority(payload)

                call_args = mock_save.call_args
                saved_config = call_args[0][0]
                assert saved_config["tools"]["priority"] == priority


@pytest.mark.asyncio
async def test_execute_improvement_event_full_flow():
    """集成测试：完整的 improvement_event 执行流程"""
    # Mock 数据库连接和所有操作
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()

    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    # Mock 数据库查询返回值
    mock_cursor.fetchone.return_value = (
        1,
        "R4_rerank_weights",
        {"weights": {"bm25": 0.3, "semantic": 0.7}},
        None,
        None,
        None,
        None,
    )

    with mock_patch("app.agent.executor.PatchExecutor") as MockExecutor:
        mock_executor = MagicMock()
        MockExecutor.return_value = mock_executor

        # Mock 异步方法
        async def mock_apply(*args, **kwargs):
            patch = args[0]
            patch.status = PatchStatus.APPLIED
            patch.applied_at = time.time()
            return patch

        async def mock_verify(*args, **kwargs):
            patch = args[0]
            patch.status = PatchStatus.VERIFIED
            patch.verified_at = time.time()
            patch.verification_result = {
                "before_rate": 0.5,
                "after_rate": 0.75,
                "delta": 0.25,
                "success": True,
            }
            return patch

        mock_executor.apply_patch = mock_apply
        mock_executor.verify_patch = mock_verify
        mock_executor._get_db_conn = MagicMock(return_value=mock_conn)
        mock_executor._put_db_conn = MagicMock()

        # 执行测试
        import time
        result = await execute_improvement_event(1, pool=mock_pool)

        assert result["success"] is True
        assert result["status"] == "verified"
        assert "verification_result" in result


@pytest.mark.asyncio
async def test_execute_improvement_event_resumes_verification_without_reapply():
    """已应用未验证的事件应直接恢复验证，不重复应用补丁。"""
    from datetime import datetime, timezone

    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    applied_at = datetime.now(timezone.utc)

    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = (
        1,
        "R4_rerank_weights",
        {"type": "ranking_optimization", "review": {"status": "approved"}},
        applied_at,
        None,
        None,
        None,
    )

    with mock_patch("app.agent.executor.PatchExecutor") as MockExecutor:
        mock_executor = MagicMock()
        MockExecutor.return_value = mock_executor

        async def mock_verify(*args, **kwargs):
            patch = args[0]
            patch.status = PatchStatus.VERIFIED
            patch.verified_at = time.time()
            patch.verification_result = {"after_rate": 0.8}
            return patch

        mock_executor.verify_patch = mock_verify
        mock_executor.apply_patch = AsyncMock(side_effect=AssertionError("apply_patch should not be called"))
        mock_executor._get_db_conn = MagicMock(return_value=mock_conn)
        mock_executor._put_db_conn = MagicMock()

        result = await execute_improvement_event(1, pool=mock_pool)

        assert result["success"] is True
        assert result["status"] == "verified"


@pytest.mark.asyncio
async def test_execute_improvement_event_refuses_unapproved_event():
    """未批准事件不应进入 executor。"""
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()

    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = (
        1,
        "R4_rerank_weights",
        {"type": "ranking_optimization", "review": {"status": "pending_review"}},
        None,
        None,
        None,
        None,
    )

    result = await execute_improvement_event(1, pool=mock_pool)

    assert result["success"] is False
    assert result["status"] == "pending_review"


@pytest.mark.asyncio
async def test_execute_improvement_event_returns_failed_without_retrying_failed_record():
    """Failed verification metadata should short-circuit executor retries."""
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()

    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = (
        1,
        "R4_rerank_weights",
        {"type": "ranking_optimization", "review": {"status": "approved"}},
        None,
        None,
        None,
        {"success": False, "status": "failed", "error": "timeout"},
    )

    with mock_patch.object(PatchExecutor, "apply_patch", new=AsyncMock(side_effect=AssertionError("apply_patch should not run"))), \
         mock_patch.object(PatchExecutor, "verify_patch", new=AsyncMock(side_effect=AssertionError("verify_patch should not run"))):
        result = await execute_improvement_event(1, pool=mock_pool)

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error"] == "timeout"


@pytest.mark.asyncio
async def test_execute_improvement_event_persists_failed_state():
    """Executor failures should be persisted so events do not stay stuck in applied/approved."""
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()

    mock_pool.getconn.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = (
        1,
        "R4_rerank_weights",
        {"type": "ranking_optimization", "review": {"status": "approved"}},
        None,
        None,
        None,
        None,
    )

    async def _mock_apply(self, patch):
        patch.status = PatchStatus.APPLIED
        patch.applied_at = time.time()
        return patch

    async def _mock_verify(self, patch):
        raise Exception("Test suite timeout (>10min)")

    with mock_patch.object(PatchExecutor, "apply_patch", _mock_apply), \
         mock_patch.object(PatchExecutor, "verify_patch", _mock_verify), \
         mock_patch.object(PatchExecutor, "_record_failure", new=AsyncMock()) as mock_record_failure:
        result = await execute_improvement_event(1, pool=mock_pool)

    assert result["success"] is False
    assert result["status"] == "failed"
    mock_record_failure.assert_awaited_once()
