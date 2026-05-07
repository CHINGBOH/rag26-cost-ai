"""
Shared interaction run context for canonical terminal writes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class RunContext:
    run_id: str
    session_id: str
    request_id: str
    trace_id: str
    channel: str
    query: str
    started_at: datetime


def build_run_context(*, query: str, session_id: str | None, channel: str) -> RunContext:
    run_id = str(uuid.uuid4())
    normalized_session_id = session_id or str(uuid.uuid4())
    request_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    return RunContext(
        run_id=run_id,
        session_id=normalized_session_id,
        request_id=request_id,
        trace_id=run_id,
        channel=channel,
        query=query,
        started_at=started_at,
    )
