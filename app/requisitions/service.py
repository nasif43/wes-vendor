import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.models import UserProfile
from app.requisitions.models import Requisition, RequisitionStatus, RequisitionVendor

logger = logging.getLogger(__name__)


class InvalidStateTransitionError(Exception):
    """Raised when an illegal status transition is attempted."""
    pass


# Legal state transition graph
# Key: current status, Value: set of allowed next statuses
ALLOWED_TRANSITIONS: dict[RequisitionStatus, set[RequisitionStatus]] = {
    RequisitionStatus.DRAFT: {
        RequisitionStatus.DRAFT,
        RequisitionStatus.NEW,
        RequisitionStatus.IN_PROGRESS,
    },
    RequisitionStatus.NEW: {
        RequisitionStatus.NEW,
        RequisitionStatus.IN_PROGRESS,
        RequisitionStatus.SUBMITTED,
    },
    RequisitionStatus.IN_PROGRESS: {
        RequisitionStatus.IN_PROGRESS,
        RequisitionStatus.SUBMITTED,
    },
    RequisitionStatus.SUBMITTED: {
        RequisitionStatus.SUBMITTED,
        RequisitionStatus.IN_PROGRESS,  # e.g., management rejection returns order for re-decision
        RequisitionStatus.RECEIVED,
        RequisitionStatus.CLOSED,
    },
    RequisitionStatus.RECEIVED: {
        RequisitionStatus.RECEIVED,
        RequisitionStatus.CLOSED,
    },
    RequisitionStatus.CLOSED: {
        RequisitionStatus.CLOSED,  # Terminal state
    },
}


async def transition_requisition_status(
    db: AsyncSession,
    *,
    requisition: Requisition,
    target_status: RequisitionStatus,
    actor: UserProfile | None,
    action_name: str,
    notes: str | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> Requisition:
    """
    Authoritative state machine transition for requisitions.
    - Validates legal transitions according to the lifecycle graph
    - Applies state mutation
    - Records an audit log entry automatically
    - Dispatches required side-effect notifications
    """
    current_status = requisition.status
    if isinstance(current_status, str):
        current_status = RequisitionStatus(current_status)

    allowed = ALLOWED_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        error_msg = f"Cannot transition requisition from '{current_status.value}' to '{target_status.value}'"
        logger.error(error_msg)
        raise InvalidStateTransitionError(error_msg)

    previous_status_val = current_status.value
    requisition.status = target_status
    requisition.updated_at = datetime.now(UTC)

    # ── Audit Log ──────────────────────────────────────────────────────────────
    if actor:
        audit_notes = f"Status changed from {previous_status_val} -> {target_status.value}."
        if notes:
            audit_notes += f" {notes}"
        await log_action(
            db,
            actor=actor,
            action=action_name,
            entity_type="requisition",
            entity_id=requisition.id,
            entity_label=requisition.title,
            notes=audit_notes,
        )

    await db.flush()
    return requisition
