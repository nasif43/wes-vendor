"""
Generate sample Purchase Order / Work Order PDF based on ACTUAL platform data fields:
- REMOVED: 4-column signature section (per user instruction)
- REMOVED: Payment clearance method box (per user instruction)
- DYNAMIC: Terms & Conditions directly rendered from quotation fields (payment_terms, delivery_days, warranty, notes) without rigid bullets
- LABELED: 'In Word:'
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from weasyprint import HTML
from app.utils.number_formatting import (
    amount_to_words_bangla,
    format_indian_number,
    format_quantity,
)

OUTPUT_DIR = PROJECT_ROOT / "generated_cycle_pdfs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Demonstration of correlated ID
REQ_CODE = "04A7E919"
REF_NO = f"WO-{REQ_CODE}"  # or WES/PO/2026/04A7E919
PO_DATE = "October 26, 2026"
QUOTATION_DATE = "October 24, 2026"

VENDOR_NAME = "Ashraf Lathe Works"
VENDOR_CONTACT = "Md. Ashraf Hossain (Proprietor)"
VENDOR_PHONE = "+880 1711-234567"
VENDOR_EMAIL = "ashraf.lathe@gmail.com"

# The 3 items from the quotation
ITEMS = [
    {
        "name": "BLDC Circle Patting Die (Complete Set)",
        "description": "Bearing Metal Diameter 132mm, Tooling Grade",
        "qty": 1,
        "price": 40000.0,
    },
    {
        "name": "BLDC Armature Cutting Die",
        "description": "D2 iron (18 shots diameter 132mm & thickness 28mm)",
        "qty": 1,
        "price": 130000.0,
    },
    {
        "name": "Armature Ripit Die (Complete Set)",
        "description": "Mild Steel Precision Finish, Standard Spec",
        "qty": 1,
        "price": 65000.0,
    },
]

grand_total = sum(item["qty"] * item["price"] for item in ITEMS)

# Actual flexible quotation data received from the supplier
# Can be structured (delivery_days, payment_terms, warranty) or a full free-text agreement note
QUOTED_DELIVERY = "30 working days"
QUOTED_PAYMENT_TERMS = "50% Advance with Purchase Order confirmation, balance 50% upon delivery and physical QC acceptance."
QUOTED_WARRANTY = "2 Months free technical replacement & service support."
QUOTED_NOTES = "Rates are inclusive of delivery to Gazipur factory premises. Loading/unloading included."

# Build dynamic terms block
terms_items = []
if QUOTED_DELIVERY:
    terms_items.append(f"<li><b>Delivery:</b> Within {QUOTED_DELIVERY} from PO date.</li>")
if QUOTED_PAYMENT_TERMS:
    terms_items.append(f"<li><b>Payment Terms:</b> {QUOTED_PAYMENT_TERMS}</li>")
if QUOTED_WARRANTY:
    terms_items.append(f"<li><b>Warranty / Support:</b> {QUOTED_WARRANTY}</li>")
if QUOTED_NOTES:
    terms_items.append(f"<li><b>Special Conditions:</b> {QUOTED_NOTES}</li>")

terms_html = "".join(terms_items) if terms_items else "<li>Terms as per submitted supplier quotation.</li>"

rows_html = ""
for idx, item in enumerate(ITEMS, 1):
    qty = float(item["qty"])
    price = float(item["price"])
    line_total = qty * price
    rows_html += f"""
    <tr>
        <td style="text-align:center;font-weight:600;">{idx}</td>
        <td><b>{item['name']}</b></td>
        <td style="font-size:11.5px;color:#333;">{item['description']}</td>
        <td style="text-align:center;font-weight:600;">{format_quantity(qty)}</td>
        <td style="text-align:right;font-family:monospace;">{format_indian_number(price)}</td>
        <td style="text-align:right;font-family:monospace;font-weight:600;">{format_indian_number(line_total)}</td>
    </tr>
    """

html_template = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page {{
        size: A4;
        margin: 40px 45px 40px 45px;
    }}
    body {{
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        color: #1a1a1a;
        line-height: 1.5;
        font-size: 12px;
    }}
    .header-table {{
        width: 100%;
        margin-bottom: 12px;
    }}
    .header-table td {{
        padding: 0;
        vertical-align: top;
    }}
    .doc-title {{
        text-align: center;
        font-size: 20px;
        font-weight: 800;
        letter-spacing: 1.5px;
        text-transform: uppercase;
        margin: 12px 0 18px 0;
        color: #0f172a;
        border-bottom: 2px solid #0f172a;
        padding-bottom: 6px;
    }}
    .recipient-box {{
        margin-bottom: 16px;
        font-size: 12px;
        line-height: 1.55;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 10px 14px;
    }}
    .salutation {{
        margin-bottom: 14px;
        font-size: 12px;
        color: #1e293b;
        line-height: 1.55;
        text-align: justify;
    }}
    table.items {{
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
        margin-bottom: 18px;
    }}
    table.items th {{
        border: 1px solid #1e293b;
        background: #f1f5f9;
        padding: 8px 6px;
        font-weight: 700;
        font-size: 11px;
        text-align: center;
        color: #0f172a;
    }}
    table.items td {{
        border: 1px solid #334155;
        padding: 8px 8px;
        vertical-align: middle;
    }}
    table.items .totals-row td {{
        border: 1px solid #1e293b;
        padding: 8px 10px;
        font-weight: 700;
    }}
    .in-words-row {{
        background: #f8fafc;
        font-size: 12px;
        color: #0f172a;
        padding: 8px 10px;
        border: 1px solid #1e293b;
    }}
    .terms-card {{
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        background: #ffffff;
        padding: 12px 16px;
        margin-top: 14px;
        margin-bottom: 24px;
    }}
    .terms-card-title {{
        font-size: 11.5px;
        font-weight: 700;
        color: #0f172a;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 8px;
        border-bottom: 1px solid #f1f5f9;
        padding-bottom: 4px;
    }}
    .terms-list {{
        margin: 0;
        padding-left: 18px;
        font-size: 11.5px;
        color: #334155;
        line-height: 1.6;
    }}
    .footer-notes {{
        margin-top: 24px;
        font-size: 10.5px;
        color: #475569;
        border-top: 1px solid #cbd5e1;
        padding-top: 10px;
        line-height: 1.5;
    }}
    .footer-notes b {{
        color: #0f172a;
    }}
</style>
</head>
<body>

<!-- Header: Ref & Date -->
<table class="header-table">
<tr>
    <td style="text-align:left;font-weight:700;font-size:13px;color:#0f172a;">
        Ref: {REF_NO}
    </td>
    <td style="text-align:right;font-size:12px;color:#475569;">
        Date: <b>{PO_DATE}</b>
    </td>
</tr>
</table>

<!-- Document Title -->
<div class="doc-title">PURCHASE ORDER</div>

<!-- Recipient Block -->
<div class="recipient-box">
    <div style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;">To Supplier:</div>
    <div style="font-size:14px;font-weight:800;color:#0f172a;margin-top:2px;">{VENDOR_NAME}</div>
    <div style="color:#334155;font-size:11.5px;margin-top:2px;">
        <b>Attn:</b> {VENDOR_CONTACT} &nbsp;|&nbsp; <b>Phone:</b> {VENDOR_PHONE} &nbsp;|&nbsp; <b>Email:</b> {VENDOR_EMAIL}
    </div>
</div>

<!-- Salutation & Body intro referencing actual quotation -->
<div class="salutation">
    <b>Dear Concern,</b><br>
    Referring to your quotation submitted on <b>{QUOTATION_DATE}</b>, we are pleased to place this official Purchase Order for supply. 
    Please supply the below items strictly as per the specified descriptions, accepted quantities, and agreed terms:
</div>

<!-- Line Items Table -->
<table class="items">
<thead>
    <tr>
        <th style="width:6%;">S/N</th>
        <th style="width:30%;text-align:left;">Item Name</th>
        <th style="width:34%;text-align:left;">Specification / Description</th>
        <th style="width:9%;">Qty</th>
        <th style="width:10%;text-align:right;">Rate (BDT)</th>
        <th style="width:11%;text-align:right;">Total (BDT)</th>
    </tr>
</thead>
<tbody>
    {rows_html}
    <tr class="totals-row">
        <td colspan="5" style="text-align:right;background:#f8fafc;font-size:12px;letter-spacing:0.5px;">TOTAL PAYABLE (BDT):</td>
        <td style="text-align:right;font-family:monospace;font-weight:800;background:#f8fafc;font-size:13px;color:#0f172a;">{format_indian_number(grand_total)}</td>
    </tr>
    <tr>
        <td colspan="6" class="in-words-row">
            <b>In Word:</b> {amount_to_words_bangla(grand_total)}
        </td>
    </tr>
</tbody>
</table>

<!-- Dynamic Terms & Conditions from Quotation -->
<div class="terms-card">
    <div class="terms-card-title">Agreed Terms &amp; Conditions (as per Quotation)</div>
    <ul class="terms-list">
        {terms_html}
    </ul>
</div>

<!-- Footer Notes: CC & N.B. -->
<div class="footer-notes">
    <div style="margin-bottom:4px;">
        <b>CC TO:</b> 01. Managing Director &amp; CEO &nbsp;|&nbsp; 02. Deputy General Manager &nbsp;|&nbsp; 03. Accounts &amp; Finance &nbsp;|&nbsp; 04. Store/QC Receiving
    </div>
    <div>
        <b>N.B:</b> The supplier's physical delivery challan and final invoice must explicitly quote this Purchase Order Reference Number (<b>{REF_NO}</b>) to clear goods receipt inspection and release payment.
    </div>
</div>

</body>
</html>
"""

out_pdf = OUTPUT_DIR / "sample_purchase_order_template.pdf"
out_html = OUTPUT_DIR / "sample_purchase_order_template.html"

out_html.write_text(html_template, encoding="utf-8")
HTML(string=html_template).write_pdf(target=str(out_pdf))

print(f"✓ Updated PDF: {out_pdf} ({out_pdf.stat().st_size:,} bytes)")
print(f"✓ Updated HTML: {out_html} ({out_html.stat().st_size:,} bytes)")
