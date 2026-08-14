import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text, func, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RequisitionStatus(enum.StrEnum):
    DRAFT = "draft"
    NEW = "new"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    RECEIVED = "received"
    CLOSED = "closed"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            val_lower = value.lower()
            for member in cls:
                if member.value.lower() == val_lower:
                    return member
        return cls.DRAFT


class Requisition(Base):
    __tablename__ = "requisitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    item_description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RequisitionStatus] = mapped_column(
        Enum(RequisitionStatus), default=RequisitionStatus.DRAFT
    )
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("user_profiles.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    
    # Delivery & QC Fields
    delivery_image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    qc_done: Mapped[bool] = mapped_column(Boolean, default=False)
    qc_done_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user_profiles.id"), nullable=True)
    qc_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Invoice & Payment Fields
    invoice_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_status: Mapped[str] = mapped_column(String(50), default="pending")

    vendor_links = relationship("RequisitionVendor", back_populates="requisition", lazy="selectin")
    creator = relationship("UserProfile", foreign_keys=[created_by], lazy="selectin")
    qc_receiver = relationship("UserProfile", foreign_keys=[qc_done_by], lazy="selectin")


class RequisitionVendor(Base):
    __tablename__ = "requisition_vendors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    requisition_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("requisitions.id", ondelete="CASCADE")
    )
    vendor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("vendors.id", ondelete="CASCADE")
    )
    unique_link_token: Mapped[str] = mapped_column(
        String(36), unique=True, default=lambda: str(uuid4())
    )
    link_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    requisition = relationship("Requisition", back_populates="vendor_links", lazy="selectin")
    vendor = relationship("Vendor", lazy="selectin")
    quotation = relationship(
        "Quotation", back_populates="requisition_vendor", uselist=False, lazy="selectin"
    )
