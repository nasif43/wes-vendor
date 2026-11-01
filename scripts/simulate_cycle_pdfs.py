"""
Standalone Requisition Lifecycle PDF Simulation Script.

Generates all 4 official PDFs produced during a complete procurement cycle:
1. RFQ / Tender PDF (Stage 1)
2. Supplier Quotation PDF (Stage 2)
3. Work Order / Purchase Order PDF (Stage 3)
4. Accepted Challan / Goods Received Voucher PDF (Stage 4)

Safety guarantees:
- Purely in-memory mock objects.
- Does NOT connect to PostgreSQL or touch any database.
- Does NOT dispatch emails or call Resend API.
- Does NOT upload to S3/R2 storage buckets.
- Saves output files locally to ./generated_cycle_pdfs/
"""

import os
import sys
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from weasyprint import HTML as WP
from app.reports.pdf_service import generate_rfq_pdf
from app.quotations.routes_vendor import _generate_quotation_pdf
from app.work_orders.service import generate_work_order_pdf
from app.utils.number_formatting import (
    format_quantity,
    format_indian_number,
    amount_to_words_bangla,
)

OUTPUT_DIR = PROJECT_ROOT / "generated_cycle_pdfs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Realistic Simulation Data ────────────────────────────────────────────────
# Simulates a procurement of industrial electrical components
REQ_TITLE = "Wener Electrical Line Expansion (Phase 1)"
VENDOR_NAME = "Apex Power & Engineering Ltd"
VENDOR_EMAIL = "procurement@apexpower-bd.com"
ISSUER_NAME = "Central Procurement Division"
QC_INSPECTOR = "Engr. Tanvir Ahmed (QC Officer)"

# Notice: item 1 uses '3E+4' (scientific notation) to demonstrate quantity normalization
ITEMS = [
    {
        "name": "Switch Socket 4-Gang (White Glossy)",
        "description": "Art: 150 GSM Spec, 16A 250V AC Fire-Retardant Polycarbonate",
        "qty": "3E+4",           # 30,000 units
        "price": 100.00,         # BDT 100.00
    },
    {
        "name": "Miniature Circuit Breaker (MCB 32A Double Pole)",
        "description": "Breaking Capacity 6kA, IEC 60898-1 Certified",
        "qty": 10000.0,          # 10,000 units
        "price": 250.00,         # BDT 250.00
    },
    {
        "name": "Distribution SDB Box (12-Way Concealed)",
        "description": "1.2mm CRCA Sheet Steel with Powder Coating",
        "qty": 2000,             # 2,000 units
        "price": 450.00,         # BDT 450.00
    },
]

# Total Calculation:
# Item 1: 30,000 * 100.00 = 30,00,000.00
# Item 2: 10,000 * 250.00 = 25,00,000.00
# Item 3:  2,000 * 450.00 =  9,00,000.00
# Grand Total = BDT 64,00,000.00 (Sixty-Four Lacs Taka Only)
GRAND_TOTAL = sum(float(item["qty"]) * float(item["price"]) for item in ITEMS)


def simulate_stage_1_rfq():
    """Stage 1: Generate Request for Quotation (RFQ) Tender PDF."""
    print("\n[1/4] Generating Stage 1: RFQ / Tender PDF...")
    req_mock = MagicMock(title=REQ_TITLE)
    now_utc = datetime.now(timezone.utc)

    pdf_bytes = generate_rfq_pdf(
        requisition=req_mock,
        supplier_name=VENDOR_NAME,
        items=ITEMS,
        issuer_name=ISSUER_NAME,
        issued_at=now_utc,
    )
    if pdf_bytes:
        out_path = OUTPUT_DIR / "01_RFQ_Tender.pdf"
        out_path.write_bytes(pdf_bytes)
        print(f"  ✓ Saved: {out_path} ({len(pdf_bytes):,} bytes)")
    else:
        print("  ✗ Failed to generate RFQ PDF")


