from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    requisition_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("requisitions.id", ondelete="CASCADE")
    )
    winning_vendor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("vendors.id")
    )
    decided_by: Mapped[str] = mapped_column(String(36), ForeignKey("user_profiles.id"))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    management_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user_profiles.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    requisition = relationship("Requisition", lazy="selectin")
    winning_vendor = relationship("Vendor", foreign_keys=[winning_vendor_id], lazy="selectin")
    decider = relationship("UserProfile", foreign_keys=[decided_by], lazy="selectin")
    approver = relationship("UserProfile", foreign_keys=[approved_by], lazy="selectin")

