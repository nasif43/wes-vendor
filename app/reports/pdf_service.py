import logging
from weasyprint import HTML

logger = logging.getLogger(__name__)

def generate_pdf_from_html(html_content: str) -> bytes | None:
    """Generate a PDF from raw HTML string using WeasyPrint."""
    try:
        pdf_bytes = HTML(string=html_content).write_pdf()
        return pdf_bytes
    except Exception as exc:
        logger.exception("generate_pdf_from_html failed: %s", exc)
        return None
