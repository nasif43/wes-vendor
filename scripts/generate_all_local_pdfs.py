"""
Generate all system PDFs locally on device:
1. RFQ / Tender Invitation (Round 1 - Multi-item)
2. Revised RFQ / Negotiation (Round 2 - Shortlisted item)
3. Supplier Quotation Submission PDF
4. Official Work Order / Purchase Order PDF (Standard Clean Corporate Layout)
5. Official Work Order / Purchase Order PDF (With Company Letterhead Banner)
6. Accepted Challan (গৃহীত চালান) / QC Receiving Voucher PDF
7. PP Virgin Bulk Raw Material Work Order PDF
8. Requisition Worksheet A4 Printable Sheet PDF
9. Executive Quotation Comparison & Evaluation Matrix PDF

All generated PDFs are written to:
- ./local_generated_pdfs/
- ./generated_cycle_pdfs/
"""

import os
import sys
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from weasyprint import HTML
from app.reports.pdf_service import generate_rfq_pdf
from app.quotations.routes_vendor import _generate_quotation_pdf
from app.work_orders.service import generate_work_order_pdf
from app.utils.number_formatting import (
    amount_to_words_bangla,
    format_indian_number,
    format_quantity,
)

OUTPUT_DIR = PROJECT_ROOT / "local_generated_pdfs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CYCLE_DIR = PROJECT_ROOT / "generated_cycle_pdfs"
CYCLE_DIR.mkdir(parents=True, exist_ok=True)

# ── 1. REALISTIC DIES & TOOLING DATA (Matches user's physical PO photo) ─────────
REQ_CODE = "04A7E919"
REF_NO = f"WO-{REQ_CODE}"
PO_DATE_STR = "October 26, 2026"
QUOTATION_DATE_STR = "October 24, 2026"

VENDOR_NAME = "Ashraf Lathe Works"
VENDOR_ADDRESS = "21/1A, Mirhazir Bagh, Dhaka-1204"
VENDOR_CONTACT = "Md. Ashraf Hossain (Proprietor)"
VENDOR_PHONE = "+880 1711-234567"
VENDOR_EMAIL = "ashraf.lathe@gmail.com"

ISSUER_NAME = "Omar Faruk Shohan (Executive Procurement)"
CHECKED_BY = "Mizanur Rahman Sujon (Dep. Management Procurement)"
VERIFIED_BY = "Md. Mahfuzur Rahman (General Manager Factory)"
APPROVED_BY = "Nazir Ahmed (Chairman WENER GROUP)"

ITEMS_DIES = [
    {
        "name": "BLDC Circle Patting Die (Complete Set)",
        "description": "Bearing Metal Diameter 132mm, Tooling Grade",
        "qty": 1,
        "unit": "Set",
        "price": 40000.0,
    },
    {
        "name": "BLDC Armature Cutting Die",
        "description": "D2 iron (18 shots diameter 132mm & thickness 28mm)",
        "qty": 1,
        "unit": "Set",
        "price": 130000.0,
    },
    {
        "name": "Armature Ripit Die (Complete Set)",
        "description": "Mild Steel Precision Finish",
        "qty": 1,
        "unit": "Set",
        "price": 65000.0,
    },
]

TOTAL_DIES = sum(i["qty"] * i["price"] for i in ITEMS_DIES)


# ── 2. PP VIRGIN DATA (Matches user's PP Virgin requisition) ────────────────────
ITEMS_PP_VIRGIN = [
    {
        "name": "PP Virgin Polymer Granules (Grade HP-550J)",
        "description": "Injection Molding Grade, Melt Flow Index: 25 g/10min, Tensile Strength >= 35 MPa, Natural White Translucent Pellets",
        "qty": 5000,
        "unit": "Bags",
        "price": 3200.0,  # 3,200 BDT per 25kg bag
    },
    {
        "name": "White Masterbatch (Titanium Dioxide 70% Concentration)",
        "description": "High Dispersibility, Food-Contact Approved Grade, 25kg moisture-proof bag",
        "qty": 200,
        "unit": "Bags",
        "price": 6500.0,  # 6,500 BDT per bag
    },
]
TOTAL_PP_VIRGIN = sum(i["qty"] * i["price"] for i in ITEMS_PP_VIRGIN)