def simulate_stage_2_quotation():
    """Stage 2: Generate Submitted Supplier Quotation PDF."""
    print("\n[2/4] Generating Stage 2: Supplier Quotation PDF...")
    form_data = {
        "price": GRAND_TOTAL,
        "delivery_days": 14,
        "items": ITEMS,
    }
    pdf_bytes = _generate_quotation_pdf(
        form_data=form_data,
        req_title=REQ_TITLE,
        vendor_name=VENDOR_NAME,
    )
    if pdf_bytes:
        out_path = OUTPUT_DIR / "02_Supplier_Quotation.pdf"
        out_path.write_bytes(pdf_bytes)
        print(f"  ✓ Saved: {out_path} ({len(pdf_bytes):,} bytes)")
    else:
        print("  ✗ Failed to generate Quotation PDF")


async def simulate_stage_3_work_order():
    """Stage 3: Generate Official Work Order / Purchase Order PDF."""
    print("\n[3/4] Generating Stage 3: Work Order / Purchase Order PDF...")
    now_utc = datetime.now(timezone.utc)

    wo_mock = MagicMock()
    wo_mock.id = "wo-20261024-e9a1"
    wo_mock.issued_at = now_utc
    wo_mock.requisition = MagicMock(title=REQ_TITLE)
    wo_mock.vendor = MagicMock(company_name=VENDOR_NAME, contact_email=VENDOR_EMAIL)
    wo_mock.issuer = MagicMock(full_name=ISSUER_NAME)
    wo_mock._quotation_data = {
        "price": GRAND_TOTAL,
        "delivery_days": 14,
        "items": ITEMS,
    }

    pdf_bytes = await generate_work_order_pdf(wo_mock, letterhead_url=None)
    if pdf_bytes:
        out_path = OUTPUT_DIR / "03_Work_Order_Purchase_Order.pdf"
        out_path.write_bytes(pdf_bytes)
        print(f"  ✓ Saved: {out_path} ({len(pdf_bytes):,} bytes)")
    else:
        print("  ✗ Failed to generate Work Order PDF")


