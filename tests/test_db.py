from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Table, create_engine
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

DATABASE_URL = "sqlite:///test.db"

engine = create_engine(DATABASE_URL, echo=False)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# Minimal models for testing
class Category(Base):
    __tablename__ = "categories"
    id = Column(String(36), primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

vendor_categories = Table(
    "vendor_categories", Base.metadata,
    Column("vendor_id", String(36), ForeignKey("vendors.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "category_id", String(36),
        ForeignKey("categories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Vendor(Base):
    __tablename__ = "vendors"
    id = Column(String(36), primary_key=True)
    company_name = Column(String(255), nullable=False)
    contact_email = Column(String(255), nullable=False)
    contact_person = Column(String(255))
    phone = Column(String(50))
    notes = Column(String(1000))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    categories = relationship("Category", secondary=vendor_categories, backref="vendors")


class UserProfile(Base):
    __tablename__ = "user_profiles"
    id = Column(String(36), primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(30), default="requester")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
