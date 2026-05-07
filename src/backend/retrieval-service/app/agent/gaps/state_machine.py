"""
Issue #120: Knowledge Gap State Machine with bidirectional transitions

This module implements a proper state machine that allows backward transitions
when gap fixes fail or need to be reconsidered.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class GapStatus:
    """Valid gap status values"""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    OBSERVING = "observing"
    RESOLVED = "resolved"
    BLOCKED = "blocked"
    
    ALL = {OPEN, IN_PROGRESS, OBSERVING, RESOLVED, BLOCKED}


class KnowledgeGapStateMachine:
    """
    State machine for knowledge gap lifecycle with bidirectional transitions.
    
    Fixes Issue #120: Allows backward transitions when fixes fail or need reconsideration.
    
    State Transitions:
    - open → in_progress (start repair)
    - open ← in_progress (repair approach failed, need rethink)
    - in_progress → observing (fix applied, enter observation)
    - in_progress ← observing (regression detected during observation)
    - observing → resolved (validation passed)
    - observing ← resolved (resolved gap reopened due to regression)
    - * → blocked (policy boundary, out of scope)
    - blocked → open (policy changed, now answerable)
    - * → open (manual reopen)
    """
    
    # Define valid transitions: from_status → list of allowed to_status
    TRANSITIONS: dict[str, list[str]] = {
        GapStatus.OPEN: [
            GapStatus.IN_PROGRESS,  # Start repair
            GapStatus.BLOCKED,       # Mark as policy boundary
        ],
        GapStatus.IN_PROGRESS: [
            GapStatus.OBSERVING,     # Fix applied, enter observation
            GapStatus.OPEN,          # ← Backward: approach failed, need rethink
            GapStatus.BLOCKED,       # Mark as policy boundary
        ],
        GapStatus.OBSERVING: [
            GapStatus.RESOLVED,      # Validation passed
            GapStatus.IN_PROGRESS,   # ← Backward: regression detected
            GapStatus.OPEN,          # ← Backward: severe regression, restart
        ],
        GapStatus.BLOCKED: [
            GapStatus.OPEN,          # Policy changed, now answerable
        ],
        GapStatus.RESOLVED: [
            GapStatus.OPEN,          # ← Backward: gap reopened (severe regression)
            GapStatus.OBSERVING,     # ← Backward: minor regression, re-observe
        ],
    }
    
    # Transition reasons for audit trail
    TRANSITION_REASONS: dict[tuple[str, str], str] = {
        (GapStatus.OPEN, GapStatus.IN_PROGRESS): "Starting repair work",
        (GapStatus.OPEN, GapStatus.BLOCKED): "Policy boundary detected",
        
        (GapStatus.IN_PROGRESS, GapStatus.OBSERVING): "Fix applied, entering observation period",
        (GapStatus.IN_PROGRESS, GapStatus.OPEN): "Current approach not working, need to rethink strategy",
        (GapStatus.IN_PROGRESS, GapStatus.BLOCKED): "Identified as policy boundary during repair",
        
        (GapStatus.OBSERVING, GapStatus.RESOLVED): "Observation period passed, fix validated",
        (GapStatus.OBSERVING, GapStatus.IN_PROGRESS): "Regression detected during observation",
        (GapStatus.OBSERVING, GapStatus.OPEN): "Severe regression, restart from scratch",
        
        (GapStatus.BLOCKED, GapStatus.OPEN): "Policy changed, gap is now answerable",
        
        (GapStatus.RESOLVED, GapStatus.OPEN): "Severe regression, gap reopened",
        (GapStatus.RESOLVED, GapStatus.OBSERVING): "Minor regression detected, re-enter observation",
    }
    
    def __init__(self):
        """Initialize state machine"""
        pass
    
    def is_valid_transition(self, from_status: str, to_status: str) -> bool:
        """
        Check if transition is allowed.
        
        Args:
            from_status: Current status
            to_status: Target status
            
        Returns:
            True if transition is valid
        """
        from_status = self._normalize_status(from_status)
        to_status = self._normalize_status(to_status)
        
        if from_status not in self.TRANSITIONS:
            return False
        
        return to_status in self.TRANSITIONS[from_status]
    
    def get_allowed_transitions(self, from_status: str) -> list[str]:
        """
        Get list of allowed target statuses from current status.
        
        Args:
            from_status: Current status
            
        Returns:
            List of valid target statuses
        """
        from_status = self._normalize_status(from_status)
        return self.TRANSITIONS.get(from_status, [])
    
    def transition(
        self,
        *,
        gap_key: str,
        from_status: str,
        to_status: str,
        actor: str,
        reason: Optional[str] = None,
        evidence_id: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Execute a state transition with validation and audit logging.
        
        Args:
            gap_key: Gap identifier
            from_status: Current status
            to_status: Target status
            actor: Who triggered the transition
            reason: Human-readable reason (optional, auto-filled from TRANSITION_REASONS)
            evidence_id: Related evidence record
            metadata: Additional transition metadata
            
        Returns:
            Transition record dict
            
        Raises:
            ValueError: If transition is invalid
        """
        from_status = self._normalize_status(from_status)
        to_status = self._normalize_status(to_status)
        
        # Validate transition
        if not self.is_valid_transition(from_status, to_status):
            allowed = self.get_allowed_transitions(from_status)
            raise ValueError(
                f"Invalid transition: {from_status} → {to_status}. "
                f"Allowed transitions from '{from_status}': {allowed}"
            )
        
        # Auto-fill reason if not provided
        if not reason:
            reason = self.TRANSITION_REASONS.get(
                (from_status, to_status),
                f"Status changed from {from_status} to {to_status}"
            )
        
        # Determine if this is a backward transition
        is_backward = self._is_backward_transition(from_status, to_status)
        
        transition_record = {
            "gap_key": gap_key,
            "from_status": from_status,
            "to_status": to_status,
            "action": f"transition_{to_status}",
            "actor": actor,
            "reason": reason,
            "evidence_id": evidence_id,
            "metadata": metadata or {},
            "occurred_at": datetime.now().isoformat(),
            "is_backward": is_backward,
        }
        
        logger.info(
            f"[gap_state_machine] Transition: {from_status} → {to_status} "
            f"(gap={gap_key}, actor={actor}, backward={is_backward})"
        )
        
        # Persist to database (caller must handle)
        return transition_record
    
    def _normalize_status(self, status: str) -> str:
        """Normalize status string"""
        normalized = str(status or "open").lower().strip()
        if normalized not in GapStatus.ALL:
            raise ValueError(f"Unknown gap status: '{status}'. Valid values: {GapStatus.ALL}")
        return normalized
    
    def _is_backward_transition(self, from_status: str, to_status: str) -> bool:
        """
        Determine if this is a backward (regressive) transition.
        
        Backward transitions indicate failure or regression:
        - observing → in_progress
        - in_progress → open
        - resolved → observing
        - resolved → open
        """
        backward_pairs = {
            (GapStatus.IN_PROGRESS, GapStatus.OPEN),
            (GapStatus.OBSERVING, GapStatus.IN_PROGRESS),
            (GapStatus.OBSERVING, GapStatus.OPEN),
            (GapStatus.RESOLVED, GapStatus.OBSERVING),
            (GapStatus.RESOLVED, GapStatus.OPEN),
        }
        return (from_status, to_status) in backward_pairs
    
    def get_transition_history_summary(self, transitions: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Analyze transition history to detect patterns.
        
        Args:
            transitions: List of transition records (sorted by occurred_at desc)
            
        Returns:
            Summary dict with metrics
        """
        if not transitions:
            return {
                "total_transitions": 0,
                "backward_count": 0,
                "forward_count": 0,
                "stuck_in_loop": False,
            }
        
        backward_count = sum(1 for t in transitions if t.get("is_backward"))
        forward_count = len(transitions) - backward_count
        
        # Detect loops: same from→to transition repeated 3+ times
        transition_pairs = [(t.get("from_status"), t.get("to_status")) for t in transitions]
        from collections import Counter
        pair_counts = Counter(transition_pairs)
        max_repeat = max(pair_counts.values()) if pair_counts else 0
        stuck_in_loop = max_repeat >= 3
        
        return {
            "total_transitions": len(transitions),
            "backward_count": backward_count,
            "forward_count": forward_count,
            "backward_rate": backward_count / len(transitions) if transitions else 0,
            "stuck_in_loop": stuck_in_loop,
            "most_common_transition": pair_counts.most_common(1)[0] if pair_counts else None,
        }


# Singleton instance
_state_machine = KnowledgeGapStateMachine()


def get_state_machine() -> KnowledgeGapStateMachine:
    """Get singleton state machine instance"""
    return _state_machine
