import sys

with open("app/quotations/routes_vendor.py", "r") as f:
    content = f.read()

import re

pattern = r'    try:\n        from app.email.resend import build_submission_notification, build_submission_confirmation, send_batch\n        email_params = \[\]\n.*?(?=    await db.commit\(\))'
replacement = """    # Send notification emails
    try:
        from app.email.resend import build_submission_notification, build_submission_confirmation, send_batch
        email_params = []

        # Generate PDF (best-effort, email sends even without it)
        pdf_bytes = _generate_quotation_pdf(
            form_data,
            req_title=link.requisition.title if link.requisition else "Quotation",
            vendor_name=link.vendor.company_name if link.vendor else "Supplier",
        )

        if link.requisition and link.requisition.creator and link.requisition.creator.email:
            view_url = f"{str(request.base_url).rstrip('/')}/quotations/detail/{link.id}"
            email_params.append(
                await build_submission_notification(
                    to=link.requisition.creator.email,
                    vendor_name=link.vendor.company_name if link.vendor else "Supplier",
                    requisition_title=link.requisition.title,
                    view_url=view_url,
                    pdf_bytes=pdf_bytes,  # None if generation failed — email sends without attachment
                )
            )

        if link.vendor and link.vendor.contact_email:
            email_params.append(
                await build_submission_confirmation(
                    to=link.vendor.contact_email,
                    vendor_name=link.vendor.contact_person or link.vendor.company_name,
                    requisition_title=link.requisition.title if link.requisition else "Quotation",
                )
            )

        if email_params:
            await send_batch(email_params)
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Failed to send submission emails: %s", e)

"""
new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

with open("app/quotations/routes_vendor.py", "w") as f:
    f.write(new_content)
