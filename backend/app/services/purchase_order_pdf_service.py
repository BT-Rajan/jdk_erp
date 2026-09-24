"""Renders a Purchase Order revision as an A4 PDF
(docs/modules/purchase_orders.md #27) -- the one PDF-generation
capability in this codebase (docs/audit/PROCUREMENT_AUDIT.md Revision 2
#2), built narrowly for this one document rather than a generic
templating engine. The "letterhead" is the organisation's own existing
name/address/contact fields (app/models/organisation.py) -- no separate
template/admin entity exists or is built here (Revision 2 #3).

Pure rendering: takes already-resolved, already-snapshotted data (a
PurchaseOrderRevision row plus a list of (material_name, quantity,
unit_price, line_total) tuples) and returns PDF bytes. Never queries the
database itself -- the caller (app/api/purchase_orders.py) resolves
everything first, the same "rendering stays dumb" boundary this codebase
already keeps between API/service layers and pure helpers."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

_TABLE_HEADER_BG = colors.HexColor("#1a1a28")
_TABLE_HEADER_FG = colors.white
_TABLE_GRID = colors.HexColor("#c9c9c9")


@dataclass
class PurchaseOrderPdfLine:
    material_name: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    unit_code: str = ""
    remarks: str | None = None


@dataclass
class PurchaseOrderPdfData:
    organisation_name: str
    organisation_address: str | None
    organisation_phone: str | None
    organisation_email: str | None
    po_number: str
    revision_number: int
    order_date: date
    expected_delivery_date: date | None
    supplier_reference: str | None
    payment_terms: str | None
    notes: str | None
    supplier_name: str
    supplier_address: str | None
    supplier_contact_person: str | None
    supplier_phone: str | None
    supplier_email: str | None
    lines: list[PurchaseOrderPdfLine]
    total_amount: Decimal
    issued_at: datetime
    currency: str = "KWD"
    delivery_location: str | None = None
    delivery_instructions: str | None = None
    rfq_reference: str | None = None
    approved_by: str | None = None


def generate_purchase_order_pdf(data: PurchaseOrderPdfData) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm
    )
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(escape(data.organisation_name), styles["Title"]))
    letterhead_line = " &nbsp;|&nbsp; ".join(
        escape(part) for part in filter(None, [data.organisation_address, data.organisation_phone, data.organisation_email])
    )
    if letterhead_line:
        story.append(Paragraph(letterhead_line, styles["Normal"]))
    story.append(Spacer(1, 10 * mm))

    story.append(Paragraph(f"PURCHASE ORDER {data.po_number} &nbsp; (Revision {data.revision_number})", styles["Heading2"]))
    story.append(Spacer(1, 4 * mm))

    header_table = Table(
        [
            ["PO Date", str(data.order_date), "Expected Delivery", str(data.expected_delivery_date or "—")],
            [
                "Supplier Reference",
                data.supplier_reference or "—",
                "Payment Terms",
                data.payment_terms or "—",
            ],
            ["Currency", data.currency, "Delivery Location", data.delivery_location or "—"],
            ["RFQ Reference", data.rfq_reference or "—", "Approved By", data.approved_by or "—"],
        ],
        colWidths=[38 * mm, 55 * mm, 38 * mm, 55 * mm],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph("Supplier", styles["Heading4"]))
    story.append(Paragraph(escape(data.supplier_name), styles["Normal"]))
    if data.supplier_address:
        story.append(Paragraph(escape(data.supplier_address), styles["Normal"]))
    supplier_contact = ", ".join(filter(None, [data.supplier_contact_person, data.supplier_phone, data.supplier_email]))
    if supplier_contact:
        story.append(Paragraph(escape(supplier_contact), styles["Normal"]))
    story.append(Spacer(1, 6 * mm))

    line_rows = [["Material", "Qty", "UOM", "Unit Price", "Total"]]
    for line in data.lines:
        name = escape(line.material_name) + (f"<br/><font size=7>{escape(line.remarks)}</font>" if line.remarks else "")
        line_rows.append(
            [Paragraph(name, styles["BodyText"]), f"{line.quantity.normalize():,f}", line.unit_code,
             f"{line.unit_price:,.3f}", f"{line.line_total:,.3f}"]
        )
    line_rows.append(["", "", "", "Total", f"{data.total_amount:,.3f} {data.currency}"])

    items_table = Table(line_rows, colWidths=[70 * mm, 25 * mm, 18 * mm, 30 * mm, 37 * mm])
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _TABLE_HEADER_BG),
                ("TEXTCOLOR", (0, 0), (-1, 0), _TABLE_HEADER_FG),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (2, -1), (-1, -1), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -2), 0.5, _TABLE_GRID),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(items_table)

    if data.delivery_instructions:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Delivery Instructions", styles["Heading4"]))
        story.append(Paragraph(escape(data.delivery_instructions), styles["Normal"]))

    if data.notes:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Notes", styles["Heading4"]))
        story.append(Paragraph(escape(data.notes), styles["Normal"]))

    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(f"Issued {data.issued_at.strftime('%d %b %Y %H:%M')}", styles["Normal"]))

    doc.build(story)
    return buffer.getvalue()
