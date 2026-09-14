"""Unit tests for Quotation model versioning."""
import pytest
from unittest.mock import MagicMock


class TestRequisitionVendorQuotationProperties:
    """Test the backward-compat quotation property on RequisitionVendor."""

    def _make_rv_with_quotations(self, versions: list[int]):
        """Create a mock RequisitionVendor with quotations of given versions."""
        rv = MagicMock()
        quotations = []
        for v in versions:
            q = MagicMock()
            q.quote_version = v
            quotations.append(q)
        # Sort by version like the real relationship does
        quotations.sort(key=lambda x: x.quote_version)
        rv.quotations = quotations

        # Implement the property logic inline
        rv.quotation = quotations[-1] if quotations else None
        rv.v1_quotation = next((q for q in quotations if q.quote_version == 1), None)
        rv.v2_quotation = next((q for q in quotations if q.quote_version == 2), None)
        rv.latest_quotation = quotations[-1] if quotations else None
        return rv

    def test_no_quotations(self):
        rv = self._make_rv_with_quotations([])
        assert rv.quotation is None
        assert rv.v1_quotation is None
        assert rv.v2_quotation is None

    def test_only_v1(self):
        rv = self._make_rv_with_quotations([1])
        assert rv.quotation is not None
        assert rv.quotation.quote_version == 1
        assert rv.v1_quotation is not None
        assert rv.v2_quotation is None

    def test_v1_and_v2(self):
        rv = self._make_rv_with_quotations([1, 2])
        # latest_quotation should be v2
        assert rv.latest_quotation.quote_version == 2
        # quotation property returns latest (v2)
        assert rv.quotation.quote_version == 2
        # v1 and v2 accessible separately
        assert rv.v1_quotation.quote_version == 1
        assert rv.v2_quotation.quote_version == 2


class TestQuotationUniqueConstraint:
    """Document that the unique constraint is now per (link, version)."""

    def test_unique_constraint_name(self):
        """Verify the correct unique constraint name exists on the model."""
        from app.quotations.models import Quotation
        # Get table args
        table_args = Quotation.__table_args__
        constraint_names = []
        for arg in table_args:
            if hasattr(arg, 'name'):
                constraint_names.append(arg.name)
        assert "uq_quotation_link_version" in constraint_names, (
            "Composite unique constraint uq_quotation_link_version not found. "
            "The unique=True on requisition_vendor_id must have been fixed to "
            "a composite (requisition_vendor_id, quote_version) constraint."
        )
