import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

if not settings.database_url:
    logger.warning("DATABASE_URL not set — database features will be unavailable")

db_url = settings.database_url or "sqlite+aiosqlite://"
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)

# prepared_statement_cache_size=0 prevents asyncpg from caching query plans
# across connection pool reuse — avoids InvalidCachedStatementError after schema changes.
_connect_args: dict = {}
if "asyncpg" in db_url:
    _connect_args = {"prepared_statement_cache_size": 0}

from sqlalchemy.pool import NullPool

# NullPool is required for serverless environments (Vercel) and PgBouncer.
# It prevents stale connection caches and InvalidCachedStatementError.
engine = create_async_engine(
    db_url,
    echo=False,
    poolclass=NullPool,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    from app.audit.models import AuditLog  # noqa: F401
    from app.auth.models import UserProfile  # noqa: F401
    from app.categories.models import Category  # noqa: F401
    from app.decisions.models import Decision  # noqa: F401
    from app.quotations.models import Quotation  # noqa: F401
    from app.requisitions.models import Requisition, RequisitionVendor  # noqa: F401
    from app.settings.models import SystemSettings  # noqa: F401
    from app.vendors.models import Vendor, vendor_categories  # noqa: F401

    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        dialect_name = conn.dialect.name
        column_exists = False
        if dialect_name == "postgresql":
            res = await conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='vendors' AND column_name='is_temporary'"
            ))
            column_exists = res.scalar() is not None
        else:
            res = await conn.execute(text("PRAGMA table_info(vendors)"))
            columns = res.fetchall()
            column_exists = any(col[1] == "is_temporary" for col in columns)

        if not column_exists:
            logger.info("Adding is_temporary column to vendors table")
            if dialect_name == "postgresql":
                await conn.execute(text("ALTER TABLE vendors ADD COLUMN is_temporary BOOLEAN DEFAULT FALSE"))
            else:
                await conn.execute(text("ALTER TABLE vendors ADD COLUMN is_temporary BOOLEAN DEFAULT 0"))

        # Vendor created_by column
        vendor_created_by_exists = False
        if dialect_name == "postgresql":
            res = await conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='vendors' AND column_name='created_by'"
            ))
            vendor_created_by_exists = res.scalar() is not None
        else:
            res = await conn.execute(text("PRAGMA table_info(vendors)"))
            columns = res.fetchall()
            vendor_created_by_exists = any(col[1] == "created_by" for col in columns)

        if not vendor_created_by_exists:
            logger.info("Adding created_by column to vendors table")
            await conn.execute(text("ALTER TABLE vendors ADD COLUMN created_by VARCHAR(36)"))

        # UserProfile permission columns
        user_perm_exists = False
        if dialect_name == "postgresql":
            res = await conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='user_profiles' AND column_name='can_view_quotations'"
            ))
            user_perm_exists = res.scalar() is not None
        else:
            res = await conn.execute(text("PRAGMA table_info(user_profiles)"))
            columns = res.fetchall()
            user_perm_exists = any(col[1] == "can_view_quotations" for col in columns)

        if not user_perm_exists:
            logger.info("Adding permission columns to user_profiles table")
            if dialect_name == "postgresql":
                await conn.execute(text("ALTER TABLE user_profiles ADD COLUMN can_view_quotations BOOLEAN DEFAULT FALSE"))
                await conn.execute(text("ALTER TABLE user_profiles ADD COLUMN can_do_qc BOOLEAN DEFAULT FALSE"))
                await conn.execute(text("ALTER TABLE user_profiles ADD COLUMN can_view_all_requisitions BOOLEAN DEFAULT FALSE"))
                await conn.execute(text("ALTER TABLE user_profiles ADD COLUMN is_management BOOLEAN DEFAULT FALSE"))
            else:
                await conn.execute(text("ALTER TABLE user_profiles ADD COLUMN can_view_quotations BOOLEAN DEFAULT 0"))
                await conn.execute(text("ALTER TABLE user_profiles ADD COLUMN can_do_qc BOOLEAN DEFAULT 0"))
                await conn.execute(text("ALTER TABLE user_profiles ADD COLUMN can_view_all_requisitions BOOLEAN DEFAULT 0"))
                await conn.execute(text("ALTER TABLE user_profiles ADD COLUMN is_management BOOLEAN DEFAULT 0"))
        else:
            # Check individual column can_view_all_requisitions
            view_all_exists = False
            if dialect_name == "postgresql":
                res = await conn.execute(text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='user_profiles' AND column_name='can_view_all_requisitions'"
                ))
                view_all_exists = res.scalar() is not None
            else:
                res = await conn.execute(text("PRAGMA table_info(user_profiles)"))
                columns = res.fetchall()
                view_all_exists = any(col[1] == "can_view_all_requisitions" for col in columns)
            if not view_all_exists:
                if dialect_name == "postgresql":
                    await conn.execute(text("ALTER TABLE user_profiles ADD COLUMN can_view_all_requisitions BOOLEAN DEFAULT FALSE"))
                else:
                    await conn.execute(text("ALTER TABLE user_profiles ADD COLUMN can_view_all_requisitions BOOLEAN DEFAULT 0"))



        # Requisition new columns for QC and Delivery
        if dialect_name == "postgresql":
            res = await conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='requisitions' AND column_name='qc_done'"
            ))
            qc_exists = res.scalar() is not None
        else:
            res = await conn.execute(text("PRAGMA table_info(requisitions)"))
            columns = res.fetchall()
            qc_exists = any(col[1] == "qc_done" for col in columns)

        if not qc_exists:
            logger.info("Adding QC and Delivery columns to requisitions table")
            if dialect_name == "postgresql":
                await conn.execute(text("ALTER TABLE requisitions ADD COLUMN delivery_image_url VARCHAR(512)"))
                await conn.execute(text("ALTER TABLE requisitions ADD COLUMN qc_done BOOLEAN DEFAULT FALSE"))
                await conn.execute(text("ALTER TABLE requisitions ADD COLUMN qc_done_by VARCHAR(36)"))
                await conn.execute(text("ALTER TABLE requisitions ADD COLUMN qc_done_at TIMESTAMP WITH TIME ZONE"))
                await conn.execute(text("ALTER TABLE requisitions ADD COLUMN invoice_url VARCHAR(512)"))
                await conn.execute(text("ALTER TABLE requisitions ADD COLUMN invoice_number VARCHAR(255)"))
                await conn.execute(text("ALTER TABLE requisitions ADD COLUMN payment_status VARCHAR(50) DEFAULT 'pending'"))
            else:
                await conn.execute(text("ALTER TABLE requisitions ADD COLUMN delivery_image_url VARCHAR(512)"))
                await conn.execute(text("ALTER TABLE requisitions ADD COLUMN qc_done BOOLEAN DEFAULT 0"))
                await conn.execute(text("ALTER TABLE requisitions ADD COLUMN qc_done_by VARCHAR(36)"))
                await conn.execute(text("ALTER TABLE requisitions ADD COLUMN qc_done_at DATETIME"))
                await conn.execute(text("ALTER TABLE requisitions ADD COLUMN invoice_url VARCHAR(512)"))
                await conn.execute(text("ALTER TABLE requisitions ADD COLUMN invoice_number VARCHAR(255)"))
                await conn.execute(text("ALTER TABLE requisitions ADD COLUMN payment_status VARCHAR(50) DEFAULT 'pending'"))

        # status and role columns are String(50) — no Postgres native enum to migrate

        # ── New negotiation & versioning columns ──────────────────────────────
        # requisition_vendors: is_shortlisted, allocated_quantity, negotiation_version
        for col_name, col_def_pg, col_def_sqlite in [
            ("is_shortlisted", "BOOLEAN DEFAULT FALSE", "BOOLEAN DEFAULT 0"),
            ("allocated_quantity", "NUMERIC", "NUMERIC"),
            ("negotiation_version", "VARCHAR(10) DEFAULT '1'", "VARCHAR(10) DEFAULT '1'"),
        ]:
            col_exists = False
            if dialect_name == "postgresql":
                res = await conn.execute(text(
                    f"SELECT 1 FROM information_schema.columns "
                    f"WHERE table_name='requisition_vendors' AND column_name='{col_name}'"
                ))
                col_exists = res.scalar() is not None
            else:
                res = await conn.execute(text("PRAGMA table_info(requisition_vendors)"))
                columns = res.fetchall()
                col_exists = any(col[1] == col_name for col in columns)
            if not col_exists:
                logger.info("Adding %s column to requisition_vendors table", col_name)
                col_def = col_def_pg if dialect_name == "postgresql" else col_def_sqlite
                await conn.execute(text(
                    f"ALTER TABLE requisition_vendors ADD COLUMN {col_name} {col_def}"
                ))

        # quotations: quote_version, quoted_quantity
        for col_name, col_def_pg, col_def_sqlite in [
            ("quote_version", "INTEGER DEFAULT 1", "INTEGER DEFAULT 1"),
            ("quoted_quantity", "NUMERIC", "NUMERIC"),
        ]:
            col_exists = False
            if dialect_name == "postgresql":
                res = await conn.execute(text(
                    f"SELECT 1 FROM information_schema.columns "
                    f"WHERE table_name='quotations' AND column_name='{col_name}'"
                ))
                col_exists = res.scalar() is not None
            else:
                res = await conn.execute(text("PRAGMA table_info(quotations)"))
                columns = res.fetchall()
                col_exists = any(col[1] == col_name for col in columns)
            if not col_exists:
                logger.info("Adding %s column to quotations table", col_name)
                col_def = col_def_pg if dialect_name == "postgresql" else col_def_sqlite
                await conn.execute(text(
                    f"ALTER TABLE quotations ADD COLUMN {col_name} {col_def}"
                ))

        # requisitions: rejected_reason
        for col_name, col_def_pg, col_def_sqlite in [
            ("rejected_reason", "TEXT", "TEXT"),
        ]:
            col_exists = False
            if dialect_name == "postgresql":
                res = await conn.execute(text(
                    f"SELECT 1 FROM information_schema.columns "
                    f"WHERE table_name='requisitions' AND column_name='{col_name}'"
                ))
                col_exists = res.scalar() is not None
            else:
                res = await conn.execute(text("PRAGMA table_info(requisitions)"))
                columns = res.fetchall()
                col_exists = any(col[1] == col_name for col in columns)
            if not col_exists:
                logger.info("Adding %s column to requisitions table", col_name)
                col_def = col_def_pg if dialect_name == "postgresql" else col_def_sqlite
                await conn.execute(text(
                    f"ALTER TABLE requisitions ADD COLUMN {col_name} {col_def}"
                ))