def save_pdf(filename: str, pdf_bytes: bytes, desc: str):
    p1 = OUTPUT_DIR / filename
    p1.write_bytes(pdf_bytes)
    p2 = CYCLE_DIR / filename
    p2.write_bytes(pdf_bytes)
    print(f"  ✓ {desc}\n    -> {p1} ({len(pdf_bytes):,} bytes)")


def generate_01_rfq_round1():
    """1. Request for Quotation (RFQ / Tender Invitation) - Round 1"""
    req_mock = MagicMock(
        id=REQ_CODE,
        title="Dies & Tooling for BLDC Motor Production",
        unit="Set",
    )
    now_utc = datetime(2026, 10, 20, 10, 30, tzinfo=timezone.utc)
    pdf_bytes = generate_rfq_pdf(
        requisition=req_mock,
        supplier_name=VENDOR_NAME,
        items=ITEMS_DIES,
        issuer_name=ISSUER_NAME,
        issued_at=now_utc,
    )
    if pdf_bytes:
        save_pdf("01_RFQ_Tender_Round1_MultiItem.pdf", pdf_bytes, "01. Stage 1: RFQ Tender Invitation (Round 1)")


def generate_02_rfq_round2():
    """2. Revised RFQ / Tender (Negotiation Round 2)"""
    req_mock = MagicMock(
        id=REQ_CODE,
        title="Dies & Tooling for BLDC Motor Production (Negotiation Round 2)",
        unit="Set",
    )
    now_utc = datetime(2026, 10, 23, 14, 15, tzinfo=timezone.utc)
    # Only shortlisted item #2
    shortlisted_items = [
        {
            "name": "BLDC Armature Cutting Die",
            "description": "D2 iron (18 shots diameter 132mm & thickness 28mm) - Target delivery: 25 days",
            "qty": 1,
            "unit": "Set",
        }
    ]
    pdf_bytes = generate_rfq_pdf(
        requisition=req_mock,
        supplier_name=VENDOR_NAME,
        items=shortlisted_items,
        issuer_name=ISSUER_NAME,
        issued_at=now_utc,
    )
    if pdf_bytes:
        save_pdf("02_RFQ_Negotiation_Round2_Shortlisted.pdf", pdf_bytes, "02. Stage 1B: Revised RFQ Negotiation (Round 2)")


def generate_03_supplier_quotation():
    """3. Supplier Quotation Submission PDF"""
    form_data = {
        "price": TOTAL_DIES,
        "delivery_days": 30,
        "payment_terms": "50% Advance required upon order confirmation and rest 50% upon delivery.",
        "warranty": "Free services for first 2 months.",
        "notes": "Rate excluding VAT & TAX. Delivery to Mirer Bazar, Pubail, Gazipur.",
        "items": ITEMS_DIES,
    }
    pdf_bytes = _generate_quotation_pdf(
        form_data=form_data,
        req_title="Dies & Tooling for BLDC Motor Production",
        vendor_name=VENDOR_NAME,
    )
    if pdf_bytes:
        save_pdf("03_Supplier_Quotation_Submission.pdf", pdf_bytes, "03. Stage 2: Supplier Submitted Quotation")


async def generate_04_work_order_standard():
    """4. Official Purchase Order / Work Order (Standard Clean Corporate Layout)"""
    wo_mock = MagicMock()
    wo_mock.id = "4d4f563a-1670-475b-9d12-99d05e0e3faf"
    wo_mock.reference_code = REF_NO
    wo_mock.issued_at = datetime(2026, 10, 26, 11, 0, tzinfo=timezone.utc)
    
    req_mock = MagicMock(
        id=REQ_CODE,
        title="Dies & Tooling for BLDC Motor Production",
        unit="Set",
    )
    wo_mock.requisition = req_mock
    
    vendor_mock = MagicMock(
        company_name=VENDOR_NAME,
        contact_person=VENDOR_CONTACT,
        phone=VENDOR_PHONE,
        contact_email=VENDOR_EMAIL,
    )
    wo_mock.vendor = vendor_mock
    
    wo_mock._quotation_data = {
        "price": TOTAL_DIES,
        "delivery_days": 30,
        "payment_terms": "50% Advance required upon order confirmation and rest 50% upon delivery.",
        "warranty": "Free services for first 2 months.",
        "notes": "Rate excluding VAT & TAX.",
        "items": ITEMS_DIES,
    }
    wo_mock.requisition_vendor = None
    
    pdf_bytes = await generate_work_order_pdf(wo_mock, letterhead_url=None)
    if pdf_bytes:
        save_pdf("04_Purchase_Order_Work_Order_Standard.pdf", pdf_bytes, "04. Stage 3: Official Purchase Order / Work Order (Clean Corporate)")


