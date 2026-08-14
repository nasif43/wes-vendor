import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.database import init_db

logger = logging.getLogger(__name__)
settings = get_settings()

templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting up — DEBUG=%s", settings.debug)

    try:
        await init_db()
        logger.info("Database tables created/verified")
    except Exception as e:
        logger.exception("init_db error during startup: %s", e)

    try:
        from app.storage import ensure_bucket_exists
        await ensure_bucket_exists()
        logger.info("Storage bucket ready")
    except Exception as e:
        logger.exception("ensure_bucket_exists error during startup: %s", e)

    yield



app = FastAPI(
    title="Vendor Management Portal",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.debug else None,
    redoc_url=None,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="session",
    max_age=86400 * 7,
)

# Mount static files only if the directory exists (dev); on Vercel this is skipped
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc), "type": type(exc).__name__},
    )



from app.auth.routes import router as auth_router
from app.audit.routes import router as audit_router
from app.categories.routes import router as categories_router
from app.decisions.routes import router as decisions_router
from app.quotations.routes_internal import router as quotations_internal_router
from app.quotations.routes_vendor import router as quotations_vendor_router
from app.requisitions.routes import router as requisitions_router
from app.vendors.routes import router as vendors_router
from app.reports.routes import router as reports_router
from app.users.routes import router as users_router

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(audit_router, prefix="/audit", tags=["audit"])
app.include_router(vendors_router, prefix="/vendors", tags=["vendors"])
app.include_router(categories_router, prefix="/categories", tags=["categories"])
app.include_router(requisitions_router, prefix="/requisitions", tags=["requisitions"])
app.include_router(quotations_vendor_router, prefix="/vendor-quote", tags=["vendor-quote"])
app.include_router(quotations_internal_router, prefix="/quotations", tags=["quotations"])
app.include_router(decisions_router, prefix="/decisions", tags=["decisions"])
app.include_router(reports_router, prefix="/reports", tags=["reports"])
app.include_router(users_router, prefix="/users", tags=["users"])


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def index(request: Request):
    from sqlalchemy import select as sa_select, func
    from app.database import AsyncSessionLocal
    from app.auth.models import UserProfile

    user_id = request.session.get("user_id")
    user = None
    stats = {
        "open_requisitions": 0,
        "delivered_requisitions": 0,
        "pending_payments": 0,
        "total_vendors": 0,
        "pending_decisions": 0,
    }
    recent_requisitions = []
    recent_audits = []

    if user_id:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                sa_select(UserProfile).where(UserProfile.id == user_id)
            )
            user = result.scalar_one_or_none()

    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    try:
        from app.vendors.models import Vendor
        from app.quotations.models import Quotation
        from app.requisitions.models import Requisition, RequisitionStatus
        from app.decisions.models import Decision

        async with AsyncSessionLocal() as db:
            # 1. Active / In-Progress Requisitions (qc_done=False & status != CLOSED)
            open_req_r = await db.execute(
                sa_select(func.count(Requisition.id)).where(
                    Requisition.qc_done == False,
                    Requisition.status != RequisitionStatus.CLOSED
                )
            )
            open_requisitions = open_req_r.scalar_one() or 0

            # 2. Delivered & QC Completed Requisitions
            delivered_r = await db.execute(
                sa_select(func.count(Requisition.id)).where(
                    Requisition.qc_done == True
                )
            )
            delivered_requisitions = delivered_r.scalar_one() or 0

            # 3. Pending Payments
            pending_pay_r = await db.execute(
                sa_select(func.count(Requisition.id)).where(
                    Requisition.qc_done == True,
                    Requisition.payment_status != "paid"
                )
            )
            pending_payments = pending_pay_r.scalar_one() or 0

            # 4. Total Active Vendors
            vendors_r = await db.execute(
                sa_select(func.count(Vendor.id)).where(
                    Vendor.is_active == True,
                    Vendor.is_temporary == False
                )
            )
            total_vendors = vendors_r.scalar_one() or 0

            # 5. Pending Management Decisions
            pending_dec_r = await db.execute(
                sa_select(func.count(Decision.id)).where(
                    Decision.management_approved == None
                )
            )
            pending_decisions = pending_dec_r.scalar_one() or 0

            # 6. Confirmed Active Orders (Management approved, awaiting QC delivery)
            confirmed_r = await db.execute(
                sa_select(func.count(Decision.id))
                .join(Requisition, Decision.requisition_id == Requisition.id)
                .where(
                    Decision.management_approved == True,
                    Requisition.qc_done == False
                )
            )
            confirmed_orders = confirmed_r.scalar_one() or 0

            # 7. Calculate Real Average Lead Time (Time from Decision Approval to QC Received)
            completed_reqs_r = await db.execute(
                sa_select(Requisition, Decision)
                .join(Decision, Requisition.id == Decision.requisition_id)
                .where(
                    Requisition.qc_done == True,
                    Requisition.qc_done_at.isnot(None),
                    Decision.approved_at.isnot(None)
                )
            )
            completed_pairs = completed_reqs_r.all()
            lead_times = []
            for req, dec in completed_pairs:
                if req.qc_done_at and dec.approved_at:
                    dur_days = (req.qc_done_at - dec.approved_at).total_seconds() / 86400.0
                    if dur_days >= 0:
                        lead_times.append(dur_days)

            avg_lead_time_days = round(sum(lead_times) / len(lead_times), 1) if lead_times else None

            total_reqs = open_requisitions + delivered_requisitions
            qc_rate = round((delivered_requisitions / total_reqs * 100.0), 1) if total_reqs > 0 else 0.0

            stats = {
                "open_requisitions": open_requisitions,
                "delivered_requisitions": delivered_requisitions,
                "pending_payments": pending_payments,
                "total_vendors": total_vendors,
                "pending_decisions": pending_decisions,
                "confirmed_orders": confirmed_orders,
                "avg_lead_time_days": avg_lead_time_days,
                "total_requisitions": total_reqs,
                "qc_completion_rate": qc_rate,
            }

            recent_r = await db.execute(
                sa_select(Requisition)
                .order_by(Requisition.created_at.desc())
                .limit(5)
            )
            recent_requisitions = list(recent_r.scalars().all())

            try:
                from app.audit.models import AuditLog
                audit_r = await db.execute(
                    sa_select(AuditLog)
                    .order_by(AuditLog.created_at.desc())
                    .limit(5)
                )
                recent_audits = list(audit_r.scalars().all())
            except Exception as audit_err:
                logger.warning("Failed to fetch recent audit logs: %s", audit_err)
    except Exception as err:
        logger.exception("Failed to load dashboard stats: %s", err)

    return templates.TemplateResponse(request, "index.html", {
        "user": user,
        "stats": stats,
        "recent_requisitions": recent_requisitions,
        "recent_audits": recent_audits,
    })

