"""Integration tests for state machine transitions with real async DB."""
import pytest
pytestmark = pytest.mark.asyncio


async def _make_user(db, role="management"):
    from app.auth.models import UserProfile, UserRole
    from uuid import uuid4
    user = UserProfile(
        id=str(uuid4()),
        email=f"test_{uuid4().hex[:6]}@test.com",
        full_name="Test User",
        role=UserRole(role),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_requisition(db, creator, status="draft"):
    from app.requisitions.models import Requisition, RequisitionStatus
    from uuid import uuid4
    req = Requisition(
        id=str(uuid4()),
        title="Test Requisition",
        item_description="Test items",
        quantity=10,
        items=[{"name": "Chair", "description": "Ergonomic", "qty": 10}],
        status=RequisitionStatus(status),
        created_by=creator.id,
    )
    db.add(req)
    await db.flush()
    return req


async def test_draft_to_new(async_db):
    from app.requisitions.service import transition_requisition_status
    from app.requisitions.models import RequisitionStatus

    user = await _make_user(async_db, "procurement")
    req = await _make_requisition(async_db, user, "draft")

    result = await transition_requisition_status(
        async_db, requisition=req,
        target_status=RequisitionStatus.NEW,
        actor=user, action_name="TEST",
    )
    assert result.status == RequisitionStatus.NEW


async def test_in_progress_to_negotiating(async_db):
    from app.requisitions.service import transition_requisition_status
    from app.requisitions.models import RequisitionStatus

    user = await _make_user(async_db, "management")
    req = await _make_requisition(async_db, user, "in_progress")

    result = await transition_requisition_status(
        async_db, requisition=req,
        target_status=RequisitionStatus.NEGOTIATING,
        actor=user, action_name="NEGOTIATION_STARTED",
    )
    assert result.status == RequisitionStatus.NEGOTIATING


async def test_negotiating_to_awarded(async_db):
    from app.requisitions.service import transition_requisition_status
    from app.requisitions.models import RequisitionStatus

    user = await _make_user(async_db, "management")
    req = await _make_requisition(async_db, user, "negotiating")

    result = await transition_requisition_status(
        async_db, requisition=req,
        target_status=RequisitionStatus.AWARDED,
        actor=user, action_name="WINNER_SELECTED",
    )
    assert result.status == RequisitionStatus.AWARDED


async def test_awarded_to_work_order_issued(async_db):
    from app.requisitions.service import transition_requisition_status
    from app.requisitions.models import RequisitionStatus

    user = await _make_user(async_db, "procurement")
    req = await _make_requisition(async_db, user, "awarded")

    result = await transition_requisition_status(
        async_db, requisition=req,
        target_status=RequisitionStatus.WORK_ORDER_ISSUED,
        actor=user, action_name="WORK_ORDER_ISSUED",
    )
    assert result.status == RequisitionStatus.WORK_ORDER_ISSUED


async def test_receiving_to_closed(async_db):
    from app.requisitions.service import transition_requisition_status
    from app.requisitions.models import RequisitionStatus

    user = await _make_user(async_db, "qc_receiver")
    req = await _make_requisition(async_db, user, "receiving")

    result = await transition_requisition_status(
        async_db, requisition=req,
        target_status=RequisitionStatus.CLOSED,
        actor=user, action_name="QC_COMPLETED",
    )
    assert result.status == RequisitionStatus.CLOSED


async def test_illegal_transition_raises(async_db):
    from app.requisitions.service import transition_requisition_status, InvalidStateTransitionError
    from app.requisitions.models import RequisitionStatus

    user = await _make_user(async_db, "procurement")
    req = await _make_requisition(async_db, user, "closed")

    with pytest.raises(InvalidStateTransitionError):
        await transition_requisition_status(
            async_db, requisition=req,
            target_status=RequisitionStatus.DRAFT,
            actor=user, action_name="ILLEGAL",
        )


async def test_rejected_reopens_to_draft(async_db):
    from app.requisitions.service import transition_requisition_status
    from app.requisitions.models import RequisitionStatus

    user = await _make_user(async_db, "management")
    req = await _make_requisition(async_db, user, "rejected")

    result = await transition_requisition_status(
        async_db, requisition=req,
        target_status=RequisitionStatus.DRAFT,
        actor=user, action_name="REOPEN",
    )
    assert result.status == RequisitionStatus.DRAFT