async def generate_05_work_order_with_letterhead():
    """5. Purchase Order / Work Order (With Company Letterhead Header)"""
    # Create an inline letterhead HTML/SVG data uri
    svg_lh = """
    <svg xmlns="http://www.w3.org/2000/svg" width="800" height="1132" viewBox="0 0 800 1132">
        <rect width="800" height="1132" fill="#ffffff"/>
        <!-- Top corporate bar -->
        <rect width="800" height="8" fill="#1e3a8a"/>
        <rect y="8" width="800" height="3" fill="#3b82f6"/>
        <!-- Watermark in center -->
        <text x="400" y="600" font-family="Helvetica, Arial, sans-serif" font-size="70" font-weight="900" fill="#f1f5f9" text-anchor="middle" transform="rotate(-30 400 600)" letter-spacing="10">WENER GROUP</text>
        <!-- Bottom bar -->
        <rect y="1120" width="800" height="12" fill="#1e3a8a"/>
    </svg>
    """.strip()
    import base64
    b64_svg = base64.b64encode(svg_lh.encode("utf-8")).decode("ascii")
    data_uri = f"data:image/svg+xml;base64,{b64_svg}"

    wo_mock = MagicMock()
    wo_mock.id = "4d4f563a-1670-475b-9d12-99d05e0e3faf"
    wo_mock.reference_code = REF_NO
    wo_mock.issued_at = datetime(2026, 10, 26, 11, 0, tzinfo=timezone.utc)
    
    req_mock = MagicMock(
        id=REQ_CODE,
        title="Dies & Tooling for BLDC Motor Production",
        unit="Set",
    )
    wo_mock.requisition = req_mock
    
    vendor_mock = MagicMock(
        company_name=VENDOR_NAME,
        contact_person=VENDOR_CONTACT,
        phone=VENDOR_PHONE,
        contact_email=VENDOR_EMAIL,
    )
    wo_mock.vendor = vendor_mock
    
    wo_mock._quotation_data = {
        "price": TOTAL_DIES,
        "delivery_days": 30,
        "payment_terms": "50% Advance required upon order confirmation and rest 50% upon delivery.",
        "warranty": "Free services for first 2 months.",
        "notes": "Rate excluding VAT & TAX.",
        "items": ITEMS_DIES,
    }
    wo_mock.requisition_vendor = None

    pdf_bytes = await generate_work_order_pdf(wo_mock, letterhead_url=data_uri)
    if pdf_bytes:
        save_pdf("05_Purchase_Order_Work_Order_With_Letterhead.pdf", pdf_bytes, "05. Stage 3B: Purchase Order With Letterhead & Watermark")


