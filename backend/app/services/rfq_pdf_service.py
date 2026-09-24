"""Renders one supplier's copy of an RFQ as an A4 PDF on the
organisation's letterhead (docs/modules/rfq.md #11). Same reportlab
approach as app/services/purchase_order_pdf_service.py.

The letterhead is the admin-configured full-page image
(app/models/document_template.py) drawn behind every page, with the
configured top/bottom margins keeping content clear of it. With no
letterhead configured, the organisation's name/address is printed as a
plain text header instead, the same fallback the PO document uses.

Pure rendering: takes already-resolved data, returns PDF bytes."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_TABLE_HEADER_BG = colors.HexColor("#1a1a28")
_TABLE_GRID = colors.HexColor("#c9c9c9")


@dataclass
class RfqPdfLine:
    material_name: str
    quantity: Decimal
    unit_code: str
    required_by_date: date | None
    remarks: str | None


@dataclass
class RfqPdfData:
    organisation_name: str
    organisation_address: str | None
    organisation_phone: str | None
    organisation_email: str | None
    rfq_number: str
    revision_number: int
    rfq_date: date
    required_delivery_date: date | None
    requested_by: str | None
    priority: str
    notes: str | None
    supplier_name: str
    supplier_address: str | None
    supplier_contact_person: str | None
    supplier_email: str | None
    lines: list[RfqPdfLine]
    letterhead_image: bytes | None = None
    margin_top_mm: int = 40
    margin_bottom_mm: int = 25
    intro_text: str | None = None
    terms_text: str | None = None
    signature_text: str | None = None


def _paragraphs(text: str, style) -> list[Paragraph]:
    """User-entered text rendered safely: escaped (reportlab Paragraph
    parses markup), one Paragraph per line."""
    return [Paragraph(escape(line) or "&nbsp;", style) for line in text.splitlines()]


def _fmt_quantity(value: Decimal) -> str:
    return f"{value.normalize():,f}"


def generate_rfq_pdf(data: RfqPdfData) -> bytes:
    buffer = BytesIO()
    letterhead = ImageReader(BytesIO(data.letterhead_image)) if data.letterhead_image else None
    top = data.margin_top_mm if letterhead else 18
    bottom = data.margin_bottom_mm if letterhead else 18
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, topMargin=top * mm, bottomMargin=bottom * mm, leftMargin=18 * mm, rightMargin=18 * mm,
        title=f"RFQ {data.rfq_number} Rev {data.revision_number}",
    )
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    story = []

    if letterhead is None:
        story.append(Paragraph(escape(data.organisation_name), styles["Title"]))
        letterhead_line = " | ".join(
            filter(None, [data.organisation_address, data.organisation_phone, data.organisation_email])
        )
        if letterhead_line:
            story.append(Paragraph(escape(letterhead_line), normal))
        story.append(Spacer(1, 8 * mm))

    story.append(
        Paragraph(
            f"REQUEST FOR QUOTATION &nbsp; {escape(data.rfq_number)} &nbsp; (Rev {data.revision_number})",
            styles["Heading2"],
        )
    )
    story.append(Spacer(1, 3 * mm))

    header_table = Table(
        [
            ["RFQ Date", data.rfq_date.strftime("%d-%m-%Y"), "Required By",
             data.required_delivery_date.strftime("%d-%m-%Y") if data.required_delivery_date else "-"],
            ["Requested By", data.requested_by or "-", "Priority", data.priority.capitalize()],
        ],
        colWidths=[30 * mm, 60 * mm, 30 * mm, 54 * mm],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 5 * mm))

    story.append(Paragraph("To", styles["Heading4"]))
    story.append(Paragraph(escape(data.supplier_name), normal))
    for extra in (data.supplier_contact_person, data.supplier_address, data.supplier_email):
        if extra:
            story.extend(_paragraphs(extra, normal))
    story.append(Spacer(1, 5 * mm))

    if data.intro_text:
        story.extend(_paragraphs(data.intro_text, normal))
        story.append(Spacer(1, 4 * mm))

    cell = styles["BodyText"]
    cell.fontSize = 9
    cell.leading = 11
    rows = [["#", "Product / Material", "Quantity", "UOM", "Required By", "Specification / Remarks"]]
    for index, line in enumerate(data.lines, start=1):
        rows.append(
            [
                str(index),
                Paragraph(escape(line.material_name), cell),
                _fmt_quantity(line.quantity),
                line.unit_code,
                line.required_by_date.strftime("%d-%m-%Y") if line.required_by_date else "-",
                Paragraph(escape(line.remarks or ""), cell),
            ]
        )
    items = Table(rows, colWidths=[8 * mm, 52 * mm, 24 * mm, 16 * mm, 24 * mm, 50 * mm], repeatRows=1)
    items.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _TABLE_HEADER_BG),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, _TABLE_GRID),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(items)

    if data.notes:
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph("Notes", styles["Heading4"]))
        story.extend(_paragraphs(data.notes, normal))

    if data.terms_text:
        story.append(Spacer(1, 5 * mm))
        story.extend(_paragraphs(data.terms_text, normal))

    if data.signature_text:
        story.append(Spacer(1, 10 * mm))
        story.extend(_paragraphs(data.signature_text, normal))

    def _draw_letterhead(canvas, _doc) -> None:
        if letterhead is not None:
            width, height = A4
            canvas.drawImage(letterhead, 0, 0, width=width, height=height, preserveAspectRatio=False, mask="auto")

    doc.build(story, onFirstPage=_draw_letterhead, onLaterPages=_draw_letterhead)
    return buffer.getvalue()
