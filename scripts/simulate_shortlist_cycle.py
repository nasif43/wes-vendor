"""
Simulation of Item-Level Shortlisting and Revision Cycle PDFs.

Demonstrates the exact behavior when a supplier who initially quoted on 3 items
is shortlisted to supply ONLY 1 item:
- Stage 1: Round 1 (v1) RFQ Tender for all 3 items.
- Stage 2: Round 1 (v1) Supplier Quotation for all 3 items (BDT 64,00,000).
- Stage 3: Round 2 (v2) Revised RFQ Tender sent to supplier containing ONLY the 1 shortlisted item.
- Stage 4: Round 2 (v2) Supplier Revised Quotation submitting rates ONLY for that 1 item (BDT 24,00,000).
- Stage 5: Official Work Order awarded strictly for that 1 shortlisted item.
- Stage 6: Accepted Challan (গৃহীত চালান) billing strictly for that 1 shortlisted item.

Zero database modifications. Zero emails dispatched. Purely local preview files.
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

REQ_TITLE = "Wener Electrical Line Expansion (Phase 1)"
VENDOR_NAME = "Apex Power & Engineering Ltd"
VENDOR_EMAIL = "procurement@apexpower-bd.com"
ISSUER_NAME = "Central Procurement Division"
QC_INSPECTOR = "Engr. Tanvir Ahmed (QC Officer)"

# Full 3 items for initial round (v1)
FULL_ITEMS = [
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

V1_GRAND_TOTAL = sum(float(item["qty"]) * float(item["price"]) for item in FULL_ITEMS)
# 30,000*100 + 10,000*250 + 2,000*450 = 30,00,000 + 25,00,000 + 9,00,000 = 64,00,000

# Shortlisted item for Apex Power: ONLY Item 2 (MCB 32A)
# In revision round (v2), the supplier negotiates unit price down from 250 to 240 BDT
SHORTLISTED_ITEMS_RFQ = [
    {
        "name": "Miniature Circuit Breaker (MCB 32A Double Pole)",
        "description": "Breaking Capacity 6kA, IEC 60898-1 Certified",
        "shortlisted_qty": 10000.0,
    }
]

SHORTLISTED_ITEMS_QUOTE = [
    {
        "name": "Miniature Circuit Breaker (MCB 32A Double Pole)",
        "description": "Breaking Capacity 6kA, IEC 60898-1 Certified",
        "qty": 10000.0,
        "price": 240.00,  # Revised negotiated price: BDT 240
    }
]

V2_GRAND_TOTAL = 10000.0 * 240.00  # BDT 24,00,000.00


def gen_stage_1_rfq_v1():
    """Round 1 (v1): RFQ with all 3 items sent to vendors."""
    print("\n[1/6] Generating Stage 1: Round 1 (v1) Full RFQ (3 Items)...")
    req_mock = MagicMock(title=REQ_TITLE)
    now_utc = datetime.now(timezone.utc)
    pdf_bytes = generate_rfq_pdf(
        requisition=req_mock,
        supplier_name=VENDOR_NAME,
        items=FULL_ITEMS,
        issuer_name=ISSUER_NAME,
        issued_at=now_utc,
    )
    out_path = OUTPUT_DIR / "01_RFQ_Round1_Full_3_Items.pdf"
    out_path.write_bytes(pdf_bytes)
    print(f"  ✓ Saved: {out_path.name} ({len(pdf_bytes):,} bytes)")


def gen_stage_2_quote_v1():
    """Round 1 (v1): Supplier Quotation covering all 3 items."""
    print("\n[2/6] Generating Stage 2: Round 1 (v1) Supplier Quotation (3 Items)...")
    form_data = {
        "price": V1_GRAND_TOTAL,
        "delivery_days": 14,
        "items": FULL_ITEMS,
    }
    pdf_bytes = _generate_quotation_pdf(
        form_data=form_data,
        req_title=REQ_TITLE,
        vendor_name=VENDOR_NAME,
    )
    out_path = OUTPUT_DIR / "02_Quotation_Round1_Full_3_Items.pdf"
    out_path.write_bytes(pdf_bytes)
    print(f"  ✓ Saved: {out_path.name} ({len(pdf_bytes):,} bytes)")


def gen_stage_3_rfq_v2_shortlist():
    """Round 2 (v2): Revised RFQ sent to Apex Power for ONLY 1 shortlisted item."""
    print("\n[3/6] Generating Stage 3: Round 2 (v2) Revised RFQ (ONLY Shortlisted Item)...")
    req_mock = MagicMock(title=f"{REQ_TITLE} (Revision Round 2)")
    now_utc = datetime.now(timezone.utc)
    pdf_bytes = generate_rfq_pdf(
        requisition=req_mock,
        supplier_name=VENDOR_NAME,
        items=SHORTLISTED_ITEMS_RFQ,
        issuer_name=ISSUER_NAME,
        issued_at=now_utc,
    )
    out_path = OUTPUT_DIR / "03_RFQ_Round2_Shortlisted_1_Item_Only.pdf"
    out_path.write_bytes(pdf_bytes)
    print(f"  ✓ Saved: {out_path.name} ({len(pdf_bytes):,} bytes)")


def gen_stage_4_quote_v2_shortlist():
    """Round 2 (v2): Supplier Revised Quotation for ONLY 1 shortlisted item."""
    print("\n[4/6] Generating Stage 4: Round 2 (v2) Revised Quotation (1 Item Only)...")
    form_data = {
        "price": V2_GRAND_TOTAL,
        "delivery_days": 10,
        "items": SHORTLISTED_ITEMS_QUOTE,
    }
    pdf_bytes = _generate_quotation_pdf(
        form_data=form_data,
        req_title=f"{REQ_TITLE} (Round 2)",
        vendor_name=VENDOR_NAME,
    )
    out_path = OUTPUT_DIR / "04_Quotation_Round2_Shortlisted_1_Item_Only.pdf"
    out_path.write_bytes(pdf_bytes)
    print(f"  ✓ Saved: {out_path.name} ({len(pdf_bytes):,} bytes)")


async def gen_stage_5_work_order():
    """Round 2 (v2): Awarded Work Order strictly for the 1 shortlisted item."""
    print("\n[5/6] Generating Stage 5: Official Work Order (Awarded 1 Item Only)...")
    now_utc = datetime.now(timezone.utc)

    wo_mock = MagicMock()
    wo_mock.id = "WO-20261024-V2-01"
    wo_mock.issued_at = now_utc
    wo_mock.requisition = MagicMock(title=REQ_TITLE)
    wo_mock.vendor = MagicMock(company_name=VENDOR_NAME, contact_email=VENDOR_EMAIL)
    wo_mock.issuer = MagicMock(full_name=ISSUER_NAME)
    wo_mock._quotation_data = {
        "price": V2_GRAND_TOTAL,
        "delivery_days": 10,
        "items": SHORTLISTED_ITEMS_QUOTE,
    }

    pdf_bytes = await generate_work_order_pdf(wo_mock, letterhead_url=None)
    out_path = OUTPUT_DIR / "05_Work_Order_Awarded_1_Item_Only.pdf"
    out_path.write_bytes(pdf_bytes)
    print(f"  ✓ Saved: {out_path.name} ({len(pdf_bytes):,} bytes)")


def gen_stage_6_accepted_challan():
    """Round 2 (v2): Accepted Challan (গৃহীত চালান) strictly for the 1 shortlisted item."""
    print("\n[6/6] Generating Stage 6: Accepted Challan (গৃহীত চালান - 1 Item Only)...")
    now_utc = datetime.now(timezone.utc)
    try:
        dhaka_tz = ZoneInfo("Asia/Dhaka")
        dhaka_time = now_utc.astimezone(dhaka_tz)
        challan_date = dhaka_time.strftime("%B %d, %Y")
        challan_time = dhaka_time.strftime("%I:%M %p")
    except Exception:
        challan_date = now_utc.strftime("%B %d, %Y")
        challan_time = now_utc.strftime("%I:%M %p")

    final_challan_number = "CH-20261024-9120"
    total_rejected = 0.0

    rows_html = ""
    for item in SHORTLISTED_ITEMS_QUOTE:
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
    <td style="border:1px solid #ccc;padding:8px;text-align:right;font-family:monospace;font-weight:700">BDT {format_indian_number(V2_GRAND_TOTAL)}</td>
    <td style="border:1px solid #ccc;padding:8px"></td></tr>
    <tr><td colspan="7" style="border:1px solid #ccc;padding:8px;background:#f8fafc;font-size:12px;color:#334155">
    <b>In Words:</b> {amount_to_words_bangla(V2_GRAND_TOTAL)}</td></tr>
    </tfoot>
    </table>
    <div class="footer">
        <p>Accepted by: <strong>{QC_INSPECTOR}</strong> &nbsp;|&nbsp; Date: <strong>{challan_date}</strong> &nbsp;|&nbsp; Time: <strong>{challan_time} BST</strong></p>
        <p style="font-size:10px;color:#94a3b8;margin-top:4px;">This Accepted Challan is system-generated based on goods received and QC-accepted quantities only.<br>
        Billing strictly corresponds to the shortlisted & awarded scope ({format_quantity(10000)} units).</p>
    </div>
    </div></body></html>
    """
    pdf_bytes = WP(string=html_content).write_pdf()
    out_path = OUTPUT_DIR / "06_Accepted_Challan_1_Item_Only.pdf"
    out_path.write_bytes(pdf_bytes)
    print(f"  ✓ Saved: {out_path.name} ({len(pdf_bytes):,} bytes)")


async def main():
    print("=" * 75)
    print("SIMULATING SHORTLIST ITEM-SPLIT PROCUREMENT CYCLE")
    print(f"Output Directory: {OUTPUT_DIR}")
    print("=" * 75)

    # Initial Round v1 (3 items)
    gen_stage_1_rfq_v1()
    gen_stage_2_quote_v1()

    # Shortlist & Revision Round v2 (1 item)
    gen_stage_3_rfq_v2_shortlist()
    gen_stage_4_quote_v2_shortlist()
    await gen_stage_5_work_order()
    gen_stage_6_accepted_challan()

    print("\n" + "=" * 75)
    print("SHORTLIST SIMULATION COMPLETE: ALL 6 COMPARISON PDFS GENERATED")
    print("=" * 75)
    for p in sorted(OUTPUT_DIR.glob("*.pdf")):
        print(f"  • {p.name} ({p.stat().st_size:,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
