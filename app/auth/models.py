import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserRole(enum.StrEnum):
    REQUESTER = "requester"
    PURCHASE_PERSON = "purchase_person"
    MANAGEMENT = "management"
    QC_RECEIVER = "qc_receiver"
    ADMIN = "admin"


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=lambda x: [e.value for e in x]),
        nullable=False, default=UserRole.REQUESTER
    )

    can_view_quotations: Mapped[bool] = mapped_column(Boolean, default=False)
    can_do_qc: Mapped[bool] = mapped_column(Boolean, default=False)
    is_management: Mapped[bool] = mapped_column(Boolean, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def can_see_quotes(self) -> bool:
        role_str = str(self.role.value) if hasattr(self.role, "value") else str(self.role or "")
        return bool(self.can_view_quotations or self.is_management or role_str in ("management", "admin", "purchase_person"))

    @property
    def can_perform_qc(self) -> bool:
        role_str = str(self.role.value) if hasattr(self.role, "value") else str(self.role or "")
        return bool(self.can_do_qc or self.is_management or role_str in ("qc_receiver", "management", "admin"))

    @property
    def has_management_authority(self) -> bool:
        role_str = str(self.role.value) if hasattr(self.role, "value") else str(self.role or "")
        return bool(self.is_management or role_str in ("management", "admin"))