def generate_06_accepted_challan():
    """6. Accepted Challan (গৃহীত চালান) / QC Receiving Voucher PDF"""
    now_utc = datetime(2026, 11, 2, 8, 45, tzinfo=timezone.utc)
    dhaka_tz = ZoneInfo("Asia/Dhaka")
    dhaka_time = now_utc.astimezone(dhaka_tz)
    challan_date = dhaka_time.strftime("%B %d, %Y")
    challan_time = dhaka_time.strftime("%I:%M %p")

    final_challan_number = "CH-2026-0842"
    total_rejected = 0.0

    rows_html = ""
    for item in ITEMS_DIES:
        qty = float(item["qty"])
        price = float(item["price"])
        line_total = qty * price
        ordered_display = f"{format_quantity(qty)} {item['unit']}"
        received_display = f"{format_quantity(qty)} {item['unit']}"
        rejected_display = "0"
        price_display = format_indian_number(price)
        total_display = format_indian_number(line_total)

        rows_html += (
            f"<tr>"
            f"<td style='border:1px solid #334155;padding:7px 8px;'><b>{item['name']}</b><br><small style='color:#555;'>{item['description']}</small></td>"
            f"<td style='border:1px solid #334155;padding:7px 8px;text-align:center;'>{ordered_display}</td>"
            f"<td style='border:1px solid #334155;padding:7px 8px;text-align:center;color:#16a34a;font-weight:700;'>{received_display}</td>"
            f"<td style='border:1px solid #334155;padding:7px 8px;text-align:center;color:#dc2626;'>{rejected_display}</td>"
            f"<td style='border:1px solid #334155;padding:7px 8px;text-align:right;font-family:monospace;'>BDT {price_display}</td>"
            f"<td style='border:1px solid #334155;padding:7px 8px;text-align:right;font-family:monospace;font-weight:700;'>BDT {total_display}</td>"
            f"<td style='border:1px solid #334155;padding:7px 8px;font-size:11px;color:#16a34a;font-weight:600;'>QC Passed ✓ Tolerance ±0.02mm verified</td>"
            f"</tr>"
        )

    html_content = f"""
    <!DOCTYPE html><html>
    <head><meta charset="utf-8">
    <style>
    @page {{ size: A4; margin: 35px 40px; }}
    body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #1a1a1a; line-height: 1.5; font-size: 12px; }}
    .wrap {{ padding: 20px; }}
    h1 {{ font-size: 20px; border-bottom: 2px solid #0f172a; padding-bottom: 8px; margin-bottom: 14px; text-align: center; color: #0f172a; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; }}
    table.meta {{ width: 100%; font-size: 12px; margin-bottom: 16px; border-collapse: collapse; }}
    table.meta td {{ padding: 4px 6px; }}
    table.items {{ border-collapse: collapse; width: 100%; font-size: 11.5px; margin-top: 12px; }}
    table.items th {{ border: 1px solid #1e293b; padding: 7px 8px; background: #f1f5f9; font-size: 11px; text-align: left; color: #0f172a; font-weight: 700; }}
    table.items td {{ border: 1px solid #334155; padding: 7px 8px; }}
    table.items tfoot td {{ font-weight: 700; background: #f8fafc; border: 1px solid #1e293b; }}
    .footer {{ margin-top: 28px; font-size: 11px; color: #475569; text-align: center; border-top: 1px solid #cbd5e1; padding-top: 12px; }}
    </style></head>
    <body><div class="wrap">
    <p style="font-size:11px;color:#64748b;margin-bottom:4px;text-align:right;">Challan Ref: <b>{final_challan_number}</b> | Received: <b>{challan_date}</b></p>
    <h1>Accepted Challan (গৃহীত চালান)</h1>
    <table class="meta" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:8px;">
    <tr><td><b>Requisition:</b> Dies &amp; Tooling for BLDC Motor Production (Ref: {REF_NO})</td><td><b>Supplier:</b> {VENDOR_NAME}</td></tr>
    <tr><td><b>Inspected &amp; Received by:</b> {VERIFIED_BY}</td><td><b>Challan Number:</b> {final_challan_number}</td></tr>
    </table>
    <table class="items">
    <thead>
    <tr>
        <th style="width:32%;">Item Details</th>
        <th style="width:11%;text-align:center;">Ordered</th>
        <th style="width:11%;text-align:center;color:#16a34a;">Received</th>
        <th style="width:10%;text-align:center;color:#dc2626;">Rejected</th>
        <th style="width:14%;text-align:right;">Unit Price</th>
        <th style="width:14%;text-align:right;">Line Total</th>
        <th style="width:18%;">QC Remarks</th>
    </tr>
    </thead>
    <tbody>{rows_html}</tbody>
    <tfoot>
    <tr>
        <td colspan="5" style="text-align:right;font-size:12px;">TOTAL ACCEPTED PAYABLE:</td>
        <td style="text-align:right;font-family:monospace;font-size:13px;color:#0f172a;">BDT {format_indian_number(TOTAL_DIES)}</td>
        <td></td>
    </tr>
    <tr>
        <td colspan="7" style="background:#f8fafc;font-size:11.5px;color:#334155;padding:8px 10px;">
        <b>In Word:</b> {amount_to_words_bangla(TOTAL_DIES)}
        </td>
    </tr>
    </tfoot>
    </table>
    <div class="footer">
        <p>Accepted by: <strong>{VERIFIED_BY}</strong> &nbsp;|&nbsp; Date: <strong>{challan_date}</strong> &nbsp;|&nbsp; Time: <strong>{challan_time} BST</strong></p>
        <p style="font-size:10px;color:#94a3b8;margin-top:4px;">This Accepted Challan is system-generated based on physical goods received and QC-accepted quantities only.<br>
        Rejected items ({format_quantity(total_rejected)} units) are excluded from payment calculation.</p>
    </div>
    </div></body></html>
    """
    pdf_bytes = HTML(string=html_content).write_pdf()
    if pdf_bytes:
        save_pdf("06_Accepted_Challan_QC_Receiving_Voucher.pdf", pdf_bytes, "06. Stage 4: Accepted Challan & QC Receiving Voucher")


