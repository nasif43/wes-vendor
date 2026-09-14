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
# NAMING CONVENTION:
#   vendor  = ORM/DB/Python internal
#   supplier = UI/Jinja2/HTML user-facing
ALLOWED_TRANSITIONS: dict[RequisitionStatus, set[RequisitionStatus]] = {
    RequisitionStatus.DRAFT: {
        RequisitionStatus.DRAFT,
        RequisitionStatus.NEW,
        RequisitionStatus.IN_PROGRESS,
        RequisitionStatus.CANCELLED,
    },
    RequisitionStatus.NEW: {
        RequisitionStatus.NEW,
        RequisitionStatus.IN_PROGRESS,
        RequisitionStatus.NEGOTIATING,
        RequisitionStatus.SUBMITTED,   # legacy compat
        RequisitionStatus.CANCELLED,
        RequisitionStatus.REJECTED,
    },
    RequisitionStatus.IN_PROGRESS: {
        RequisitionStatus.IN_PROGRESS,
        RequisitionStatus.NEGOTIATING,
        RequisitionStatus.AWARDED,
        RequisitionStatus.SUBMITTED,   # legacy compat — maps to awarded
        RequisitionStatus.CANCELLED,
        RequisitionStatus.REJECTED,
    },
    RequisitionStatus.NEGOTIATING: {
        RequisitionStatus.NEGOTIATING,
        RequisitionStatus.AWARDED,
        RequisitionStatus.IN_PROGRESS,  # management reverts to re-compare
        RequisitionStatus.CANCELLED,
        RequisitionStatus.REJECTED,
    },
    RequisitionStatus.AWARDED: {
        RequisitionStatus.AWARDED,
        RequisitionStatus.WORK_ORDER_ISSUED,
        RequisitionStatus.SUBMITTED,   # legacy compat
        RequisitionStatus.CANCELLED,
    },
    RequisitionStatus.SUBMITTED: {
        # Legacy status — treated as AWARDED for new code, kept for backward compat
        RequisitionStatus.SUBMITTED,
        RequisitionStatus.AWARDED,
        RequisitionStatus.WORK_ORDER_ISSUED,
        RequisitionStatus.IN_PROGRESS,
        RequisitionStatus.RECEIVING,
        RequisitionStatus.RECEIVED,     # legacy compat
        RequisitionStatus.CLOSED,
        RequisitionStatus.CANCELLED,
        RequisitionStatus.REJECTED,
    },
    RequisitionStatus.WORK_ORDER_ISSUED: {
        RequisitionStatus.WORK_ORDER_ISSUED,
        RequisitionStatus.RECEIVING,
        RequisitionStatus.RECEIVED,     # legacy compat
        RequisitionStatus.CLOSED,
        RequisitionStatus.CANCELLED,
    },
    RequisitionStatus.RECEIVING: {
        RequisitionStatus.RECEIVING,
        RequisitionStatus.CLOSED,
        RequisitionStatus.CANCELLED,
    },
    RequisitionStatus.RECEIVED: {
        # Legacy status — kept for backward compat with existing data
        RequisitionStatus.RECEIVED,
        RequisitionStatus.RECEIVING,
        RequisitionStatus.CLOSED,
        RequisitionStatus.CANCELLED,
    },
    RequisitionStatus.CLOSED: {
        RequisitionStatus.CLOSED,  # Terminal state
    },
    RequisitionStatus.CANCELLED: {
        RequisitionStatus.CANCELLED,  # Terminal state
    },
    RequisitionStatus.REJECTED: {
        RequisitionStatus.REJECTED,  # Terminal state
        RequisitionStatus.DRAFT,     # Allow re-opening rejected requisitions
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
        try:
            current_status = RequisitionStatus(current_status)
        except ValueError:
            current_status = RequisitionStatus.DRAFT

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


async def get_winning_vendor_ids(db: AsyncSession, req_id: str) -> list[str]:
    """Returns all vendor_ids that have a WorkOrder issued for this requisition."""
    from app.work_orders.models import WorkOrder
    result = await db.execute(
        select(WorkOrder.vendor_id).where(WorkOrder.requisition_id == req_id)
    )
    return [row[0] for row in result.all()]