def simulate_stage_4_accepted_challan():
    """Stage 4: Generate Accepted Challan / Goods Received Voucher PDF."""
    print("\n[4/4] Generating Stage 4: Accepted Challan (গৃহীত চালান) PDF...")
    now_utc = datetime.now(timezone.utc)
    try:
        dhaka_tz = ZoneInfo("Asia/Dhaka")
        dhaka_time = now_utc.astimezone(dhaka_tz)
        challan_date = dhaka_time.strftime("%B %d, %Y")
        challan_time = dhaka_time.strftime("%I:%M %p")
    except Exception:
        challan_date = now_utc.strftime("%B %d, %Y")
        challan_time = now_utc.strftime("%I:%M %p")

    final_challan_number = "CH-20261024-8841"
    total_rejected = 0.0

    rows_html = ""
    for item in ITEMS:
        qty = float(item["qty"])
        price = float(item["price"])
        line_total = qty * price
        ordered_display = format_quantity(qty)
        received_display = format_quantity(qty)   # 100% accepted in QC
        rejected_display = format_quantity(0)
        price_display = format_indian_number(price)
        total_display = format_indian_number(line_total)

        rows_html += (
            f"<tr>"
            f"<td style='border:1px solid #ccc;padding:6px'><b>{item['name']}</b><br><small style='color:#666'>{item['description']}</small></td>"
            f"<td style='border:1px solid #ccc;padding:6px;text-align:center'>{ordered_display}</td>"
            f"<td style='border:1px solid #ccc;padding:6px;text-align:center;color:#16a34a;font-weight:600'>{received_display}</td>"
            f"<td style='border:1px solid #ccc;padding:6px;text-align:center;color:#dc2626'>{rejected_display}</td>"
            f"<td style='border:1px solid #ccc;padding:6px;text-align:right;font-family:monospace'>BDT {price_display}</td>"
            f"<td style='border:1px solid #ccc;padding:6px;text-align:right;font-family:monospace;font-weight:700'>BDT {total_display}</td>"
            f"<td style='border:1px solid #ccc;padding:6px;font-size:11px;color:#16a34a'>QC Passed ✓</td>"
            f"</tr>"
        )

    html_content = f"""
    <!DOCTYPE html><html>
    <head><meta charset="utf-8">
    <style>
    @page {{ margin: 40px; }}
    body {{ font-family: 'Noto Sans Bengali', 'SolaimanLipi', 'Helvetica Neue', Arial, sans-serif; color: #1a1a1a; line-height: 1.5; }}
    .wrap {{ background: rgba(255,255,255,0.95); padding: 32px; border-radius: 8px; }}
    h1 {{ font-size: 22px; border-bottom: 2px solid #1a1a1a; padding-bottom: 8px; margin-bottom: 16px; text-align: center; color: #0f172a; }}
    table.meta {{ width: 100%; font-size: 13px; margin-bottom: 16px; }}
    table.meta td {{ padding: 3px 0; }}
    table.items {{ border-collapse: collapse; width: 100%; font-size: 12px; margin-top: 12px; }}
    table.items th {{ border: 1px solid #ccc; padding: 7px; background: #e2e8f0; font-size: 11px; }}
    table.items td {{ border: 1px solid #ccc; padding: 6px; }}
    table.items tfoot td {{ font-weight: 700; background: #f8fafc; }}
    .footer {{ margin-top: 28px; font-size: 11px; color: #475569; text-align: center; border-top: 1px solid #cbd5e1; padding-top: 12px; }}
    </style></head>
    <body><div class="wrap">
    <p style="font-size:11px;color:#666;margin-bottom:4px">Challan No: {final_challan_number} | Date: {challan_date}</p>
    <h1>Accepted Challan (গৃহীত চালান)</h1>
    <table class="meta">
    <tr><td><b>Requisition:</b> {REQ_TITLE}</td><td><b>Supplier:</b> {VENDOR_NAME}</td></tr>
    <tr><td><b>Received by:</b> {QC_INSPECTOR}</td><td><b>Challan No:</b> {final_challan_number}</td></tr>
    </table>
    <table class="items">
    <thead><tr><th>Item</th><th style="text-align:center">Ordered</th><th style="color:#16a34a;text-align:center">Received</th><th style="color:#dc2626;text-align:center">Rejected</th><th style="text-align:right">Unit Price</th><th style="text-align:right">Line Total</th><th>Notes</th></tr></thead>
    <tbody>{rows_html}</tbody>
    <tfoot>
    <tr><td colspan="5" style="text-align:right;border:1px solid #ccc;padding:8px;font-weight:700">TOTAL PAYABLE:</td>
    <td style="border:1px solid #ccc;padding:8px;text-align:right;font-family:monospace;font-weight:700">BDT {format_indian_number(GRAND_TOTAL)}</td>
    <td style="border:1px solid #ccc;padding:8px"></td></tr>
    <tr><td colspan="7" style="border:1px solid #ccc;padding:8px;background:#f8fafc;font-size:12px;color:#334155">
    <b>In Words:</b> {amount_to_words_bangla(GRAND_TOTAL)}</td></tr>
    </tfoot>
    </table>
    <div class="footer">
        <p>Accepted by: <strong>{QC_INSPECTOR}</strong> &nbsp;|&nbsp; Date: <strong>{challan_date}</strong> &nbsp;|&nbsp; Time: <strong>{challan_time} BST</strong></p>
        <p style="font-size:10px;color:#94a3b8;margin-top:4px;">This Accepted Challan is system-generated based on goods received and QC-accepted quantities only.<br>
        Rejected items ({format_quantity(total_rejected)} units) are excluded from payment.</p>
    </div>
    </div></body></html>
    """

    pdf_bytes = WP(string=html_content).write_pdf()
    if pdf_bytes:
        out_path = OUTPUT_DIR / "04_Accepted_Challan.pdf"
        out_path.write_bytes(pdf_bytes)
        print(f"  ✓ Saved: {out_path} ({len(pdf_bytes):,} bytes)")
    else:
        print("  ✗ Failed to generate Accepted Challan PDF")


async def main():
    print("=" * 70)
    print("SIMULATING REQUISITION CYCLE PDF GENERATION")
    print(f"Target Output Folder: {OUTPUT_DIR}")
    print("=" * 70)

    simulate_stage_1_rfq()
    simulate_stage_2_quotation()
    await simulate_stage_3_work_order()
    simulate_stage_4_accepted_challan()

    print("\n" + "=" * 70)
    print("CYCLE COMPLETE: 4 OF 4 PDFS GENERATED SUCCESSFULLY")
    print("=" * 70)
    for p in sorted(OUTPUT_DIR.glob("*.pdf")):
        print(f"  • {p.name} ({p.stat().st_size:,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