async def generate_07_pp_virgin_work_order():
    """7. PP Virgin Plastic Raw Material Work Order PDF"""
    wo_mock = MagicMock()
    wo_mock.id = "bb41254c-1532-4ff7-824a-deee4371c17a"
    wo_mock.reference_code = "WO-04A7E919"
    wo_mock.issued_at = datetime(2026, 11, 1, 15, 30, tzinfo=timezone.utc)
    
    req_mock = MagicMock(
        id="04a7e919-2b09-4840-bfdb-1c26163e5be7",
        title="PP Virgin Raw Material Procurement",
        unit="Bags",
    )
    wo_mock.requisition = req_mock
    
    vendor_mock = MagicMock(
        company_name="Meghna Plastic Industries Ltd.",
        contact_person="Engr. Khorshed Alam (Head of Sales)",
        phone="+880 1819-876543",
        contact_email="sales@meghnaplastics.com",
    )
    wo_mock.vendor = vendor_mock
    
    wo_mock._quotation_data = {
        "price": TOTAL_PP_VIRGIN,
        "delivery_days": 15,
        "payment_terms": "30% Advance with Purchase Order confirmation, 70% upon delivery & QC inspection.",
        "warranty": "Standard manufacturer raw material QC certificate and replacement of defective lots.",
        "notes": "Delivery in 25kg sealed moisture-proof bags to Wener Factory, Mirer Bazar, Pubail, Gazipur.",
        "items": ITEMS_PP_VIRGIN,
    }
    wo_mock.requisition_vendor = None

    pdf_bytes = await generate_work_order_pdf(wo_mock, letterhead_url=None)
    if pdf_bytes:
        save_pdf("07_PP_Virgin_Raw_Material_Work_Order.pdf", pdf_bytes, "07. Requisition Case: PP Virgin Raw Material Official Work Order")


