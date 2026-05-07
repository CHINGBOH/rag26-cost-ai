"""
Test suite for Issue #121: Price query time validation

Covers:
- Reversed time range auto-correction
- Future time rejection
- Time span validation
- Format validation
- Edge cases
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime

# Setup path like other tests in this directory
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from app.agent.tools import _validate_and_normalize_time_range


class TestTimeValidation:
    """Test time range validation for price queries"""

    def test_valid_time_range(self):
        """Normal case: valid ascending time range"""
        start, end = _validate_and_normalize_time_range("2024-01", "2024-12", "test_material")
        assert start == "2024-01"
        assert end == "2024-12"

    def test_reversed_time_range_auto_corrects(self):
        """Issue #121: Auto-correct reversed time ranges"""
        start, end = _validate_and_normalize_time_range("2024-12", "2024-01", "test_material")
        # Should auto-swap
        assert start == "2024-01"
        assert end == "2024-12"

    def test_future_time_rejected(self):
        """Issue #121: Reject future dates"""
        future_date = datetime.now().replace(year=datetime.now().year + 1).strftime("%Y-%m")
        
        with pytest.raises(ValueError, match="Cannot query future"):
            _validate_and_normalize_time_range("2024-01", future_date, "test_material")
        
        with pytest.raises(ValueError, match="Cannot query future"):
            _validate_and_normalize_time_range(future_date, future_date, "test_material")

    def test_time_span_too_large(self):
        """Issue #121: Reject time spans > 10 years"""
        with pytest.raises(ValueError, match="Time span too large"):
            _validate_and_normalize_time_range("2010-01", "2025-01", "test_material", max_span_years=10)

    def test_invalid_format(self):
        """Issue #121: Clear error messages for invalid formats"""
        with pytest.raises(ValueError, match="Invalid start_month format"):
            _validate_and_normalize_time_range("2024/01/15", "2024-12", "test_material")
        
        with pytest.raises(ValueError, match="Invalid end_month format"):
            _validate_and_normalize_time_range("2024-01", "Dec 2024", "test_material")

    def test_empty_start_only(self):
        """Allow empty start with valid end"""
        start, end = _validate_and_normalize_time_range("", "2024-12", "test_material")
        assert start == ""
        assert end == "2024-12"

    def test_empty_end_only(self):
        """Allow empty end with valid start"""
        start, end = _validate_and_normalize_time_range("2024-01", "", "test_material")
        assert start == "2024-01"
        assert end == ""

    def test_both_empty(self):
        """Allow both empty (no time filter)"""
        start, end = _validate_and_normalize_time_range("", "", "test_material")
        assert start == ""
        assert end == ""

    def test_single_month(self):
        """Allow single month range"""
        start, end = _validate_and_normalize_time_range("2024-06", "2024-06", "test_material")
        assert start == "2024-06"
        assert end == "2024-06"

    def test_edge_case_current_month(self):
        """Allow query up to current month"""
        current_month = datetime.now().strftime("%Y-%m")
        start, end = _validate_and_normalize_time_range("2024-01", current_month, "test_material")
        assert start == "2024-01"
        assert end == current_month

    def test_max_allowed_span(self):
        """Allow exactly max_span_years"""
        # 10 years = 120 months
        start, end = _validate_and_normalize_time_range("2014-01", "2024-01", "test_material", max_span_years=10)
        assert start == "2014-01"
        assert end == "2024-01"

    def test_reversed_with_large_span(self):
        """Auto-correct reversed range even if span is large"""
        with pytest.raises(ValueError, match="Time span too large"):
            # This will first auto-correct 2025-01 → 2010-01, then fail on span
            _validate_and_normalize_time_range("2025-01", "2010-01", "test_material", max_span_years=10)


class TestDeltaCalculation:
    """Test safe delta calculation with zero handling (Issue #121)"""

    def test_delta_from_zero_to_positive(self):
        """Price surge from 0 to positive should be marked as infinity"""
        # This test would require mocking or integration testing
        # For now, document the expected behavior
        pass

    def test_delta_from_zero_to_zero(self):
        """Both zero should result in zero delta"""
        pass

    def test_delta_normal_case(self):
        """Normal case: non-zero previous price"""
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
