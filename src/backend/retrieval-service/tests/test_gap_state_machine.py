"""
Test suite for Issue #120: Knowledge Gap State Machine

Covers:
- Valid forward transitions
- Valid backward transitions
- Invalid transition rejection
- Transition reason auto-fill
- Backward transition detection
- Loop detection
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime

# Setup path like other tests
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from app.agent.gaps.state_machine import (
    KnowledgeGapStateMachine,
    GapStatus,
    get_state_machine,
)


class TestStateTransitions:
    """Test valid and invalid state transitions"""
    
    def test_forward_transition_open_to_in_progress(self):
        """Forward: open → in_progress"""
        sm = KnowledgeGapStateMachine()
        assert sm.is_valid_transition(GapStatus.OPEN, GapStatus.IN_PROGRESS)
        
        record = sm.transition(
            gap_key="test_gap_1",
            from_status=GapStatus.OPEN,
            to_status=GapStatus.IN_PROGRESS,
            actor="test_user"
        )
        
        assert record["from_status"] == GapStatus.OPEN
        assert record["to_status"] == GapStatus.IN_PROGRESS
        assert record["is_backward"] is False
        assert "Starting repair" in record["reason"]
    
    def test_backward_transition_in_progress_to_open(self):
        """Backward: in_progress → open (approach failed)"""
        sm = KnowledgeGapStateMachine()
        assert sm.is_valid_transition(GapStatus.IN_PROGRESS, GapStatus.OPEN)
        
        record = sm.transition(
            gap_key="test_gap_1",
            from_status=GapStatus.IN_PROGRESS,
            to_status=GapStatus.OPEN,
            actor="test_user"
        )
        
        assert record["is_backward"] is True
        assert "not working" in record["reason"].lower()
    
    def test_backward_transition_observing_to_in_progress(self):
        """Backward: observing → in_progress (regression)"""
        sm = KnowledgeGapStateMachine()
        assert sm.is_valid_transition(GapStatus.OBSERVING, GapStatus.IN_PROGRESS)
        
        record = sm.transition(
            gap_key="test_gap_1",
            from_status=GapStatus.OBSERVING,
            to_status=GapStatus.IN_PROGRESS,
            actor="test_user"
        )
        
        assert record["is_backward"] is True
        assert "regression" in record["reason"].lower()
    
    def test_backward_transition_resolved_to_open(self):
        """Backward: resolved → open (severe regression)"""
        sm = KnowledgeGapStateMachine()
        assert sm.is_valid_transition(GapStatus.RESOLVED, GapStatus.OPEN)
        
        record = sm.transition(
            gap_key="test_gap_1",
            from_status=GapStatus.RESOLVED,
            to_status=GapStatus.OPEN,
            actor="test_user"
        )
        
        assert record["is_backward"] is True
        assert "reopened" in record["reason"].lower()
    
    def test_invalid_transition_rejected(self):
        """Invalid transitions should raise ValueError"""
        sm = KnowledgeGapStateMachine()
        
        # open cannot go directly to resolved
        assert not sm.is_valid_transition(GapStatus.OPEN, GapStatus.RESOLVED)
        
        with pytest.raises(ValueError, match="Invalid transition"):
            sm.transition(
                gap_key="test_gap_1",
                from_status=GapStatus.OPEN,
                to_status=GapStatus.RESOLVED,
                actor="test_user"
            )
    
    def test_blocked_can_reopen(self):
        """Blocked gaps can be reopened when policy changes"""
        sm = KnowledgeGapStateMachine()
        assert sm.is_valid_transition(GapStatus.BLOCKED, GapStatus.OPEN)
        
        record = sm.transition(
            gap_key="test_gap_1",
            from_status=GapStatus.BLOCKED,
            to_status=GapStatus.OPEN,
            actor="test_user"
        )
        
        assert "policy changed" in record["reason"].lower()
    
    def test_get_allowed_transitions(self):
        """Get all allowed transitions from a status"""
        sm = KnowledgeGapStateMachine()
        
        # Open can go to in_progress or blocked
        allowed = sm.get_allowed_transitions(GapStatus.OPEN)
        assert set(allowed) == {GapStatus.IN_PROGRESS, GapStatus.BLOCKED}
        
        # Observing has multiple options including backward
        allowed = sm.get_allowed_transitions(GapStatus.OBSERVING)
        assert GapStatus.RESOLVED in allowed  # forward
        assert GapStatus.IN_PROGRESS in allowed  # backward
        assert GapStatus.OPEN in allowed  # backward


class TestCustomReasons:
    """Test custom transition reasons"""
    
    def test_custom_reason_overrides_default(self):
        """Custom reason should override auto-filled reason"""
        sm = KnowledgeGapStateMachine()
        
        custom_reason = "Manual reopen requested by product team"
        record = sm.transition(
            gap_key="test_gap_1",
            from_status=GapStatus.RESOLVED,
            to_status=GapStatus.OPEN,
            actor="test_user",
            reason=custom_reason
        )
        
        assert record["reason"] == custom_reason
    
    def test_auto_filled_reason(self):
        """Reason should be auto-filled from TRANSITION_REASONS"""
        sm = KnowledgeGapStateMachine()
        
        record = sm.transition(
            gap_key="test_gap_1",
            from_status=GapStatus.OBSERVING,
            to_status=GapStatus.RESOLVED,
            actor="test_user"
        )
        
        assert "observation period passed" in record["reason"].lower()


class TestBackwardDetection:
    """Test backward transition detection"""
    
    def test_all_backward_transitions(self):
        """All backward transitions should be detected"""
        sm = KnowledgeGapStateMachine()
        
        backward_pairs = [
            (GapStatus.IN_PROGRESS, GapStatus.OPEN),
            (GapStatus.OBSERVING, GapStatus.IN_PROGRESS),
            (GapStatus.OBSERVING, GapStatus.OPEN),
            (GapStatus.RESOLVED, GapStatus.OBSERVING),
            (GapStatus.RESOLVED, GapStatus.OPEN),
        ]
        
        for from_st, to_st in backward_pairs:
            assert sm._is_backward_transition(from_st, to_st), \
                f"{from_st} → {to_st} should be marked as backward"
    
    def test_forward_not_marked_backward(self):
        """Forward transitions should not be marked as backward"""
        sm = KnowledgeGapStateMachine()
        
        forward_pairs = [
            (GapStatus.OPEN, GapStatus.IN_PROGRESS),
            (GapStatus.IN_PROGRESS, GapStatus.OBSERVING),
            (GapStatus.OBSERVING, GapStatus.RESOLVED),
        ]
        
        for from_st, to_st in forward_pairs:
            assert not sm._is_backward_transition(from_st, to_st), \
                f"{from_st} → {to_st} should NOT be marked as backward"


class TestTransitionHistory:
    """Test transition history analysis"""
    
    def test_history_summary_empty(self):
        """Empty history should return zeros"""
        sm = KnowledgeGapStateMachine()
        summary = sm.get_transition_history_summary([])
        
        assert summary["total_transitions"] == 0
        assert summary["backward_count"] == 0
        assert summary["forward_count"] == 0
        assert summary["stuck_in_loop"] is False
    
    def test_history_summary_with_backward(self):
        """History with backward transitions"""
        sm = KnowledgeGapStateMachine()
        
        transitions = [
            {"from_status": "open", "to_status": "in_progress", "is_backward": False},
            {"from_status": "in_progress", "to_status": "observing", "is_backward": False},
            {"from_status": "observing", "to_status": "in_progress", "is_backward": True},
            {"from_status": "in_progress", "to_status": "open", "is_backward": True},
        ]
        
        summary = sm.get_transition_history_summary(transitions)
        
        assert summary["total_transitions"] == 4
        assert summary["backward_count"] == 2
        assert summary["forward_count"] == 2
        assert summary["backward_rate"] == 0.5
    
    def test_loop_detection(self):
        """Detect when gap is stuck in a loop"""
        sm = KnowledgeGapStateMachine()
        
        # Same transition repeated 3+ times = loop
        transitions = [
            {"from_status": "in_progress", "to_status": "observing", "is_backward": False},
            {"from_status": "observing", "to_status": "in_progress", "is_backward": True},
            {"from_status": "in_progress", "to_status": "observing", "is_backward": False},
            {"from_status": "observing", "to_status": "in_progress", "is_backward": True},
            {"from_status": "in_progress", "to_status": "observing", "is_backward": False},
            {"from_status": "observing", "to_status": "in_progress", "is_backward": True},
        ]
        
        summary = sm.get_transition_history_summary(transitions)
        
        assert summary["stuck_in_loop"] is True
        assert summary["most_common_transition"] is not None


class TestSingletonAccess:
    """Test singleton state machine access"""
    
    def test_get_state_machine_returns_singleton(self):
        """get_state_machine() should return the same instance"""
        sm1 = get_state_machine()
        sm2 = get_state_machine()
        
        assert sm1 is sm2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
