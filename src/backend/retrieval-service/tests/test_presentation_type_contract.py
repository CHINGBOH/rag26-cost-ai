"""
Issue #119: Test presentation type contract compliance.

Tests that backend respects frontend contract:
- price_comparison: points.length >= 2, delta != null
- price_trend: points.length >= 2, delta != null
- price_snapshot: points.length >= 1 (any)

Also tests _validate_presentation_contract enforces downgrade.
"""

import pytest
from app.agent.presentation_payloads import _build_presentation_payload, _validate_presentation_contract


class TestPresentationTypeContract:
    """Test that presentation types match frontend expectations."""

    def test_single_point_forces_snapshot_not_comparison(self):
        """When only 1 point, must return price_snapshot, never price_comparison."""
        chunks = [
            {
                "content": "电力电缆 0.6/1KV YJV 5×120 单位:m 价格:605.73元 期间:2025-12 类别:电缆",
                "doc_filename": "深圳市2025年12月工程建设信息价.pdf",
                "page_number": 36,
                "metadata": {"unit": "m"},
            },
        ]

        # Even if query_type suggests comparison, 1 point must → snapshot
        presentation = _build_presentation_payload(
            "电力电缆规格型号为0.6/1KV YJV 5×120的价格",
            "comparison",  # User asked for comparison but data only has 1 point
            chunks,
        )

        assert presentation is not None
        assert presentation["type"] == "price_snapshot", "Single point must be snapshot"
        assert len(presentation["points"]) == 1
        assert "delta" not in presentation, "Snapshot should not have delta"

    def test_single_point_forces_snapshot_not_trend(self):
        """When only 1 point, must return price_snapshot, never price_trend."""
        chunks = [
            {
                "content": "中砂 价格走势 期间:2025-12 均价:192.00元/m³",
                "metadata": {"year_month": "2025-12", "avg_price": 192.0, "unit": "m³"},
            },
        ]

        presentation = _build_presentation_payload(
            "中砂2025年12月价格走势",
            "trend_chart",  # User asked for trend but data only has 1 point
            chunks,
        )

        assert presentation is not None
        assert presentation["type"] == "price_snapshot", "Single point must be snapshot"
        assert len(presentation["points"]) == 1
        assert "delta" not in presentation

    def test_two_points_allows_comparison(self):
        """2+ points with query_type=comparison → price_comparison."""
        chunks = [
            {
                "content": "电缆 价格:488.98元 期间:2023-12",
                "doc_filename": "深圳市2023年12月工程建设信息价.pdf",
                "page_number": 27,
                "metadata": {"unit": "m"},
            },
            {
                "content": "电缆 价格:605.73元 期间:2025-12",
                "doc_filename": "深圳市2025年12月工程建设信息价.pdf",
                "page_number": 36,
                "metadata": {"unit": "m"},
            },
        ]

        presentation = _build_presentation_payload(
            "对比2023和2025电缆价格",
            "comparison",
            chunks,
        )

        assert presentation is not None
        assert presentation["type"] == "price_comparison"
        assert len(presentation["points"]) == 2
        assert presentation["delta"] is not None
        assert presentation["delta_percent"] is not None

    def test_two_points_allows_trend(self):
        """2+ points with query_type=trend_chart → price_trend."""
        chunks = [
            {
                "content": "中砂 期间:2025-10 均价:180.00元/m³",
                "metadata": {"year_month": "2025-10", "avg_price": 180.0, "unit": "m³"},
            },
            {
                "content": "中砂 期间:2025-11 均价:185.00元/m³",
                "metadata": {"year_month": "2025-11", "avg_price": 185.0, "unit": "m³"},
            },
        ]

        presentation = _build_presentation_payload(
            "中砂10-11月价格走势",
            "trend_chart",
            chunks,
        )

        assert presentation is not None
        assert presentation["type"] == "price_trend"
        assert len(presentation["points"]) == 2
        assert presentation["delta"] is not None
        assert presentation["delta_percent"] is not None

    def test_empty_chunks_returns_none(self):
        """No chunks → no presentation."""
        presentation = _build_presentation_payload("任意查询", "price", [])
        assert presentation is None

    def test_non_price_query_returns_none(self):
        """Non-price query types should not build price presentation."""
        chunks = [
            {
                "content": "某条规则文本",
                "doc_filename": "标准.pdf",
                "page_number": 1,
            },
        ]

        presentation = _build_presentation_payload(
            "查询标准",
            "standard_ref",  # Not a price query
            chunks,
        )

        # _build_presentation_payload only handles price-related queries
        # For other types, it returns None (handled by finalize_presentation_payload)
        assert presentation is None


class TestPresentationContractValidator:
    """Test _validate_presentation_contract enforces invariants."""

    def test_validator_downgrades_invalid_comparison(self):
        """price_comparison with < 2 points → downgraded to snapshot."""
        invalid = {
            "type": "price_comparison",
            "points": [{"label": "2025-12", "value": 100}],
            "delta": 10,
            "delta_percent": 5.0,
        }

        validated = _validate_presentation_contract(invalid)

        assert validated["type"] == "price_snapshot"
        assert validated["delta"] is None
        assert validated["delta_percent"] is None

    def test_validator_downgrades_invalid_trend(self):
        """price_trend with < 2 points → downgraded to snapshot."""
        invalid = {
            "type": "price_trend",
            "points": [{"label": "2025-12", "value": 100}],
            "delta": 10,
            "delta_percent": 5.0,
        }

        validated = _validate_presentation_contract(invalid)

        assert validated["type"] == "price_snapshot"
        assert validated["delta"] is None
        assert validated["delta_percent"] is None

    def test_validator_preserves_valid_comparison(self):
        """Valid price_comparison passes through unchanged."""
        valid = {
            "type": "price_comparison",
            "points": [{"label": "2023-12", "value": 100}, {"label": "2025-12", "value": 120}],
            "delta": 20,
            "delta_percent": 20.0,
        }

        validated = _validate_presentation_contract(valid)

        assert validated["type"] == "price_comparison"
        assert validated["delta"] == 20
        assert validated["delta_percent"] == 20.0

    def test_validator_preserves_valid_trend(self):
        """Valid price_trend passes through unchanged."""
        valid = {
            "type": "price_trend",
            "points": [{"label": "2025-10", "value": 180}, {"label": "2025-11", "value": 185}],
            "delta": 5,
            "delta_percent": 2.78,
        }

        validated = _validate_presentation_contract(valid)

        assert validated["type"] == "price_trend"
        assert validated["delta"] == 5

    def test_validator_preserves_snapshot(self):
        """price_snapshot accepts any point count."""
        for point_count in [0, 1, 5]:
            snapshot = {
                "type": "price_snapshot",
                "points": [{"label": f"P{i}", "value": i * 100} for i in range(point_count)],
            }

            validated = _validate_presentation_contract(snapshot)
            assert validated["type"] == "price_snapshot"

    def test_validator_handles_none(self):
        """None input → None output."""
        assert _validate_presentation_contract(None) is None

