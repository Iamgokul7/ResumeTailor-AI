"""
pdf_service.py — Renders the tailored resume to a PDF via WeasyPrint.

Takes the Gemini-selected content dict + contact info from the bank,
fills the Jinja2 HTML template, converts to PDF via WeasyPrint,
saves to /output/, and returns the file path.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
TEMPLATE_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "output"


def absolute_url_filter(url: Any) -> str:
    if not url:
        return ""
    url_str = str(url).strip()
    if not url_str:
        return ""
    # Ensure it starts with an absolute URI scheme
    if url_str.startswith(("http://", "https://", "mailto:", "tel:")):
        return url_str
    # Standardize relative-looking domains/paths
    return "https://" + url_str


def display_url_filter(url: Any) -> str:
    if not url:
        return ""
    url_str = str(url).strip()
    if not url_str:
        return ""
    # Clean up prefixes and trailing slashes for clean presentation text
    if url_str.startswith("https://"):
        url_str = url_str[8:]
    elif url_str.startswith("http://"):
        url_str = url_str[7:]
    elif url_str.startswith("mailto:"):
        url_str = url_str[7:]
    elif url_str.startswith("tel:"):
        url_str = url_str[4:]
    return url_str.rstrip("/")


def render_pdf(
    tailored_data: dict[str, Any],
    contact: dict[str, str],
    simple_layout: bool = False,
) -> Path:
    """
    Render *tailored_data* into a PDF resume and save it to /output/.

    Args:
        tailored_data: Parsed JSON from gemini_service.tailor_resume().
        contact:       The ``contact`` section from resume_bank.json.
        simple_layout: True to render using a simplified ATS-safe template.

    Returns:
        Absolute path to the generated PDF file.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Build Jinja2 context
    context: dict[str, Any] = {
        "contact": contact,
        **tailored_data,
    }

    # Render HTML
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["absolute_url"] = absolute_url_filter
    env.filters["display_url"] = display_url_filter
    
    template_name = "resume_template_simple.html" if simple_layout else "resume_template.html"
    template = env.get_template(template_name)
    rendered_html = template.render(**context)

    # Convert to PDF via WeasyPrint
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"resume_{timestamp}.pdf"

    logger.info("Rendering PDF with WeasyPrint → %s", output_path)
    _render_with_weasyprint(rendered_html, output_path)
    logger.info("PDF written (%d bytes).", output_path.stat().st_size)

    return output_path


def _render_with_weasyprint(html: str, output_path: Path) -> None:
    """Use WeasyPrint to convert HTML string → PDF file, falling back to xhtml2pdf if GTK3 is missing."""
    import os
    # Add GTK3 runtime path if not already in PATH (common paths for Windows installer)
    gtk_bin = r"C:\Program Files\GTK3-Runtime\bin"
    if os.path.exists(gtk_bin) and gtk_bin not in os.environ["PATH"]:
        os.environ["PATH"] = gtk_bin + os.path.pathsep + os.environ["PATH"]

    try:
        from weasyprint import HTML  # type: ignore
        HTML(string=html).write_pdf(target=output_path)
    except OSError as exc:
        logger.warning("WeasyPrint could not load (possibly missing GTK3). Falling back to xhtml2pdf: %s", exc)
        from xhtml2pdf import pisa  # type: ignore
        with open(output_path, "wb") as f:
            pisa_status = pisa.CreatePDF(html, dest=f)
        if pisa_status.err:
            raise RuntimeError(f"xhtml2pdf rendering failed with status {pisa_status.err}")