def generate_08_requisition_worksheet_a4():
    """8. Requisition Worksheet Specification Sheet (Printable A4 Sheet)"""
    rows_html = ""
    for idx, item in enumerate(ITEMS_DIES, 1):
        budget = item["qty"] * item["price"]
        rows_html += f"""
        <tr>
            <td style="border:1px solid #334155;padding:8px;text-align:center;font-weight:700;">{idx}</td>
            <td style="border:1px solid #334155;padding:8px;font-weight:700;color:#0f172a;">{item['name']}</td>
            <td style="border:1px solid #334155;padding:8px;font-size:11.5px;color:#334155;">{item['description']}</td>
            <td style="border:1px solid #334155;padding:8px;text-align:center;font-weight:700;">{item['qty']}</td>
            <td style="border:1px solid #334155;padding:8px;text-align:center;font-weight:600;color:#475569;">{item['unit']}</td>
            <td style="border:1px solid #334155;padding:8px;text-align:right;font-family:monospace;font-weight:700;">৳{format_indian_number(budget)}</td>
        </tr>
        """

    html_content = f"""
    <!DOCTYPE html><html>
    <head><meta charset="utf-8">
    <style>
    @page {{ size: A4 portrait; margin: 12mm 10mm; }}
    body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #1e293b; line-height: 1.45; font-size: 12px; }}
    .header {{ border-bottom: 2px solid #1e293b; padding-bottom: 8px; margin-bottom: 12px; }}
    .title {{ font-size: 18px; font-weight: 800; color: #0f172a; text-transform: uppercase; letter-spacing: 0.5px; }}
    .meta-box {{ width: 100%; border-collapse: collapse; margin-bottom: 14px; font-size: 11.5px; }}
    .meta-box td {{ padding: 4px 6px; }}
    .badge {{ display: inline-block; padding: 2px 8px; font-size: 10px; font-weight: 700; border-radius: 4px; text-transform: uppercase; background: #e0e7ff; color: #3730a3; border: 1px solid #c7d2fe; }}
    table.worksheet {{ width: 100%; border-collapse: collapse; font-size: 11.5px; }}
    table.worksheet th {{ border: 1px solid #1e293b; background: #f1f5f9; padding: 8px 6px; font-weight: 700; font-size: 11px; color: #0f172a; }}
    table.worksheet td {{ border: 1px solid #334155; }}
    .footer {{ margin-top: 24px; font-size: 10px; color: #64748b; border-top: 1px solid #e2e8f0; padding-top: 8px; text-align: center; }}
    </style></head>
    <body>
    <div class="header">
        <table style="width:100%;">
            <tr>
                <td style="text-align:left;">
                    <div style="font-size:10px;color:#64748b;font-weight:700;letter-spacing:1px;text-transform:uppercase;">Wener Trading Company &bull; Internal Procurement</div>
                    <div class="title">Requisition Worksheet: Dies &amp; Tooling for BLDC Motor Production</div>
                </td>
                <td style="text-align:right;vertical-align:bottom;">
                    <span class="badge">WO Issued</span>
                </td>
            </tr>
        </table>
    </div>

    <table class="meta-box" style="background:#f8fafc;border:1px solid #cbd5e1;border-radius:6px;">
        <tr>
            <td style="width:25%;"><b>Requisition Ref:</b> REQ-04A7E919</td>
            <td style="width:25%;"><b>Target Category:</b> Electrical &amp; Mechanical Tooling</td>
            <td style="width:25%;"><b>Created By:</b> Omar Faruk Shohan</td>
            <td style="width:25%;"><b>Created Date:</b> October 20, 2026</td>
        </tr>
        <tr>
            <td><b>Estimated Budget:</b> ৳235,000.00</td>
            <td><b>Linked Work Order:</b> WO-04A7E919</td>
            <td><b>Default Unit:</b> Set</td>
            <td><b>QC Requirement:</b> Mandatory Physical Inspection</td>
        </tr>
    </table>

    <table class="worksheet">
        <thead>
            <tr>
                <th style="width:6%;text-align:center;">S/N</th>
                <th style="width:26%;text-align:left;">Item Name</th>
                <th style="width:36%;text-align:left;">Technical Specifications</th>
                <th style="width:10%;text-align:center;">Quantity</th>
                <th style="width:10%;text-align:center;">Unit</th>
                <th style="width:12%;text-align:right;">Est. Total (৳)</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
            <tr style="background:#f8fafc;font-weight:700;">
                <td colspan="5" style="border:1px solid #1e293b;padding:8px;text-align:right;">TOTAL ESTIMATED BUDGET (BDT):</td>
                <td style="border:1px solid #1e293b;padding:8px;text-align:right;font-family:monospace;font-size:12px;color:#0f172a;">৳{format_indian_number(TOTAL_DIES)}</td>
            </tr>
        </tbody>
    </table>

    <div class="footer">
        Generated from Wener ERP Procurement System &bull; Timezone: Bangladesh Standard Time (BST, GMT+6) &bull; Page 1 of 1
    </div>
    </body></html>
    """
    pdf_bytes = HTML(string=html_content).write_pdf()
    if pdf_bytes:
        save_pdf("08_Requisition_Worksheet_A4_Printable.pdf", pdf_bytes, "08. Printable A4: Requisition Excel-Tabular Worksheet")


