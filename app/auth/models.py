import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserRole(enum.StrEnum):
    PROCUREMENT = "procurement"
    QC_RECEIVER = "qc_receiver"
    OPERATIONS_MANAGER = "operations_manager"
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
            if val_lower in ("operations_manager", "operation_manager", "manager", "approver", "op_manager"):
                return cls.OPERATIONS_MANAGER
            for member in cls:
                if member.value.lower() == val_lower or member.name.lower() == val_lower:
                    return member
        return cls.PROCUREMENT


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        String(50), nullable=False, default=UserRole.PROCUREMENT
    )

    can_view_quotations: Mapped[bool] = mapped_column(Boolean, default=False)
    can_do_qc: Mapped[bool] = mapped_column(Boolean, default=False)
    can_view_all_requisitions: Mapped[bool] = mapped_column(Boolean, default=False)
    is_management: Mapped[bool] = mapped_column(Boolean, default=False)
    can_access_audit: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    can_access_users: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    can_access_settings: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def set_password(self, plain_password: str) -> None:
        from app.auth.security import hash_password
        self.password_hash = hash_password(plain_password)

    def check_password(self, plain_password: str) -> bool:
        from app.auth.security import verify_password
        return verify_password(plain_password, self.password_hash)


    @property
    def is_procurement(self) -> bool:
        role_str = str(self.role.value) if hasattr(self.role, "value") else str(self.role or "")
        return bool(role_str in ("procurement", "admin") or self.is_management)


    @property
    def can_create_requisitions(self) -> bool:
        role_str = str(self.role.value) if hasattr(self.role, "value") else str(self.role or "")
        return bool(role_str in ("procurement", "management", "admin", "operations_manager") or self.is_management)


    @property
    def can_see_quotes(self) -> bool:
        role_str = str(self.role.value) if hasattr(self.role, "value") else str(self.role or "")
        # Procurement by default cannot see quotation details/pricing unless explicitly granted can_view_quotations by management
        return bool(self.can_view_quotations or self.is_management or role_str in ("management", "admin", "operations_manager"))


    @property
    def can_perform_qc(self) -> bool:
        role_str = str(self.role.value) if hasattr(self.role, "value") else str(self.role or "")
        return bool(self.can_do_qc or self.is_management or role_str in ("qc_receiver", "management", "admin", "operations_manager"))

    @property
    def has_management_authority(self) -> bool:
        role_str = str(self.role.value) if hasattr(self.role, "value") else str(self.role or "")
        return bool(self.is_management or role_str in ("management", "admin", "operations_manager"))

    @property
    def has_audit_access(self) -> bool:
        role_str = str(self.role.value if hasattr(self.role, "value") else (self.role or "")).lower()
        if role_str == "admin":
            return True
        if self.can_access_audit:
            return True
        if role_str == "management" or self.is_management:
            return True
        return False

    @property
    def has_users_access(self) -> bool:
        role_str = str(self.role.value if hasattr(self.role, "value") else (self.role or "")).lower()
        if role_str == "admin":
            return True
        if self.can_access_users:
            return True
        if role_str == "management" or self.is_management:
            return True
        return False

    @property
    def has_settings_access(self) -> bool:
        role_str = str(self.role.value if hasattr(self.role, "value") else (self.role or "")).lower()
        if role_str == "admin":
            return True
        if self.can_access_settings:
            return True
        if role_str == "management" or self.is_management:
            return True
        return False

    @property
    def can_access_admin_settings(self) -> bool:
        """True if user has access to at least one administration area (Audit, Users, Settings)."""
        return self.has_audit_access or self.has_users_access or self.has_settings_access

    @property
    def can_see_all_requisitions(self) -> bool:
        return bool(self.has_management_authority or self.can_perform_qc or self.can_view_all_requisitions)

    @property
    def is_procurement_blind(self) -> bool:
        """True for Procurement users who cannot view quotation pricing details.
        Management-flagged users and those explicitly granted can_view_quotations are exempt."""
        role_str = str(self.role.value) if hasattr(self.role, "value") else str(self.role or "")
        return bool(
            role_str == "procurement"
            and not self.is_management
            and not self.can_view_quotations
        )

