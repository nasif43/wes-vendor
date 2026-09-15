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

# Use a real connection pool instead of NullPool.
# NullPool opens a fresh TCP+TLS connection for every single query — extremely slow.
# AsyncAdaptedQueuePool reuses connections across requests, saving 10-100ms per query.
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool  # noqa: E402

_is_sqlite = db_url.startswith("sqlite")

engine = create_async_engine(
    db_url,
    echo=False,
    # SQLite doesn't support connection pooling — it's file-based and single-writer.
    poolclass=NullPool if _is_sqlite else AsyncAdaptedQueuePool,
    **({} if _is_sqlite else {
        "pool_size": 5,          # maintain 5 persistent connections
        "max_overflow": 10,      # allow up to 10 extra connections under load
        "pool_timeout": 30,      # wait up to 30s for a free connection before raising
        "pool_recycle": 1800,    # recycle connections after 30min to avoid Supabase idle timeouts
        "pool_pre_ping": True,   # test connections before use; auto-discard dead ones
    }),
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
    """
    Yield a database session.
    The session does NOT auto-commit — handlers that write data must call
    await db.commit() explicitly. Read-only handlers pay zero WAL overhead.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
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
    from app.work_orders.models import WorkOrder, SupplierRating  # noqa: F401
    from app.requisitions.models import ShortlistedItem, ReceivedItem  # noqa: F401
    from app.vendors.models import Vendor, vendor_categories  # noqa: F401

    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        dialect_name = conn.dialect.name

        if dialect_name == "postgresql":
            # ── Single round-trip: fetch ALL existing columns across all tables at once.
            # Previously this was 50+ individual information_schema queries. Now it's 1.
            res = await conn.execute(text("""
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name IN (
                    'vendors', 'user_profiles', 'requisitions',
                    'requisition_vendors', 'quotations', 'decisions',
                    'work_orders', 'supplier_ratings', 'shortlisted_items', 'received_items'
                  )
            """))
            existing: set[tuple[str, str]] = {(row[0], row[1]) for row in res.fetchall()}

            def col_exists(table: str, column: str) -> bool:
                return (table, column) in existing

            # ── vendors ──────────────────────────────────────────────────────────────
            for col, defn in [
                ("is_temporary", "BOOLEAN DEFAULT FALSE"),
                ("created_by", "VARCHAR(36)"),
                ("image_url", "VARCHAR(512)"),
            ]:
                if not col_exists("vendors", col):
                    await conn.execute(text(f"ALTER TABLE vendors ADD COLUMN {col} {defn}"))

            # ── user_profiles ────────────────────────────────────────────────────────
            for col, defn in [
                ("can_view_quotations", "BOOLEAN DEFAULT FALSE"),
                ("can_do_qc", "BOOLEAN DEFAULT FALSE"),
                ("can_view_all_requisitions", "BOOLEAN DEFAULT FALSE"),
                ("is_management", "BOOLEAN DEFAULT FALSE"),
            ]:
                if not col_exists("user_profiles", col):
                    await conn.execute(text(f"ALTER TABLE user_profiles ADD COLUMN {col} {defn}"))

            # ── requisitions ─────────────────────────────────────────────────────────
            for col, defn in [
                ("delivery_image_url", "VARCHAR(512)"),
                ("qc_done", "BOOLEAN DEFAULT FALSE"),
                ("qc_done_by", "VARCHAR(36)"),
                ("qc_done_at", "TIMESTAMP WITH TIME ZONE"),
                ("invoice_url", "VARCHAR(512)"),
                ("invoice_number", "VARCHAR(255)"),
                ("payment_status", "VARCHAR(50) DEFAULT 'pending'"),
                ("received_pieces", "INTEGER"),
                ("received_at", "TIMESTAMP WITH TIME ZONE"),
                ("qc_number", "VARCHAR(255)"),
                ("receiver_number", "VARCHAR(255)"),
                ("rejected_reason", "TEXT"),
                ("items", "JSONB"),
            ]:
                if not col_exists("requisitions", col):
                    await conn.execute(text(f"ALTER TABLE requisitions ADD COLUMN {col} {defn}"))

            # ── requisition_vendors ──────────────────────────────────────────────────
            for col, defn in [
                ("is_shortlisted", "BOOLEAN DEFAULT FALSE"),
                ("allocated_quantity", "NUMERIC"),
                ("negotiation_version", "INTEGER DEFAULT 1"),
            ]:
                if not col_exists("requisition_vendors", col):
                    await conn.execute(text(f"ALTER TABLE requisition_vendors ADD COLUMN {col} {defn}"))

            # ── quotations ───────────────────────────────────────────────────────────
            for col, defn in [
                ("quote_version", "INTEGER DEFAULT 1"),
                ("quoted_quantity", "NUMERIC"),
            ]:
                if not col_exists("quotations", col):
                    await conn.execute(text(f"ALTER TABLE quotations ADD COLUMN {col} {defn}"))

            # ── decisions ────────────────────────────────────────────────────────────
            for col, defn in [
                ("work_order_status", "VARCHAR(50) DEFAULT 'pending_approval'"),
                ("work_order_url", "VARCHAR(512)"),
            ]:
                if not col_exists("decisions", col):
                    await conn.execute(text(f"ALTER TABLE decisions ADD COLUMN {col} {defn}"))

            # ── work_orders ──────────────────────────────────────────────────────────
            for col, defn in [
                ("letterhead_slot", "VARCHAR(10)"),
                ("notes", "TEXT"),
                ("delivery_started_at", "TIMESTAMP WITH TIME ZONE"),
                ("delivery_completed_at", "TIMESTAMP WITH TIME ZONE"),
            ]:
                if not col_exists("work_orders", col):
                    await conn.execute(text(f"ALTER TABLE work_orders ADD COLUMN {col} {defn}"))

            # ── Indexes — CREATE INDEX IF NOT EXISTS (idempotent, one-time cost) ─────
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS idx_requisitions_created_by ON requisitions(created_by)",
                "CREATE INDEX IF NOT EXISTS idx_requisitions_created_at ON requisitions(created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_requisitions_status ON requisitions(status)",
                "CREATE INDEX IF NOT EXISTS idx_requisitions_qc_done ON requisitions(qc_done)",
                "CREATE INDEX IF NOT EXISTS idx_req_vendors_requisition_id ON requisition_vendors(requisition_id)",
                "CREATE INDEX IF NOT EXISTS idx_req_vendors_vendor_id ON requisition_vendors(vendor_id)",
                "CREATE INDEX IF NOT EXISTS idx_decisions_requisition_id ON decisions(requisition_id)",
                "CREATE INDEX IF NOT EXISTS idx_decisions_mgmt_approved ON decisions(management_approved)",
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_user_profiles_email ON user_profiles(email)",
                "CREATE INDEX IF NOT EXISTS idx_vendors_is_active ON vendors(is_active)",
                "CREATE INDEX IF NOT EXISTS idx_quotations_req_vendor_id ON quotations(requisition_vendor_id)",
                "CREATE INDEX IF NOT EXISTS idx_work_orders_requisition_id ON work_orders(requisition_id)",
                "CREATE INDEX IF NOT EXISTS idx_work_orders_vendor_id ON work_orders(vendor_id)",
                "CREATE INDEX IF NOT EXISTS idx_supplier_ratings_vendor_id ON supplier_ratings(vendor_id)",
                "CREATE INDEX IF NOT EXISTS idx_shortlisted_items_rv_id ON shortlisted_items(requisition_vendor_id)",
                "CREATE INDEX IF NOT EXISTS idx_received_items_req_id ON received_items(requisition_id)",
            ]:
                try:
                    await conn.execute(text(idx_sql))
                except Exception as e:
                    logger.warning("Index creation skipped: %s", e)

        else:
            # ── SQLite fallback ───────────────────────────────────────────────────────
            sqlite_existing: set[tuple[str, str]] = set()
            for table in ("vendors", "user_profiles", "requisitions", "requisition_vendors", "quotations", "decisions", "work_orders", "supplier_ratings", "shortlisted_items", "received_items"):
                try:
                    res = await conn.execute(text(f"PRAGMA table_info({table})"))
                    for row in res.fetchall():
                        sqlite_existing.add((table, row[1]))
                except Exception:
                    pass

            def col_exists(table: str, column: str) -> bool:  # type: ignore[misc]
                return (table, column) in sqlite_existing

            for col, defn in [("is_temporary", "BOOLEAN DEFAULT 0"), ("created_by", "VARCHAR(36)"), ("image_url", "VARCHAR(512)")]:
                if not col_exists("vendors", col):
                    await conn.execute(text(f"ALTER TABLE vendors ADD COLUMN {col} {defn}"))

            for col, defn in [
                ("can_view_quotations", "BOOLEAN DEFAULT 0"), ("can_do_qc", "BOOLEAN DEFAULT 0"),
                ("can_view_all_requisitions", "BOOLEAN DEFAULT 0"), ("is_management", "BOOLEAN DEFAULT 0"),
            ]:
                if not col_exists("user_profiles", col):
                    await conn.execute(text(f"ALTER TABLE user_profiles ADD COLUMN {col} {defn}"))

            for col, defn in [
                ("delivery_image_url", "VARCHAR(512)"), ("qc_done", "BOOLEAN DEFAULT 0"),
                ("qc_done_by", "VARCHAR(36)"), ("qc_done_at", "DATETIME"),
                ("invoice_url", "VARCHAR(512)"), ("invoice_number", "VARCHAR(255)"),
                ("payment_status", "VARCHAR(50) DEFAULT 'pending'"), ("received_pieces", "INTEGER"),
                ("received_at", "DATETIME"), ("qc_number", "VARCHAR(255)"),
                ("receiver_number", "VARCHAR(255)"), ("rejected_reason", "TEXT"), ("items", "TEXT"),
            ]:
                if not col_exists("requisitions", col):
                    await conn.execute(text(f"ALTER TABLE requisitions ADD COLUMN {col} {defn}"))

            for col, defn in [
                ("is_shortlisted", "BOOLEAN DEFAULT 0"), ("allocated_quantity", "NUMERIC"),
                ("negotiation_version", "INTEGER DEFAULT 1"),
            ]:
                if not col_exists("requisition_vendors", col):
                    await conn.execute(text(f"ALTER TABLE requisition_vendors ADD COLUMN {col} {defn}"))

            for col, defn in [("quote_version", "INTEGER DEFAULT 1"), ("quoted_quantity", "NUMERIC")]:
                if not col_exists("quotations", col):
                    await conn.execute(text(f"ALTER TABLE quotations ADD COLUMN {col} {defn}"))

            for col, defn in [
                ("work_order_status", "VARCHAR(50) DEFAULT 'pending_approval'"), ("work_order_url", "VARCHAR(512)"),
            ]:
                if not col_exists("decisions", col):
                    await conn.execute(text(f"ALTER TABLE decisions ADD COLUMN {col} {defn}"))

            for col, defn in [
                ("letterhead_slot", "VARCHAR(10)"),
                ("notes", "TEXT"),
                ("delivery_started_at", "DATETIME"),
                ("delivery_completed_at", "DATETIME"),
            ]:
                if not col_exists("work_orders", col):
                    await conn.execute(text(f"ALTER TABLE work_orders ADD COLUMN {col} {defn}"))
