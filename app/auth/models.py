import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserRole(enum.StrEnum):
    PROCUREMENT = "procurement"
    QC_RECEIVER = "qc_receiver"
    MANAGEMENT = "management"
    ADMIN = "admin"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            val_lower = value.lower().replace("-", "_")
            if val_lower in ("purchase_person", "purchaser", "purchase", "requester"):
                return cls.PROCUREMENT
            if val_lower in ("receiver", "qc", "receiver_and_qc", "qc_and_receiver"):
                return cls.QC_RECEIVER
            for member in cls:
                if member.value.lower() == val_lower or member.name.lower() == val_lower:
                    return member
        return cls.PROCUREMENT


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        String(50), nullable=False, default=UserRole.PROCUREMENT
    )

    can_view_quotations: Mapped[bool] = mapped_column(Boolean, default=False)
    can_do_qc: Mapped[bool] = mapped_column(Boolean, default=False)
    can_view_all_requisitions: Mapped[bool] = mapped_column(Boolean, default=False)
    is_management: Mapped[bool] = mapped_column(Boolean, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def is_procurement(self) -> bool:
        role_str = str(self.role.value) if hasattr(self.role, "value") else str(self.role or "")
        return bool(role_str in ("procurement", "admin") or self.is_management)


    @property
    def can_create_requisitions(self) -> bool:
        role_str = str(self.role.value) if hasattr(self.role, "value") else str(self.role or "")
        return bool(role_str in ("procurement", "management", "admin") or self.is_management)


    @property
    def can_see_quotes(self) -> bool:
        role_str = str(self.role.value) if hasattr(self.role, "value") else str(self.role or "")
        # Procurement by default cannot see quotation details/pricing unless explicitly granted can_view_quotations by management
        return bool(self.can_view_quotations or self.is_management or role_str in ("management", "admin"))


    @property
    def can_perform_qc(self) -> bool:
        role_str = str(self.role.value) if hasattr(self.role, "value") else str(self.role or "")
        return bool(self.can_do_qc or self.is_management or role_str in ("qc_receiver", "management", "admin"))

    @property
    def has_management_authority(self) -> bool:
        role_str = str(self.role.value) if hasattr(self.role, "value") else str(self.role or "")
        return bool(self.is_management or role_str in ("management", "admin"))

    @property
    def can_see_all_requisitions(self) -> bool:
        return bool(self.has_management_authority or self.can_perform_qc or self.can_view_all_requisitions)

