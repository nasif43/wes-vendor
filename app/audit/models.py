from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AuditLog(Base):
    """Centralized activity log recording who did what and when."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    # Who performed the action
    actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True
    )
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)  # snapshot of full_name at time of action
    actor_email: Mapped[str] = mapped_column(String(255), nullable=False)  # snapshot of email
    actor_role: Mapped[str] = mapped_column(String(50), nullable=False)  # snapshot of role
    # What happened
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    # Which entity was affected
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # e.g. "requisition", "decision"
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    entity_label: Mapped[str | None] = mapped_column(String(255), nullable=True)  # human-readable name/title
    # Extra notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # When
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    actor = relationship("UserProfile", foreign_keys=[actor_id], lazy="selectin")
