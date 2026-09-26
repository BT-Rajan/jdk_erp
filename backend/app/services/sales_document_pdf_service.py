"""Renders the Sales documents -- Quotation, Order Confirmation (Sales
Order) and Delivery Note -- as A4 PDFs. Same reportlab approach and
letterhead handling as app/services/rfq_pdf_service.py: the configured
full-page letterhead image is drawn behind every page with its margins,
or, without one, the organisation's name/address is printed as a plain
text header.

One layout serves all three documents: a title and number, a small
header table, the customer block, an items table, optional totals and
optional signature blocks. Which columns, totals and signatures a
document has is decided by its caller
(app/services/sales_document_service.py).

Pure rendering: takes already-resolved data, returns PDF bytes."""

from dataclasses import dataclass, field
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
_CONTENT_WIDTH_MM = 174  # A4 (210) less 18 mm each side


@dataclass
class SalesDocumentColumn:
    label: str
    width_mm: float
    align_right: bool = False
    # Wrapped text (product names); other cells are plain strings.
    wrap: bool = False


@dataclass
class SalesDocumentPdfData:
    organisation_name: str
    organisation_address: str | None
    organisation_phone: str | None
    organisation_email: str | None
    title: str
    number: str
    # Label/value pairs shown two per row under the title.
    header: list[tuple[str, str]]
    customer_name: str
    customer_details: list[str]
    columns: list[SalesDocumentColumn]
    rows: list[list[str]]
    totals: list[tuple[str, str]] = field(default_factory=list)
    notes: str | None = None
    # Captions of the signature blocks printed at the end ("Received by").
    signatures: list[str] = field(default_factory=list)
    letterhead_image: bytes | None = None
    margin_top_mm: int = 40
    margin_bottom_mm: int = 25


def _paragraphs(text: str, style) -> list[Paragraph]:
    """User-entered text rendered safely: escaped (reportlab Paragraph
    parses markup), one Paragraph per line."""
    return [Paragraph(escape(line) or "&nbsp;", style) for line in text.splitlines()]


def generate_sales_document_pdf(data: SalesDocumentPdfData) -> bytes:
    buffer = BytesIO()
    letterhead = ImageReader(BytesIO(data.letterhead_image)) if data.letterhead_image else None
    top = data.margin_top_mm if letterhead else 18
    bottom = data.margin_bottom_mm if letterhead else 18
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, topMargin=top * mm, bottomMargin=bottom * mm, leftMargin=18 * mm, rightMargin=18 * mm,
        title=f"{data.title} {data.number}",
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

    story.append(Paragraph(f"{escape(data.title.upper())} &nbsp; {escape(data.number)}", styles["Heading2"]))
    story.append(Spacer(1, 3 * mm))

    header_rows = []
    for index in range(0, len(data.header), 2):
        pair = data.header[index:index + 2]
        row = [value for item in pair for value in item]
        header_rows.append(row + [""] * (4 - len(row)))
    if header_rows:
        header_table = Table(header_rows, colWidths=[34 * mm, 53 * mm, 34 * mm, 53 * mm])
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

    story.append(Paragraph("Customer", styles["Heading4"]))
    story.append(Paragraph(escape(data.customer_name), normal))
    for extra in data.customer_details:
        if extra:
            story.extend(_paragraphs(extra, normal))
    story.append(Spacer(1, 5 * mm))

    cell = styles["BodyText"]
    cell.fontSize = 9
    cell.leading = 11
    rows: list[list] = [[column.label for column in data.columns]]
    for values in data.rows:
        rows.append(
            [Paragraph(escape(value), cell) if column.wrap else value for column, value in zip(data.columns, values)]
        )
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, _TABLE_GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    style.extend(("ALIGN", (i, 0), (i, -1), "RIGHT") for i, column in enumerate(data.columns) if column.align_right)
    items = Table(rows, colWidths=[column.width_mm * mm for column in data.columns], repeatRows=1)
    items.setStyle(TableStyle(style))
    story.append(items)

    if data.totals:
        story.append(Spacer(1, 3 * mm))
        totals = Table(
            [[label, value] for label, value in data.totals],
            colWidths=[(_CONTENT_WIDTH_MM - 40) * mm, 40 * mm],
        )
        totals.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ]
            )
        )
        story.append(totals)

    if data.notes:
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph("Notes", styles["Heading4"]))
        story.extend(_paragraphs(data.notes, normal))

    if data.signatures:
        story.append(Spacer(1, 15 * mm))
        width = _CONTENT_WIDTH_MM / len(data.signatures)
        signatures = Table(
            [["_" * 28 for _ in data.signatures], data.signatures, ["Name / Date" for _ in data.signatures]],
            colWidths=[width * mm for _ in data.signatures],
        )
        signatures.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
        story.append(signatures)

    def _draw_letterhead(canvas, _doc) -> None:
        if letterhead is not None:
            width, height = A4
            canvas.drawImage(letterhead, 0, 0, width=width, height=height, preserveAspectRatio=False, mask="auto")

    doc.build(story, onFirstPage=_draw_letterhead, onLaterPages=_draw_letterhead)
    return buffer.getvalue()
