"""
Audit service — thin helper to write AuditLog entries without repeating boilerplate.

Usage:
    from app.audit.service import log_action
    await log_action(db, actor=user, action="DECISION_APPROVED", entity_type="decision",
                     entity_id=decision.id, entity_label=decision.requisition.title)
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.auth.models import UserProfile


async def log_action(
    db: AsyncSession,
    *,
    actor: UserProfile,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    entity_label: str | None = None,
    notes: str | None = None,
) -> AuditLog:
    """Write a single audit log entry and flush it (does NOT commit — let the caller's session commit)."""
    entry = AuditLog(
        actor_id=actor.id,
        actor_name=actor.full_name,
        actor_email=actor.email,
        actor_role=str(actor.role),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        notes=notes,
    )
    db.add(entry)
    await db.flush()
    return entry
