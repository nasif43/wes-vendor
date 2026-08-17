import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.auth.models import UserProfile, UserRole
from app.database import Base
from app.requisitions.models import Requisition, RequisitionStatus
from app.requisitions.service import (
    ALLOWED_TRANSITIONS,
    InvalidStateTransitionError,
    transition_requisition_status,
)


@pytest.fixture
async def async_db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as session:
        yield session


def test_allowed_transitions_graph_coverage():
    """Verify that all enum statuses exist in the state machine graph."""
    for status in RequisitionStatus:
        assert status in ALLOWED_TRANSITIONS
        assert status in ALLOWED_TRANSITIONS[status]  # Idempotent re-affirmation allowed


@pytest.mark.anyio
async def test_legal_requisition_lifecycle(async_db_session):
    """Test full sequential lifecycle: DRAFT -> NEW -> IN_PROGRESS -> SUBMITTED -> RECEIVED -> CLOSED."""
    actor = UserProfile(
        email="procurement@wener.com",
        full_name="Procurement Officer",
        role=UserRole.PROCUREMENT,
    )
    async_db_session.add(actor)
    await async_db_session.flush()

    req = Requisition(
        title="Laptop Batch Q3",
        item_description="10x Thinkpad laptops",
        quantity=10,
        status=RequisitionStatus.DRAFT,
        created_by=actor.id,
    )
    async_db_session.add(req)
    await async_db_session.flush()

    assert req.status == RequisitionStatus.DRAFT

    # 1. Invite Vendors: DRAFT -> NEW
    await transition_requisition_status(
        async_db_session,
        requisition=req,
        target_status=RequisitionStatus.NEW,
        actor=actor,
        action_name="VENDORS_INVITED",
    )
    assert req.status == RequisitionStatus.NEW

    # 2. Quotation Received: NEW -> IN_PROGRESS
    await transition_requisition_status(
        async_db_session,
        requisition=req,
        target_status=RequisitionStatus.IN_PROGRESS,
        actor=actor,
        action_name="QUOTATION_RECEIVED",
    )
    assert req.status == RequisitionStatus.IN_PROGRESS

    # 3. Decision Selected: IN_PROGRESS -> SUBMITTED
    await transition_requisition_status(
        async_db_session,
        requisition=req,
        target_status=RequisitionStatus.SUBMITTED,
        actor=actor,
        action_name="DECISION_CREATED",
    )
    assert req.status == RequisitionStatus.SUBMITTED

    # 4. Delivery Arrived: SUBMITTED -> RECEIVED
    await transition_requisition_status(
        async_db_session,
        requisition=req,
        target_status=RequisitionStatus.RECEIVED,
        actor=actor,
        action_name="DELIVERY_RECEIVED",
    )
    assert req.status == RequisitionStatus.RECEIVED

    # 5. QC Done: RECEIVED -> CLOSED
    await transition_requisition_status(
        async_db_session,
        requisition=req,
        target_status=RequisitionStatus.CLOSED,
        actor=actor,
        action_name="QC_COMPLETED",
    )
    assert req.status == RequisitionStatus.CLOSED


@pytest.mark.anyio
async def test_illegal_transition_rejection(async_db_session):
    """Test that transitioning from CLOSED back to DRAFT or IN_PROGRESS raises InvalidStateTransitionError."""
    actor = UserProfile(
        email="admin@wener.com",
        full_name="Admin User",
        role=UserRole.ADMIN,
    )
    async_db_session.add(actor)
    await async_db_session.flush()

    req = Requisition(
        title="Completed Requisition",
        item_description="Finished items",
        quantity=5,
        status=RequisitionStatus.CLOSED,
        created_by=actor.id,
    )
    async_db_session.add(req)
    await async_db_session.flush()

    # Attempt illegal transition: CLOSED -> DRAFT
    with pytest.raises(InvalidStateTransitionError):
        await transition_requisition_status(
            async_db_session,
            requisition=req,
            target_status=RequisitionStatus.DRAFT,
            actor=actor,
            action_name="ILLEGAL_RESET",
        )

    # Attempt illegal transition: CLOSED -> IN_PROGRESS
    with pytest.raises(InvalidStateTransitionError):
        await transition_requisition_status(
            async_db_session,
            requisition=req,
            target_status=RequisitionStatus.IN_PROGRESS,
            actor=actor,
            action_name="ILLEGAL_REGRESSION",
        )
