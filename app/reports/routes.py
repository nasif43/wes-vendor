from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select as sa_select
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user
from app.auth.models import UserProfile
from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.requisitions.models import Requisition
from app.decisions.models import Decision
import logging

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/", response_class=HTMLResponse)
async def list_reports(
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        # Fetch all delivered requisitions with decision and creator
        result = await db.execute(
            sa_select(Requisition)
            .options(selectinload(Requisition.creator))
            .where(Requisition.qc_done == True)
            .order_by(Requisition.qc_done_at.desc())
        )
        delivered_reqs = result.scalars().all()

        # We also need the management decision approval date to calculate duration
        req_ids = [r.id for r in delivered_reqs]
        
        decisions_map = {}
        if req_ids:
            dec_result = await db.execute(
                sa_select(Decision)
                .where(Decision.requisition_id.in_(req_ids))
            )
            for d in dec_result.scalars().all():
                decisions_map[d.requisition_id] = d
        
        report_data = []
        for req in delivered_reqs:
            decision = decisions_map.get(req.id)
            duration_days = None
            if decision and decision.approved_at and req.qc_done_at:
                diff = req.qc_done_at - decision.approved_at
                duration_days = round(diff.total_seconds() / 86400, 1)

            report_data.append({
                "requisition": req,
                "decision": decision,
                "duration_days": duration_days
            })
            
    except Exception as e:
        logger.exception("Error loading reports")
        report_data = []

    return templates.TemplateResponse(
        request,
        "reports/list.html",
        {"report_data": report_data, "user": user}
    )
