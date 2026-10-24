"""
Unit tests for South Asian / Indian comma formatting, quantity normalization,
and Bangladeshi amount-in-words translation.
"""
from decimal import Decimal
import pytest

from app.utils.number_formatting import (
    amount_to_words_bangla,
    format_indian_number,
    format_quantity,
)


class TestFormatQuantity:
    def test_scientific_notation_expansion(self):
        assert format_quantity("3E+4") == "30,000"
        assert format_quantity("3e+04") == "30,000"
        assert format_quantity("1.5e3") == "1,500"
        assert format_quantity(Decimal("3E+4")) == "30,000"

    def test_integers_and_floats(self):
        assert format_quantity(30000) == "30,000"
        assert format_quantity(30000.0) == "30,000"
        assert format_quantity("30000") == "30,000"
        assert format_quantity(10000.00) == "10,000"
        assert format_quantity(1000000) == "1,000,000"

    def test_decimals_with_fractions(self):
        assert format_quantity(10.5) == "10.5"
        assert format_quantity("1234.56") == "1,234.56"
        assert format_quantity(0.25) == "0.25"

    def test_edge_cases(self):
        assert format_quantity(0) == "0"
        assert format_quantity(0.0) == "0"
        assert format_quantity("0.00") == "0"
        assert format_quantity(None) == "0"
        assert format_quantity("") == "0"


class TestFormatIndianNumber:
    def test_standard_indian_grouping(self):
        assert format_indian_number(0) == "0.00"
        assert format_indian_number(5) == "5.00"
        assert format_indian_number(100) == "100.00"
        assert format_indian_number(1000) == "1,000.00"
        assert format_indian_number(10000) == "10,000.00"
        assert format_indian_number(100000) == "1,00,000.00"
        assert format_indian_number(1000000) == "10,00,000.00"
        assert format_indian_number(10000000) == "1,00,00,000.00"
        assert format_indian_number(1234567.89) == "12,34,567.89"

    def test_negative_values(self):
        assert format_indian_number(-100000) == "-1,00,000.00"
        assert format_indian_number("-50000.50") == "-50,000.50"

    def test_custom_decimals(self):
        assert format_indian_number(100000, decimals=0) == "1,00,000"
        assert format_indian_number(1234567.891, decimals=3) == "12,34,567.891"

    def test_edge_cases(self):
        assert format_indian_number(None) == "0.00"
        assert format_indian_number("") == "0.00"


class TestAmountToWordsBangla:
    def test_zero_and_small_numbers(self):
        assert amount_to_words_bangla(0) == "Zero Taka Only"
        assert amount_to_words_bangla(1) == "One Taka Only"
        assert amount_to_words_bangla(50) == "Fifty Taka Only"
        assert amount_to_words_bangla(100) == "One Hundred Taka Only"

    def test_thousands(self):
        assert amount_to_words_bangla(1000) == "One Thousand Taka Only"
        assert amount_to_words_bangla(30000) == "Thirty Thousand Taka Only"
        assert amount_to_words_bangla("3E+4") == "Thirty Thousand Taka Only"

    def test_lacs_and_crores(self):
        # 1 Lac
        assert amount_to_words_bangla(100000) == "One Lac Taka Only"
        # Plural Lacs
        assert amount_to_words_bangla(200000) == "Two Lacs Taka Only"
        assert amount_to_words_bangla(1000000) == "Ten Lacs Taka Only"
        # 1 Crore
        assert amount_to_words_bangla(10000000) == "One Crore Taka Only"
        # Plural Crores
        assert amount_to_words_bangla(20000000) == "Two Crores Taka Only"
        assert amount_to_words_bangla(25000000) == "Two Crores Fifty Lacs Taka Only"
        assert amount_to_words_bangla(100000000) == "Ten Crores Taka Only"
        assert amount_to_words_bangla(2500000000) == "Two Hundred Fifty Crores Taka Only"

    def test_complex_amounts_with_poisha(self):
        assert (
            amount_to_words_bangla(1234567.89)
            == "Twelve Lacs Thirty-Four Thousand Five Hundred Sixty-Seven Taka and Eighty-Nine Poisha Only"
        )
        assert amount_to_words_bangla(0.75) == "Seventy-Five Poisha Only"
        assert amount_to_words_bangla(100.50) == "One Hundred Taka and Fifty Poisha Only"

    def test_negative_amounts(self):
        assert amount_to_words_bangla(-100000) == "Minus One Lac Taka Only"

    def test_edge_cases(self):
        assert amount_to_words_bangla(None) == "Zero Taka Only"
        assert amount_to_words_bangla("") == "Zero Taka Only"


