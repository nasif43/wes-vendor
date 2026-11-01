"""
Work order business logic:
- PDF generation using WeasyPrint + active letterhead
- Email dispatch to winning supplier + management CC
- Supplier rating creation after invoice finalization
"""
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from app.utils.number_formatting import (
    amount_to_words_bangla,
    format_indian_number,
    format_quantity,
)

logger = logging.getLogger(__name__)


async def generate_work_order_pdf(work_order, letterhead_url: str | None) -> bytes | None:
    """Render work order HTML template to PDF bytes via WeasyPrint."""
    try:
        from weasyprint import HTML
        from zoneinfo import ZoneInfo
        from datetime import timezone as _tz

        req = work_order.requisition
        vendor = work_order.vendor

        # Try to get items from quotation form_data (with fallback to requisition_vendor)
        quotation = getattr(work_order, '_quotation_data', None)
        if not quotation and work_order.requisition_vendor:
            rv = work_order.requisition_vendor
            if rv.quotation and rv.quotation.form_data:
                quotation = rv.quotation.form_data

        # Dates
        issued_date = "N/A"
        if work_order.issued_at:
            try:
                dt_bst = work_order.issued_at.astimezone(ZoneInfo("Asia/Dhaka")) if work_order.issued_at.tzinfo else work_order.issued_at.replace(tzinfo=_tz.utc).astimezone(ZoneInfo("Asia/Dhaka"))
                issued_date = dt_bst.strftime("%B %d, %Y")
            except Exception:
                issued_date = work_order.issued_at.strftime("%B %d, %Y")

        quotation_date_str = ""
        if work_order.requisition_vendor and work_order.requisition_vendor.quotation:
            q = work_order.requisition_vendor.quotation
            if q.submitted_at:
                try:
                    q_bst = q.submitted_at.astimezone(ZoneInfo("Asia/Dhaka")) if q.submitted_at.tzinfo else q.submitted_at.replace(tzinfo=_tz.utc).astimezone(ZoneInfo("Asia/Dhaka"))
                    quotation_date_str = q_bst.strftime("%B %d, %Y")
                except Exception:
                    quotation_date_str = q.submitted_at.strftime("%B %d, %Y")

        # Reference code: WO-{req.id[:8].upper()}
        ref_code = (
            work_order.reference_code
            if hasattr(work_order, "reference_code")
            else (f"WO-{req.id[:8].upper()}" if req and req.id else f"WO-{work_order.id[:8].upper()}")
        )

        # Build items table
        rows_html = ""
        grand_total = 0.0
        if quotation and isinstance(quotation, dict) and quotation.get("items"):
            for idx, item in enumerate(quotation["items"], 1):
                qty = item.get("qty", 0)
                price = item.get("price", 0)
                try:
                    total = float(qty) * float(price)
                except Exception:
                    total = 0.0
                grand_total += total
                unit = item.get("unit") or (req.unit if req else "") or ""
                qty_display = format_quantity(qty)
                if unit:
                    qty_display = f"{qty_display} {unit}"
                price_display = format_indian_number(price)
                total_display = format_indian_number(total)
                rows_html += (
                    f"<tr>"
                    f"<td style='border:1px solid #334155;padding:7px 8px;text-align:center;font-weight:600;'>{idx}</td>"
                    f"<td style='border:1px solid #334155;padding:7px 8px;'><b>{item.get('name','')}</b></td>"
                    f"<td style='border:1px solid #334155;padding:7px 8px;font-size:11.5px;color:#333;'>{item.get('description','')}</td>"
                    f"<td style='border:1px solid #334155;padding:7px 8px;text-align:center;font-weight:600;'>{qty_display}</td>"
                    f"<td style='border:1px solid #334155;padding:7px 8px;text-align:right;font-family:monospace;'>{price_display}</td>"
                    f"<td style='border:1px solid #334155;padding:7px 8px;text-align:right;font-family:monospace;font-weight:600;'>{total_display}</td>"
                    f"</tr>"
                )

        if not rows_html:
            # Fallback for old/empty quotation data
            raw_price = (quotation or {}).get("price", 0.0) if isinstance(quotation, dict) else 0.0
            try:
                grand_total = float(raw_price)
            except Exception:
                grand_total = 0.0
            rows_html = (
                f"<tr>"
                f"<td style='border:1px solid #334155;padding:8px;text-align:center;'>1</td>"
                f"<td style='border:1px solid #334155;padding:8px;'><b>{req.title if req else 'Procurement Scope'}</b></td>"
                f"<td style='border:1px solid #334155;padding:8px;font-size:11px;color:#555;'>As per submitted quotation</td>"
                f"<td style='border:1px solid #334155;padding:8px;text-align:center;'>1</td>"
                f"<td style='border:1px solid #334155;padding:8px;text-align:right;font-family:monospace;'>{format_indian_number(grand_total)}</td>"
                f"<td style='border:1px solid #334155;padding:8px;text-align:right;font-family:monospace;font-weight:600;'>{format_indian_number(grand_total)}</td>"
                f"</tr>"
            )

        # Dynamic Terms & Conditions from Quotation
        terms_items = []
        if isinstance(quotation, dict):
            delivery_days = quotation.get("delivery_days")
            payment_terms = quotation.get("payment_terms")
            warranty = quotation.get("warranty")
            notes = quotation.get("notes") or getattr(work_order, 'notes', None)

            if delivery_days:
                terms_items.append(f"<li><b>Delivery Timeline:</b> Delivery within next <b>{delivery_days} days</b> from PO issuance date.</li>")
            if payment_terms:
                terms_items.append(f"<li><b>Payment Terms:</b> {payment_terms}</li>")
            if warranty:
                terms_items.append(f"<li><b>Warranty / Support:</b> {warranty}</li>")
            if notes:
                terms_items.append(f"<li><b>Special Conditions:</b> {notes}</li>")

        terms_html = "".join(terms_items) if terms_items else "<li>Terms strictly as per approved quotation specifications.</li>"

        # Vendor Contact Information
        vendor_name = vendor.company_name if vendor else "N/A"
        contact_parts = []
        if vendor and vendor.contact_person:
            contact_parts.append(f"<b>Attn:</b> {vendor.contact_person}")
        if vendor and vendor.phone:
            contact_parts.append(f"<b>Phone:</b> {vendor.phone}")
        if vendor and vendor.contact_email:
            contact_parts.append(f"<b>Email:</b> {vendor.contact_email}")
        contact_line = " &nbsp;|&nbsp; ".join(contact_parts) if contact_parts else "Contact information as per vendor directory."

        # Salutation
        salutation_intro = (
            f"Referring to your quotation submitted on <b>{quotation_date_str}</b>, we are pleased to place this official Purchase Order for supply. "
            if quotation_date_str
            else "We are pleased to place this official Purchase Order for supply. "
        )

        bg_style = ""
        container_style = ""
        if letterhead_url:
            actual_bg_url = letterhead_url
            try:
                import os
                from app.config import get_settings
                settings = get_settings()
                if "uploads/" in letterhead_url or letterhead_url.startswith("http://localhost"):
                    clean_lh = (
                        letterhead_url
                        .replace("http://localhost:8000", "")
                        .replace(settings.app_url, "")
                        .removeprefix("/uploads/")
                    )
                    local_lh = os.path.join(settings.upload_dir, clean_lh)
                    if os.path.exists(local_lh):
                        actual_bg_url = f"file://{os.path.abspath(local_lh)}"
                    elif not letterhead_url.startswith("http"):
                        actual_bg_url = None
            except Exception:
                actual_bg_url = letterhead_url

            if actual_bg_url:
                bg_style = f"background-image: url('{actual_bg_url}'); background-size: cover; background-position: center;"
                container_style = "background: rgba(255,255,255,0.94); padding: 24px 28px; border-radius: 8px;"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            @page {{ size: A4; margin: 40px 45px 40px 45px; }}
            body {{ {bg_style} font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                   color: #1a1a1a; line-height: 1.5; font-size: 12px; }}
            .container {{ {container_style} }}
            .header-table {{ width: 100%; margin-bottom: 12px; }}
            .header-table td {{ padding: 0; vertical-align: top; }}
            .doc-title {{
                text-align: center; font-size: 20px; font-weight: 800; letter-spacing: 1.5px;
                text-transform: uppercase; margin: 12px 0 18px 0; color: #0f172a;
                border-bottom: 2px solid #0f172a; padding-bottom: 6px;
            }}
            .recipient-box {{
                margin-bottom: 16px; font-size: 12px; line-height: 1.55;
                background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px 14px;
            }}
            .salutation {{
                margin-bottom: 14px; font-size: 12px; color: #1e293b; line-height: 1.55; text-align: justify;
            }}
            table.items {{
                width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 18px;
            }}
            table.items th {{
                border: 1px solid #1e293b; background: #f1f5f9; padding: 8px 6px;
                font-weight: 700; font-size: 11px; text-align: center; color: #0f172a;
            }}
            table.items td {{
                border: 1px solid #334155; padding: 8px 8px; vertical-align: middle;
            }}
            table.items .totals-row td {{
                border: 1px solid #1e293b; padding: 8px 10px; font-weight: 700;
            }}
            .in-words-row {{
                background: #f8fafc; font-size: 12px; color: #0f172a; padding: 8px 10px;
                border: 1px solid #1e293b;
            }}
            .terms-card {{
                border: 1px solid #cbd5e1; border-radius: 6px; background: #ffffff;
                padding: 12px 16px; margin-top: 14px; margin-bottom: 24px;
            }}
            .terms-card-title {{
                font-size: 11.5px; font-weight: 700; color: #0f172a; text-transform: uppercase;
                letter-spacing: 0.5px; margin-bottom: 8px; border-bottom: 1px solid #f1f5f9; padding-bottom: 4px;
            }}
            .terms-list {{
                margin: 0; padding-left: 18px; font-size: 11.5px; color: #334155; line-height: 1.6;
            }}
            .footer-notes {{
                margin-top: 24px; font-size: 10.5px; color: #475569; border-top: 1px solid #cbd5e1;
                padding-top: 10px; line-height: 1.5;
            }}
            .footer-notes b {{ color: #0f172a; }}
          </style>
        </head>
        <body>
          <div class="container">
            <!-- Header: Ref & Date -->
            <table class="header-table">
            <tr>
                <td style="text-align:left;font-weight:700;font-size:13px;color:#0f172a;">
                    Ref: {ref_code}
                </td>
                <td style="text-align:right;font-size:12px;color:#475569;">
                    Date: <b>{issued_date}</b>
                </td>
            </tr>
            </table>

            <!-- Document Title -->
            <div class="doc-title">PURCHASE ORDER</div>

            <!-- Recipient Block -->
            <div class="recipient-box">
                <div style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;">To Supplier:</div>
                <div style="font-size:14px;font-weight:800;color:#0f172a;margin-top:2px;">{vendor_name}</div>
                <div style="color:#334155;font-size:11.5px;margin-top:2px;">
                    {contact_line}
                </div>
            </div>

            <!-- Salutation & Body Intro -->
            <div class="salutation">
                <b>Dear Concern,</b><br>
                {salutation_intro}Please supply the below items strictly as per the specified descriptions, accepted quantities, and agreed terms:
            </div>

            <!-- Items Table -->
            <table class="items">
            <thead>
                <tr>
                    <th style="width:6%;">S/N</th>
                    <th style="width:28%;text-align:left;">Item Name</th>
                    <th style="width:36%;text-align:left;">Specification</th>
                    <th style="width:12%;">Quantity</th>
                    <th style="width:9%;text-align:right;">Rate (Tk)</th>
                    <th style="width:9%;text-align:right;">Total (Tk)</th>
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
                    <b>N.B:</b> The supplier's physical delivery challan and final invoice must explicitly quote this Purchase Order Reference Number (<b>{ref_code}</b>) to clear goods receipt inspection and release payment.
                </div>
            </div>
          </div>
        </body>
        </html>
        """

        pdf_bytes = HTML(string=html_content).write_pdf()
        return pdf_bytes

    except Exception as exc:
        logger.exception("generate_work_order_pdf failed: %s", exc)
        return None


async def send_work_order_email(work_order, pdf_bytes: bytes) -> bool:
    """Send the work order PDF to the winning supplier + management CC."""
    try:
        from app.email.resend import get_cc_emails, _apply_cc, send_batch, settings
        vendor = work_order.vendor
        req = work_order.requisition
        if not vendor or not vendor.contact_email:
            return False

        cc = await get_cc_emails()
        supplier_name = vendor.company_name
        req_title = req.title if req else "N/A"

        html = f"""
        <h2>Work Order Issued</h2>
        <p>Dear {supplier_name},</p>
        <p>Please find attached the official Work Order / Purchase Order for
        <strong>{req_title}</strong>.</p>
        <p>Kindly proceed with the delivery of the requested items as per the agreed specifications.</p>
        <p>Work Order Reference: <strong>{work_order.id[:8].upper()}</strong></p>
        """

        payload = _apply_cc({
            "from": f"Wener Supplier Management <{settings.mail_from}>",
            "to": [vendor.contact_email],
            "subject": f"Work Order: {req_title}",
            "html": html,
            "attachments": [{
                "filename": f"WorkOrder_{work_order.id[:8].upper()}.pdf",
                "content": list(pdf_bytes),
            }],
        }, cc)

        return await send_batch([payload])
    except Exception as exc:
        logger.exception("send_work_order_email failed: %s", exc)
        return False


async def create_supplier_rating(
    db: AsyncSession,
    work_order,
    received_items: list,
    rated_by_id: str,
) -> "SupplierRating":
    """Create a SupplierRating record after invoice is finalized.
    
    Args:
        received_items: list of ReceivedItem ORM objects
        rated_by_id: user.id of the QC receiver
    """
    from app.work_orders.models import SupplierRating
    from datetime import datetime, timezone

    total_ordered = sum(float(ri.ordered_qty) for ri in received_items)
    total_received = sum(float(ri.received_qty) for ri in received_items)
    total_rejected = sum(float(ri.rejected_qty) for ri in received_items)
    defect_rate = (total_rejected / total_ordered * 100.0) if total_ordered > 0 else 0.0

    delivery_days = None
    if work_order.delivery_started_at and work_order.delivery_completed_at:
        delta = work_order.delivery_completed_at - work_order.delivery_started_at
        delivery_days = round(delta.total_seconds() / 86400.0, 2)

    rating = SupplierRating(
        vendor_id=work_order.vendor_id,
        requisition_id=work_order.requisition_id,
        work_order_id=work_order.id,
        rated_by=rated_by_id,
        delivery_days=delivery_days,
        ordered_qty=total_ordered,
        received_qty=total_received,
        rejected_qty=total_rejected,
        defect_rate_pct=round(defect_rate, 2),
    )
    db.add(rating)
    await db.flush()
    return rating
