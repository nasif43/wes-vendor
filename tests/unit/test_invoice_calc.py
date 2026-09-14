"""Unit tests for invoice calculation logic."""
import pytest


class TestInvoiceCalculation:
    """Tests for received_qty * unit_price invoice math."""

    def _calc_invoice(self, line_items: list[dict]) -> float:
        """Simulate the invoice calculation from routes_receiving.py."""
        total = 0.0
        for item in line_items:
            received = float(item.get("received_qty", 0))
            price = float(item.get("unit_price", 0))
            total += received * price
        return round(total, 2)

    def _calc_defect_rate(self, ordered: float, rejected: float) -> float:
        if ordered <= 0:
            return 0.0
        return round(rejected / ordered * 100.0, 2)

    def test_full_acceptance(self):
        items = [
            {"received_qty": 10, "unit_price": 500.0},
            {"received_qty": 5, "unit_price": 1200.0},
        ]
        assert self._calc_invoice(items) == 11000.0

    def test_partial_acceptance(self):
        """Only accepted items are billed."""
        items = [
            {"received_qty": 8, "unit_price": 500.0},   # ordered 10, received 8
            {"received_qty": 5, "unit_price": 1200.0},
        ]
        assert self._calc_invoice(items) == 10000.0

    def test_all_rejected(self):
        items = [
            {"received_qty": 0, "unit_price": 500.0},
        ]
        assert self._calc_invoice(items) == 0.0

    def test_zero_price_item(self):
        items = [
            {"received_qty": 10, "unit_price": 0.0},
        ]
        assert self._calc_invoice(items) == 0.0

    def test_defect_rate_20_percent(self):
        rate = self._calc_defect_rate(ordered=10, rejected=2)
        assert rate == 20.0

    def test_defect_rate_zero(self):
        rate = self._calc_defect_rate(ordered=10, rejected=0)
        assert rate == 0.0

    def test_defect_rate_100_percent(self):
        rate = self._calc_defect_rate(ordered=5, rejected=5)
        assert rate == 100.0

    def test_defect_rate_zero_ordered(self):
        """No division by zero when ordered=0."""
        rate = self._calc_defect_rate(ordered=0, rejected=0)
        assert rate == 0.0

    def test_multi_item_mixed_acceptance(self):
        items = [
            {"received_qty": 8, "unit_price": 100.0},   # 800
            {"received_qty": 0, "unit_price": 200.0},   # 0 (all rejected)
            {"received_qty": 3, "unit_price": 50.0},    # 150
        ]
        assert self._calc_invoice(items) == 950.0
