"""Renders a posted Goods Receipt as an A4 PDF
(docs/modules/purchase_orders.md #41, Revision 4) -- a second, equally
narrow PDF-generation capability built to the exact same shape as
app/services/purchase_order_pdf_service.py (docs/audit/PROCUREMENT_AUDIT.md
Revision 4 #11): no generic templating engine, no second letterhead
concept -- the same organisation name/address/contact fields.

Pure rendering: takes already-resolved, already-snapshotted data and
returns PDF bytes. Never queries the database itself, the same
"rendering stays dumb" boundary the PO PDF service already keeps."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.timezone import to_jdk_time

_TABLE_HEADER_BG = colors.HexColor("#1a1a28")
_TABLE_HEADER_FG = colors.white
_TABLE_GRID = colors.HexColor("#c9c9c9")


@dataclass
class PurchaseOrderReceiptPdfLine:
    material_name: str
    ordered_quantity: Decimal
    previously_received_quantity: Decimal
    received_quantity: Decimal
    unit_code: str | None


@dataclass
class PurchaseOrderReceiptPdfData:
    organisation_name: str
    organisation_address: str | None
    organisation_phone: str | None
    organisation_email: str | None
    receipt_number: str
    receipt_date: date
    po_number: str
    supplier_name: str
    supplier_delivery_reference: str | None
    notes: str | None
    receiver_name: str
    lines: list[PurchaseOrderReceiptPdfLine]
    posted_at: datetime


def generate_purchase_order_receipt_pdf(data: PurchaseOrderReceiptPdfData) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm
    )
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(data.organisation_name, styles["Title"]))
    letterhead_line = " &nbsp;|&nbsp; ".join(
        filter(None, [data.organisation_address, data.organisation_phone, data.organisation_email])
    )
    if letterhead_line:
        story.append(Paragraph(letterhead_line, styles["Normal"]))
    story.append(Spacer(1, 10 * mm))

    story.append(Paragraph(f"GOODS RECEIPT {data.receipt_number}", styles["Heading2"]))
    story.append(Spacer(1, 4 * mm))

    header_table = Table(
        [
            ["Receipt Date", data.receipt_date.strftime("%d-%m-%Y"), "Purchase Order", data.po_number],
            ["Supplier", data.supplier_name, "Received By", data.receiver_name],
            ["Supplier Delivery Ref.", data.supplier_delivery_reference or "—", "", ""],
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

    line_rows = [["Raw Material", "Ordered", "Previously Received", "This Receipt", "UOM"]]
    for line in data.lines:
        line_rows.append(
            [
                line.material_name,
                str(line.ordered_quantity),
                str(line.previously_received_quantity),
                str(line.received_quantity),
                line.unit_code or "—",
            ]
        )

    items_table = Table(line_rows, colWidths=[60 * mm, 30 * mm, 35 * mm, 30 * mm, 20 * mm])
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _TABLE_HEADER_BG),
                ("TEXTCOLOR", (0, 0), (-1, 0), _TABLE_HEADER_FG),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, _TABLE_GRID),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(items_table)

    if data.notes:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Notes", styles["Heading4"]))
        story.append(Paragraph(data.notes, styles["Normal"]))

    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(f"Posted {to_jdk_time(data.posted_at).strftime('%d-%m-%Y %H:%M')}", styles["Normal"]))

    doc.build(story)
    return buffer.getvalue()
