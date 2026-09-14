from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WorkOrder(Base):
    """Issued to a winning supplier for a specific requisition.
    
    A requisition can have multiple WorkOrders (one per winning supplier
    when items are split across multiple suppliers).
    """
    __tablename__ = "work_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    requisition_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("requisitions.id", ondelete="CASCADE")
    )
    vendor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("vendors.id")
    )
    requisition_vendor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("requisition_vendors.id")
    )
    issued_by: Mapped[str] = mapped_column(String(36), ForeignKey("user_profiles.id"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    pdf_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="issued")  # issued, receiving, closed
    letterhead_slot: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Delivery timer — starts when WO issued, stops when invoice finalized
    delivery_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    requisition = relationship("Requisition", lazy="selectin")
    vendor = relationship("Vendor", lazy="selectin")
    issuer = relationship("UserProfile", lazy="selectin")
    ratings = relationship("SupplierRating", back_populates="work_order", lazy="selectin")


class SupplierRating(Base):
    """Performance rating recorded for a supplier after invoice finalization.
    
    Tracks delivery speed and defect rates for future assessment.
    """
    __tablename__ = "supplier_ratings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    vendor_id: Mapped[str] = mapped_column(String(36), ForeignKey("vendors.id"))
    requisition_id: Mapped[str] = mapped_column(String(36), ForeignKey("requisitions.id"))
    work_order_id: Mapped[str] = mapped_column(String(36), ForeignKey("work_orders.id"))
    rated_by: Mapped[str] = mapped_column(String(36), ForeignKey("user_profiles.id"))
    rated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Delivery performance
    delivery_days: Mapped[float | None] = mapped_column(Numeric, nullable=True)

    # Quality performance
    ordered_qty: Mapped[float] = mapped_column(Numeric)
    received_qty: Mapped[float] = mapped_column(Numeric)
    rejected_qty: Mapped[float] = mapped_column(Numeric, default=0)
    defect_rate_pct: Mapped[float] = mapped_column(Numeric, default=0)  # rejected/ordered * 100

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    vendor = relationship("Vendor", lazy="selectin")
    work_order = relationship("WorkOrder", back_populates="ratings", lazy="selectin")
    rater = relationship("UserProfile", lazy="selectin")