class TestPDFFormatting:
    def test_rfq_pdf_quantity_formatting(self):
        from unittest.mock import MagicMock, patch
        import app.reports.pdf_service as rfq_mod

        captured_html = []
        def mock_html(string=None):
            captured_html.append(string)
            m = MagicMock()
            m.write_pdf.return_value = b"%PDF-1.4 mock"
            return m

        with patch("app.reports.pdf_service.HTML", side_effect=mock_html):
            req = MagicMock(title="Wener Product Price List", quantity="3E+4")
            items = [{"name": "Art Paper", "description": "150 GSM", "qty": "3E+4"}]
            rfq_mod.generate_rfq_pdf(req, "Apex Supplies Ltd", items)
            assert len(captured_html) > 0
            html = captured_html[-1]
            assert "30,000" in html
            assert "3E+4" not in html

    @pytest.mark.asyncio
    async def test_work_order_pdf_formatting_and_words(self):
        from unittest.mock import MagicMock, patch
        from datetime import datetime
        import app.work_orders.service as wo_mod

        captured_html = []
        def mock_html(string=None):
            captured_html.append(string)
            m = MagicMock()
            m.write_pdf.return_value = b"%PDF-1.4 mock"
            return m

        with patch("weasyprint.HTML", side_effect=mock_html):
            wo = MagicMock()
            wo.id = "abcdef12-3456-7890-abcd-ef1234567890"
            wo.issued_at = datetime.now()
            wo.requisition = MagicMock(title="Switch Socket Order")
            wo.vendor = MagicMock(company_name="Apex Supplies Ltd", contact_email="apex@example.com")
            wo.issuer = MagicMock(full_name="Procurement Officer")
            wo._quotation_data = {
                "items": [
                    {"name": "Switch Socket", "description": "White 4-gang", "qty": "3E+4", "price": 5.50}
                ]
            }
            await wo_mod.generate_work_order_pdf(wo, None)
            assert len(captured_html) > 0
            html = captured_html[-1]
            assert "30,000" in html
            assert "3E+4" not in html
            assert "1,65,000.00" in html
            assert "One Lac Sixty-Five Thousand Taka Only" in html

    def test_quotation_pdf_formatting_and_words(self):
        from unittest.mock import MagicMock, patch
        import app.quotations.routes_vendor as q_mod

        captured_html = []
        def mock_html(string=None):
            captured_html.append(string)
            m = MagicMock()
            m.write_pdf.return_value = b"%PDF-1.4 mock"
            return m

        with patch("weasyprint.HTML", side_effect=mock_html):
            form_data = {
                "price": 165000.00,
                "delivery_days": 7,
                "items": [
                    {"name": "Switch Socket", "description": "White 4-gang", "qty": "3E+4", "price": 5.50}
                ],
            }
            q_mod._generate_quotation_pdf(form_data, "Switch Socket Order", "Apex Supplies Ltd")
            assert len(captured_html) > 0
            html = captured_html[-1]
            assert "30,000" in html
            assert "3E+4" not in html
            assert "1,65,000.00" in html
            assert "One Lac Sixty-Five Thousand Taka Only" in html
