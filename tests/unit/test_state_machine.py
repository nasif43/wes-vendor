"""Unit tests for the requisition state machine."""
import pytest
from app.requisitions.models import RequisitionStatus
from app.requisitions.service import ALLOWED_TRANSITIONS, InvalidStateTransitionError


class TestRequisitionStatusEnum:
    def test_all_new_statuses_exist(self):
        assert RequisitionStatus.NEGOTIATING == "negotiating"
        assert RequisitionStatus.AWARDED == "awarded"
        assert RequisitionStatus.WORK_ORDER_ISSUED == "work_order_issued"
        assert RequisitionStatus.RECEIVING == "receiving"

    def test_legacy_statuses_preserved(self):
        assert RequisitionStatus.SUBMITTED == "submitted"
        assert RequisitionStatus.RECEIVED == "received"

    def test_terminal_states(self):
        assert RequisitionStatus.CLOSED in ALLOWED_TRANSITIONS
        assert RequisitionStatus.CANCELLED in ALLOWED_TRANSITIONS
        # Terminal: only self-transition
        assert ALLOWED_TRANSITIONS[RequisitionStatus.CLOSED] == {RequisitionStatus.CLOSED}
        assert ALLOWED_TRANSITIONS[RequisitionStatus.CANCELLED] == {RequisitionStatus.CANCELLED}


class TestAllowedTransitions:
    def test_draft_to_new(self):
        assert RequisitionStatus.NEW in ALLOWED_TRANSITIONS[RequisitionStatus.DRAFT]

    def test_new_to_in_progress(self):
        assert RequisitionStatus.IN_PROGRESS in ALLOWED_TRANSITIONS[RequisitionStatus.NEW]

    def test_in_progress_to_negotiating(self):
        assert RequisitionStatus.NEGOTIATING in ALLOWED_TRANSITIONS[RequisitionStatus.IN_PROGRESS]

    def test_negotiating_to_awarded(self):
        assert RequisitionStatus.AWARDED in ALLOWED_TRANSITIONS[RequisitionStatus.NEGOTIATING]

    def test_awarded_to_work_order_issued(self):
        assert RequisitionStatus.WORK_ORDER_ISSUED in ALLOWED_TRANSITIONS[RequisitionStatus.AWARDED]

    def test_work_order_issued_to_receiving(self):
        assert RequisitionStatus.RECEIVING in ALLOWED_TRANSITIONS[RequisitionStatus.WORK_ORDER_ISSUED]

    def test_receiving_to_closed(self):
        assert RequisitionStatus.CLOSED in ALLOWED_TRANSITIONS[RequisitionStatus.RECEIVING]

    def test_rejected_can_reopen_to_draft(self):
        assert RequisitionStatus.DRAFT in ALLOWED_TRANSITIONS[RequisitionStatus.REJECTED]

    def test_all_statuses_in_transitions(self):
        """Every status must appear as a key in ALLOWED_TRANSITIONS."""
        for status in RequisitionStatus:
            assert status in ALLOWED_TRANSITIONS, f"{status} missing from ALLOWED_TRANSITIONS"

    def test_in_progress_can_cancel(self):
        assert RequisitionStatus.CANCELLED in ALLOWED_TRANSITIONS[RequisitionStatus.IN_PROGRESS]

    def test_negotiating_can_cancel(self):
        assert RequisitionStatus.CANCELLED in ALLOWED_TRANSITIONS[RequisitionStatus.NEGOTIATING]


class TestInvalidStateTransitionError:
    def test_is_exception(self):
        err = InvalidStateTransitionError("test")
        assert isinstance(err, Exception)
        assert str(err) == "test"
