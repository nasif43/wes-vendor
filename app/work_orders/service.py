"""
Work order business logic:
- PDF generation using WeasyPrint + active letterhead
- Email dispatch to winning supplier + management CC
- Supplier rating creation after invoice finalization
"""
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def generate_work_order_pdf(work_order, letterhead_url: str | None) -> bytes | None:
    """Render work order HTML template to PDF bytes via WeasyPrint."""
    try:
        from weasyprint import HTML
        from jinja2 import Environment, FileSystemLoader
        import os

        # Build items table from the winning quotation
        items = []
        grand_total = 0.0
        rv = work_order.requisition_vendor  # may be None if not loaded
        if rv is None and work_order.requisition_vendor_id:
            # Lazy-load if needed
            pass

        # Try to get items from quotation form_data
        quotation = None
        if hasattr(work_order, '_quotation_data'):
            quotation = work_order._quotation_data

        req = work_order.requisition
        vendor = work_order.vendor

        # Build inline HTML directly (no template file needed yet)
        rows_html = ""
        if quotation and isinstance(quotation, dict) and quotation.get("items"):
            for item in quotation["items"]:
                qty = item.get("qty", 0)
                price = item.get("price", 0)
                total = float(qty) * float(price)
                grand_total += total
                rows_html += (
                    f"<tr>"
                    f"<td style='border:1px solid #333;padding:6px'>{item.get('name','')}</td>"
                    f"<td style='border:1px solid #333;padding:6px'>{item.get('description','')}</td>"
                    f"<td style='border:1px solid #333;padding:6px'>{qty}</td>"
                    f"<td style='border:1px solid #333;padding:6px'>{float(price):.2f}</td>"
                    f"<td style='border:1px solid #333;padding:6px'>{total:.2f}</td>"
                    f"</tr>"
                )

        bg_style = ""
        if letterhead_url:
            bg_style = f"background-image: url('{letterhead_url}'); background-size: cover; background-position: center;"

        issued_date = work_order.issued_at.strftime("%B %d, %Y") if work_order.issued_at else "N/A"
        req_title = req.title if req else "N/A"
        vendor_name = vendor.company_name if vendor else "N/A"
        vendor_email = vendor.contact_email if vendor else ""

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            @page {{ margin: 40px; }}
            body {{ {bg_style} font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                   color: #1a1a1a; line-height: 1.5; }}
            .container {{ background: rgba(255,255,255,0.92); padding: 32px;
                          border-radius: 8px; min-height: 90vh; }}
            h1 {{ border-bottom: 2px solid #1a1a1a; padding-bottom: 8px;
                  font-size: 22px; margin-bottom: 20px; }}
            table.meta {{ width: 100%; font-size: 13px; margin-bottom: 20px; }}
            table.meta td {{ padding: 4px 0; }}
            table.items {{ border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 16px; }}
            table.items th {{ border: 1px solid #333; padding: 8px;
                              background: #e2e8f0; font-weight: 600; }}
            table.items td {{ border: 1px solid #333; padding: 6px; }}
            table.items tfoot td {{ font-weight: bold; background: #f8fafc; }}
            .wo-ref {{ font-size: 11px; color: #666; margin-bottom: 8px; }}
          </style>
        </head>
        <body>
          <div class="container">
            <p class="wo-ref">Work Order Ref: {work_order.id[:8].upper()} | Date: {issued_date}</p>
            <h1>Work Order / Purchase Order</h1>
            <table class="meta">
              <tr>
                <td><strong>Requisition:</strong> {req_title}</td>
                <td><strong>Supplier:</strong> {vendor_name}</td>
              </tr>
              <tr>
                <td><strong>Issued By:</strong> {work_order.issuer.full_name if work_order.issuer else 'N/A'}</td>
                <td><strong>Supplier Email:</strong> {vendor_email}</td>
              </tr>
            </table>

            {'<table class="items"><thead><tr>' +
             '<th>Item</th><th>Description</th><th>Qty</th><th>Unit Price</th><th>Total</th>' +
             '</tr></thead><tbody>' + rows_html +
             '</tbody><tfoot><tr><td colspan="4" style="text-align:right;border:1px solid #333;padding:6px">Grand Total:</td>' +
             f'<td style="border:1px solid #333;padding:6px">{grand_total:.2f}</td>' +
             '</tr></tfoot></table>'
             if rows_html else '<p><em>Item details as per quotation submitted.</em></p>'}

            <p style="margin-top:32px;font-size:12px;color:#666;">
              This work order is system-generated. Please proceed with delivery as per the agreed terms.
            </p>
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
