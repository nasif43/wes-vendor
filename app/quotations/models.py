from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Quotation(Base):
    __tablename__ = "quotations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    requisition_vendor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("requisition_vendors.id", ondelete="CASCADE"), unique=True
    )
    submission_type: Mapped[str] = mapped_column(String(10), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    form_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    requisition_vendor = relationship(
        "RequisitionVendor", back_populates="quotation", lazy="selectin"
    )
