from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Table, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

vendor_categories = Table(
    "vendor_categories",
    Base.metadata,
    Column("vendor_id", String(36), ForeignKey("vendors.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "category_id", String(36),
        ForeignKey("categories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Vendor(Base):
    __tablename__ = "vendors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_person: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_temporary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user_profiles.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    categories = relationship(
        "Category", secondary=vendor_categories, back_populates="vendors", lazy="selectin"
    )
    creator = relationship("UserProfile", foreign_keys=[created_by], lazy="selectin")



# Add back_populates to Category
from app.categories.models import Category

Category.vendors = relationship(
    "Vendor", secondary=vendor_categories, back_populates="categories", lazy="selectin"
)