def generate_09_quotation_comparison_matrix():
    """9. Executive Quotation Comparison & Evaluation Matrix PDF"""
    html_content = f"""
    <!DOCTYPE html><html>
    <head><meta charset="utf-8">
    <style>
    @page {{ size: A4 landscape; margin: 10mm 12mm; }}
    body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #1e293b; line-height: 1.4; font-size: 11px; }}
    .header {{ border-bottom: 2px solid #0f172a; padding-bottom: 6px; margin-bottom: 10px; display: flex; justify-content: space-between; }}
    .title {{ font-size: 16px; font-weight: 800; color: #0f172a; text-transform: uppercase; }}
    table.comp {{ width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 10px; }}
    table.comp th {{ border: 1px solid #cbd5e1; padding: 7px 8px; font-weight: 700; }}
    table.comp td {{ border: 1px solid #cbd5e1; padding: 7px 8px; vertical-align: top; }}
    .vendor-head {{ background: #f8fafc; font-size: 12px; font-weight: 800; }}
    .best-bid {{ background: #eff6ff; border-top: 2px solid #1d4ed8 !important; }}
    .text-rose {{ color: #e11d48; font-weight: 700; }}
    .text-blue {{ color: #1d4ed8; font-weight: 700; }}
    .footer {{ margin-top: 14px; font-size: 10px; color: #64748b; border-top: 1px solid #e2e8f0; padding-top: 6px; display: flex; justify-content: space-between; }}
    </style></head>
    <body>
    <table style="width:100%;border-bottom:2px solid #0f172a;padding-bottom:6px;">
        <tr>
            <td>
                <div style="font-size:9px;color:#64748b;font-weight:700;text-transform:uppercase;">Executive Decision Portal &bull; Comparative Analysis</div>
                <div class="title">Quotation Evaluation Matrix: Dies &amp; Tooling for BLDC Motor Production</div>
                <div style="font-size:11px;color:#475569;">Requisition: <b>REQ-04A7E919</b> &bull; Total Vendors Quoted: <b>3</b> &bull; Sorted: <b>Lowest Overall Total First</b></div>
            </td>
            <td style="text-align:right;vertical-align:bottom;">
                <span style="background:#dcfce7;color:#166534;border:1px solid #bbf7d0;padding:3px 8px;border-radius:4px;font-weight:700;font-size:10px;">Evaluation Completed</span>
            </td>
        </tr>
    </table>

    <table class="comp">
        <thead>
            <tr style="background:#f1f5f9;">
                <th style="width:25%;text-align:left;">Item / Evaluation Criteria</th>
                <th class="best-bid" style="width:25%;text-align:left;">
                    <div style="font-size:12px;color:#1d4ed8;">1. Ashraf Lathe Works</div>
                    <div style="font-size:10px;color:#1e40af;">★ Lowest Overall Bidder</div>
                </th>
                <th style="width:25%;text-align:left;">
                    <div style="font-size:12px;color:#0f172a;">2. Super Engineering Ltd.</div>
                    <div style="font-size:10px;color:#64748b;">Alternative Supplier</div>
                </th>
                <th style="width:25%;text-align:left;">
                    <div style="font-size:12px;color:#0f172a;">3. Modern Lathe &amp; Tools</div>
                    <div style="font-size:10px;color:#64748b;">Alternative Supplier</div>
                </th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>
                    <b>1. BLDC Circle Patting Die (Complete Set)</b><br>
                    <small style="color:#64748b;">Bearing Metal Diameter 132mm &bull; Qty: 1 Set</small>
                </td>
                <td class="best-bid">
                    <b class="text-blue">৳40,000.00</b><br>
                    <small class="text-blue">Lowest offer for item</small>
                </td>
                <td>
                    ৳45,000.00<br>
                    <small class="text-rose">+৳5,000 (+12.5%)</small>
                </td>
                <td>
                    ৳48,000.00<br>
                    <small class="text-rose">+৳8,000 (+20.0%)</small>
                </td>
            </tr>
            <tr>
                <td>
                    <b>2. BLDC Armature Cutting Die</b><br>
                    <small style="color:#64748b;">D2 iron (18 shots dia 132mm, 28mm) &bull; Qty: 1 Set</small>
                </td>
                <td class="best-bid">
                    <b class="text-blue">৳130,000.00</b><br>
                    <small class="text-blue">Lowest offer for item</small>
                </td>
                <td>
                    ৳145,000.00<br>
                    <small class="text-rose">+৳15,000 (+11.5%)</small>
                </td>
                <td>
                    ৳160,000.00<br>
                    <small class="text-rose">+৳30,000 (+23.1%)</small>
                </td>
            </tr>
            <tr>
                <td>
                    <b>3. Armature Ripit Die (Complete Set)</b><br>
                    <small style="color:#64748b;">Mild Steel Precision Finish &bull; Qty: 1 Set</small>
                </td>
                <td class="best-bid">
                    <b class="text-blue">৳65,000.00</b><br>
                    <small class="text-blue">Lowest offer for item</small>
                </td>
                <td>
                    ৳75,000.00<br>
                    <small class="text-rose">+৳10,000 (+15.4%)</small>
                </td>
                <td>
                    ৳82,000.00<br>
                    <small class="text-rose">+৳17,000 (+26.2%)</small>
                </td>
            </tr>
            <tr style="background:#f8fafc;font-weight:700;">
                <td style="font-size:12px;">TOTAL QUOTED AMOUNT:</td>
                <td class="best-bid" style="font-size:13px;font-family:monospace;color:#1d4ed8;">
                    ৳235,000.00<br>
                    <span style="font-size:10px;font-weight:700;color:#16a34a;">● WINNING BID (Lowest)</span>
                </td>
                <td style="font-size:12px;font-family:monospace;">
                    ৳265,000.00<br>
                    <span class="text-rose">+৳30,000.00 (+12.8%)</span>
                </td>
                <td style="font-size:12px;font-family:monospace;">
                    ৳290,000.00<br>
                    <span class="text-rose">+৳55,000.00 (+23.4%)</span>
                </td>
            </tr>
            <tr>
                <td><b>Delivery Timeline</b></td>
                <td class="best-bid"><b>30 working days</b></td>
                <td>25 working days</td>
                <td>35 working days</td>
            </tr>
            <tr>
                <td><b>Commercial Payment Terms</b></td>
                <td class="best-bid">50% Advance with PO, 50% on Delivery</td>
                <td>60% Advance, 40% on Delivery</td>
                <td>100% Against Delivery &amp; QC</td>
            </tr>
            <tr>
                <td><b>Executive Award Action</b></td>
                <td class="best-bid">
                    <span style="background:#1d4ed8;color:#ffffff;padding:4px 8px;border-radius:4px;font-weight:700;font-size:10px;">★ Awarded Full PO</span>
                </td>
                <td><span style="color:#64748b;font-size:10px;">Not Shortlisted</span></td>
                <td><span style="color:#64748b;font-size:10px;">Not Shortlisted</span></td>
            </tr>
        </tbody>
    </table>

    <table style="width:100%;margin-top:14px;font-size:10px;color:#64748b;border-top:1px solid #e2e8f0;padding-top:4px;">
        <tr>
            <td>Wener ERP &bull; Price Comparison Engine &bull; Red Deltas Highlight Cost Variance Above Lowest Bid</td>
            <td style="text-align:right;">Generated at: November 02, 2026 &bull; BST (GMT+6)</td>
        </tr>
    </table>
    </body></html>
    """
    pdf_bytes = HTML(string=html_content).write_pdf()
    if pdf_bytes:
        save_pdf("09_Executive_Quotation_Comparison_Matrix.pdf", pdf_bytes, "09. Executive: Side-by-Side Quotation Comparison & Evaluation Matrix")


async def main():
    print("=" * 75)
    print("GENERATING ALL SYSTEM PROCUREMENT PDFS LOCALLY ON DEVICE")
    print(f"Target Primary Folder: {OUTPUT_DIR}")
    print(f"Target Cycle Folder:   {CYCLE_DIR}")
    print("=" * 75)

    generate_01_rfq_round1()
    generate_02_rfq_round2()
    generate_03_supplier_quotation()
    await generate_04_work_order_standard()
    await generate_05_work_order_with_letterhead()
    generate_06_accepted_challan()
    await generate_07_pp_virgin_work_order()
    generate_08_requisition_worksheet_a4()
    generate_09_quotation_comparison_matrix()

    print("\n" + "=" * 75)
    print("ALL 9 OF 9 PDFS GENERATED SUCCESSFULLY ON DEVICE")
    print("=" * 75)
    for p in sorted(OUTPUT_DIR.glob("*.pdf")):
        print(f"  • {p.name:<48} ({p.stat().st_size:,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
