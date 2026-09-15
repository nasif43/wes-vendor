import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text, func, Boolean, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RequisitionStatus(enum.StrEnum):
    DRAFT = "draft"
    NEW = "new"                              # Suppliers invited, awaiting quotes
    IN_PROGRESS = "in_progress"              # Quotes received, under review
    NEGOTIATING = "negotiating"              # v2 revision round active
    AWARDED = "awarded"                      # Winner(s) selected by management
    WORK_ORDER_ISSUED = "work_order_issued"  # Work order PDF sent to winner
    RECEIVING = "receiving"                  # Items in transit / partial receipt
    SUBMITTED = "submitted"                  # Legacy compat — maps to AWARDED
    RECEIVED = "received"                    # Legacy compat — maps to RECEIVING
    CLOSED = "closed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            val_lower = value.lower().replace("-", "_")
            if val_lower in ("sent", "decided", "reviewed"):
                return cls.IN_PROGRESS
            if val_lower == "delivered":
                return cls.RECEIVING
            if val_lower == "submitted":
                return cls.SUBMITTED
            if val_lower == "received":
                return cls.RECEIVED
            for member in cls:
                if member.value.lower() == val_lower or member.name.lower() == val_lower:
                    return member
        return cls.DRAFT


class Requisition(Base):
    __tablename__ = "requisitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    item_description: Mapped[str] = mapped_column(Text, nullable=True)
    quantity: Mapped[float] = mapped_column(Numeric, nullable=True)
    items: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RequisitionStatus] = mapped_column(
        Enum(RequisitionStatus, native_enum=False, length=50), default=RequisitionStatus.DRAFT
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
    received_pieces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    qc_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receiver_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    vendor_links = relationship("RequisitionVendor", back_populates="requisition", lazy="selectin")
    creator = relationship("UserProfile", foreign_keys=[created_by], lazy="selectin")
    qc_receiver = relationship("UserProfile", foreign_keys=[qc_done_by], lazy="selectin")


class RequisitionVendor(Base):
    """Links a Requisition to a Vendor (internally 'vendor', displayed as 'supplier' in UI)."""
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
    # Shortlisting & allocation for multi-vendor split
    is_shortlisted: Mapped[bool] = mapped_column(Boolean, default=False)
    allocated_quantity: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    # Negotiation versioning: 1=initial, 2=negotiated — now properly typed as Integer
    negotiation_version: Mapped[int] = mapped_column(Integer, default=1)

    requisition = relationship("Requisition", back_populates="vendor_links", lazy="selectin")
    vendor = relationship("Vendor", lazy="selectin")
    # Supports multiple quotation versions (v1 + v2)
    quotations = relationship(
        "Quotation", back_populates="requisition_vendor",
        order_by="Quotation.quote_version", lazy="selectin"
    )
    # Shortlisted line items for this vendor link
    shortlisted_items = relationship("ShortlistedItem", back_populates="requisition_vendor", lazy="selectin")

    @property
    def quotation(self):
        """Backward-compat: returns the latest quotation (v2 if exists, else v1)."""
        return self.quotations[-1] if self.quotations else None

    @property
    def v1_quotation(self):
        return next((q for q in self.quotations if q.quote_version == 1), None)

    @property
    def v2_quotation(self):
        return next((q for q in self.quotations if q.quote_version == 2), None)

    @property
    def latest_quotation(self):
        return self.quotations[-1] if self.quotations else None


class ShortlistedItem(Base):
    """Tracks which specific line items management shortlisted a supplier for."""
    __tablename__ = "shortlisted_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    requisition_vendor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("requisition_vendors.id", ondelete="CASCADE")
    )
    item_index: Mapped[int] = mapped_column(Integer)         # Index into requisition.items JSON array
    item_name: Mapped[str] = mapped_column(String(255))      # Denormalized for display
    shortlisted_qty: Mapped[float] = mapped_column(Numeric)  # Qty allocated to this supplier

    requisition_vendor = relationship("RequisitionVendor", back_populates="shortlisted_items")


class ReceivedItem(Base):
    """Per-line-item record of goods received and QC results."""
    __tablename__ = "received_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    requisition_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("requisitions.id", ondelete="CASCADE")
    )
    work_order_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("work_orders.id"), nullable=True
    )
    item_index: Mapped[int] = mapped_column(Integer)
    item_name: Mapped[str] = mapped_column(String(255))
    ordered_qty: Mapped[float] = mapped_column(Numeric)
    received_qty: Mapped[float] = mapped_column(Numeric)
    rejected_qty: Mapped[float] = mapped_column(Numeric, default=0)
    unit_price: Mapped[float] = mapped_column(Numeric, default=0)  # From winning quotation
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
