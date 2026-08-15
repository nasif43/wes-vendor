"""
SystemSettings model — stores key/value config for management-editable settings.
The 'cc_emails' key holds a JSON list of CC email addresses used in all outbound emails.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SystemSettings(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ─── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def cc_emails_key() -> str:
        return "cc_emails"

    def get_list(self) -> list[str]:
        """Deserialize the JSON value into a list of strings."""
        try:
            result = json.loads(self.value or "[]")
            return [e for e in result if isinstance(e, str) and e.strip()]
        except Exception:
            return []

    @staticmethod
    def encode_list(emails: list[str]) -> str:
        return json.dumps([e.strip() for e in emails if e.strip()])
