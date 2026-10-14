from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CashPurchase(Base):
    """A cash purchase record logged after an off-portal/in-store transaction.
    
    Includes mandatory physical receipt/cash memo image attachment.
    """
    __tablename__ = "cash_purchases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    reference_number: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="BDT", nullable=False)
    
    # Event dates
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    
    # Mandatory proof of purchase
    receipt_url: Mapped[str] = mapped_column(String(512), nullable=False)
    receipt_number: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    
    # Supplier / Category linkage (optional reuse of existing modules)
    vendor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("vendors.id"), nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("categories.id"), nullable=True)
    
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Audit & User tracking
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("user_profiles.id"), nullable=False, index=True)
    
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user_profiles.id"), nullable=True)

    # Relationships
    creator = relationship("UserProfile", foreign_keys=[created_by], lazy="selectin")
    updater = relationship("UserProfile", foreign_keys=[updated_by], lazy="selectin")
    vendor = relationship("Vendor", foreign_keys=[vendor_id], lazy="selectin")
    category = relationship("Category", foreign_keys=[category_id], lazy="selectin")

    __table_args__ = (
        Index("idx_cash_purchases_date_amount", "purchase_date", "amount"),
    )
