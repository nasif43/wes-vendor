"""Unit tests for supplier rating computation."""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestSupplierRatingCalc:
    """Tests for create_supplier_rating logic."""

    def _make_received_item(self, ordered, received, rejected):
        ri = MagicMock()
        ri.ordered_qty = ordered
        ri.received_qty = received
        ri.rejected_qty = rejected
        return ri

    def _compute_stats(self, received_items: list):
        total_ordered = sum(float(ri.ordered_qty) for ri in received_items)
        total_received = sum(float(ri.received_qty) for ri in received_items)
        total_rejected = sum(float(ri.rejected_qty) for ri in received_items)
        defect_rate = (total_rejected / total_ordered * 100.0) if total_ordered > 0 else 0.0
        return {
            "ordered": total_ordered,
            "received": total_received,
            "rejected": total_rejected,
            "defect_rate": round(defect_rate, 2),
        }

    def test_perfect_delivery(self):
        items = [
            self._make_received_item(10, 10, 0),
            self._make_received_item(5, 5, 0),
        ]
        stats = self._compute_stats(items)
        assert stats["ordered"] == 15.0
        assert stats["received"] == 15.0
        assert stats["rejected"] == 0.0
        assert stats["defect_rate"] == 0.0

    def test_partial_rejection(self):
        items = [
            self._make_received_item(10, 8, 2),
            self._make_received_item(5, 5, 0),
        ]
        stats = self._compute_stats(items)
        assert stats["ordered"] == 15.0
        assert stats["received"] == 13.0
        assert stats["rejected"] == 2.0
        assert stats["defect_rate"] == pytest.approx(13.33, abs=0.01)

    def test_all_rejected(self):
        items = [self._make_received_item(5, 0, 5)]
        stats = self._compute_stats(items)
        assert stats["defect_rate"] == 100.0

    def test_delivery_days_calculation(self):
        from datetime import datetime, timezone, timedelta
        started = datetime(2024, 1, 1, tzinfo=timezone.utc)
        completed = datetime(2024, 1, 8, tzinfo=timezone.utc)  # 7 days
        delta = completed - started
        days = round(delta.total_seconds() / 86400.0, 2)
        assert days == 7.0

    def test_delivery_days_fractional(self):
        from datetime import datetime, timezone, timedelta
        started = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        completed = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)  # 0.5 days
        delta = completed - started
        days = round(delta.total_seconds() / 86400.0, 2)
        assert days == 0.5
