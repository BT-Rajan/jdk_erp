"""Generated Sales documents -- Quotation, Order Confirmation (Sales
Order) and Delivery Note -- stored exactly like the RFQ and PO PDFs: a
FileRecord linked to its record (entity_type/entity_id) through
file_service.upload_file, downloaded through the one files endpoint
(GET /api/files/{id}), whose access follows the record's own rules
(the checks registered by each module's API).

When they are rendered (decided with the business):
- Quotation: on every save (create, edit, renew);
- Sales Order: on creation and after every Admin edit;
- Delivery Note: on Delivery Instruction creation and every shipment
  change while pending -- nothing changes after fulfilment, so the last
  one is final.
Each render is a new FileRecord; earlier ones are kept and the latest
is the document offered for download.

Letterhead and margins come from the RFQ document template (the only
one configured); its RFQ wording (intro/terms/signature) is not used.

`store_*` calls file_service.upload_file, which commits: callers log
their audit events first so the record, its audit trail and its PDF
land in one commit (the RFQ/PO pattern)."""

import io
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.storage import default_storage
from app.core.timezone import to_jdk_time
from app.models.customer import Customer
from app.models.delivery_instruction import DeliveryInstruction
from app.models.document_template import RFQ_DOCUMENT, DocumentTemplate
from app.models.file import FileRecord
from app.models.organisation import Organisation
from app.models.product import Product
from app.models.quotation import Quotation
from app.models.sales_order import SalesOrder
from app.models.unit import UnitOfMeasure
from app.services import file_service
from app.services.sales_document_pdf_service import (
    SalesDocumentColumn,
    SalesDocumentPdfData,
    generate_sales_document_pdf,
)

QUOTATION_PDF = "quotation_pdf"
SALES_ORDER_PDF = "sales_order_pdf"
DELIVERY_NOTE_PDF = "delivery_note_pdf"


def latest_pdf(db: Session, entity_type: str, entity_id: int) -> FileRecord | None:
    return (
        db.query(FileRecord)
        .filter(FileRecord.entity_type == entity_type, FileRecord.entity_id == entity_id, FileRecord.deleted_at.is_(None))
        .order_by(FileRecord.id.desc())
        .first()
    )


def _letterhead(db: Session, organisation_id: int) -> tuple[bytes | None, int, int]:
    template = (
        db.query(DocumentTemplate)
        .filter(DocumentTemplate.organisation_id == organisation_id, DocumentTemplate.document_type == RFQ_DOCUMENT)
        .first()
    )
    if template is None:
        return None, 40, 25
    image = None
    if template.letterhead_file_id is not None:
        record = (
            db.query(FileRecord)
            .filter(
                FileRecord.id == template.letterhead_file_id,
                FileRecord.organisation_id == organisation_id,
                FileRecord.deleted_at.is_(None),
            )
            .first()
        )
        if record is not None:
            image = b"".join(default_storage.download(record.storage_key))
    return image, template.margin_top_mm, template.margin_bottom_mm


def _base(db: Session, organisation_id: int, customer_id: int) -> dict:
    organisation = db.query(Organisation).filter(Organisation.id == organisation_id).one()
    customer = db.query(Customer).filter(Customer.id == customer_id).one()
    image, top, bottom = _letterhead(db, organisation_id)
    return dict(
        organisation_name=organisation.name,
        organisation_address=organisation.address,
        organisation_phone=organisation.contact_phone,
        organisation_email=organisation.contact_email,
        customer_name=customer.name,
        customer_details=[customer.contact_person, customer.address, customer.phone, customer.email],
        letterhead_image=image,
        margin_top_mm=top,
        margin_bottom_mm=bottom,
    )


def _names(db: Session, lines) -> tuple[dict[int, str], dict[int, str]]:
    products = {p.id: p.name for p in db.query(Product).filter(Product.id.in_({line.product_id for line in lines}))}
    units = {
        u.id: u.code
        for u in db.query(UnitOfMeasure).filter(UnitOfMeasure.id.in_({line.unit_of_measure_id for line in lines}))
    }
    return products, units


def _quantity(value: Decimal) -> str:
    return f"{value.normalize():,f}"


def _money(value: Decimal) -> str:
    return f"{value:,.3f}"


def _date(value) -> str:
    return value.strftime("%d-%m-%Y") if value else "-"


_PRICED_COLUMNS = [
    SalesDocumentColumn("#", 8),
    SalesDocumentColumn("Product", 62, wrap=True),
    SalesDocumentColumn("Quantity", 24, align_right=True),
    SalesDocumentColumn("Unit", 16),
    SalesDocumentColumn("Unit Price", 30, align_right=True),
    SalesDocumentColumn("Amount", 34, align_right=True),
]


def _priced_rows(db: Session, lines) -> list[list[str]]:
    products, units = _names(db, lines)
    return [
        [
            str(line.line_number),
            products.get(line.product_id, f"#{line.product_id}"),
            _quantity(line.quantity),
            units.get(line.unit_of_measure_id, ""),
            _money(line.unit_price),
            _money(line.line_amount),
        ]
        for line in sorted(lines, key=lambda line: line.line_number)
    ]


def _store(db: Session, organisation_id: int, user_id: int, filename: str, pdf: bytes, entity_type: str, entity_id: int) -> FileRecord:
    return file_service.upload_file(
        db,
        organisation_id=organisation_id,
        uploaded_by_user_id=user_id,
        filename=filename,
        stream=io.BytesIO(pdf),
        entity_type=entity_type,
        entity_id=entity_id,
    )


def render_quotation(db: Session, quotation: Quotation) -> bytes:
    return generate_sales_document_pdf(
        SalesDocumentPdfData(
            **_base(db, quotation.organisation_id, quotation.customer_id),
            title="Quotation",
            number=quotation.quotation_number,
            header=[
                ("Quotation Date", _date(quotation.quotation_date)),
                ("Valid Until", _date(quotation.valid_until)),
                ("Requested Delivery", _date(quotation.requested_delivery_date)),
                ("Currency", quotation.currency),
            ],
            columns=_PRICED_COLUMNS,
            rows=_priced_rows(db, quotation.lines),
            totals=[
                ("Subtotal", f"{_money(quotation.subtotal_amount)} {quotation.currency}"),
                ("Total", f"{_money(quotation.total_amount)} {quotation.currency}"),
            ],
        )
    )


def store_quotation_pdf(db: Session, quotation: Quotation, user_id: int) -> FileRecord:
    db.flush()
    db.refresh(quotation)
    return _store(
        db, quotation.organisation_id, user_id, f"Quotation-{quotation.quotation_number}.pdf",
        render_quotation(db, quotation), QUOTATION_PDF, quotation.id,
    )


def render_sales_order(db: Session, order: SalesOrder) -> bytes:
    quotation_number = db.query(Quotation.quotation_number).filter(Quotation.id == order.quotation_id).scalar()
    return generate_sales_document_pdf(
        SalesDocumentPdfData(
            **_base(db, order.organisation_id, order.customer_id),
            title="Order Confirmation",
            number=order.order_number,
            header=[
                ("Order Date", _date(order.order_date)),
                ("Quotation", quotation_number or "-"),
                ("Requested Delivery", _date(order.requested_delivery_date)),
                ("Currency", order.currency),
            ],
            columns=_PRICED_COLUMNS,
            rows=_priced_rows(db, order.lines),
            totals=[
                ("Subtotal", f"{_money(order.subtotal_amount)} {order.currency}"),
                ("Total", f"{_money(order.total_amount)} {order.currency}"),
            ],
        )
    )


def store_sales_order_pdf(db: Session, order: SalesOrder, user_id: int) -> FileRecord:
    db.flush()
    db.refresh(order)
    return _store(
        db, order.organisation_id, user_id, f"Order-Confirmation-{order.order_number}.pdf",
        render_sales_order(db, order), SALES_ORDER_PDF, order.id,
    )


_DELIVERY_COLUMNS = [
    SalesDocumentColumn("#", 8),
    SalesDocumentColumn("Product", 86, wrap=True),
    SalesDocumentColumn("Quantity", 30, align_right=True),
    SalesDocumentColumn("Unit", 22),
    SalesDocumentColumn("Pallets", 28, align_right=True),
]


def render_delivery_note(db: Session, instruction: DeliveryInstruction) -> bytes:
    """Quantities only -- no prices (decided with the business)."""
    order = db.query(SalesOrder).filter(SalesOrder.id == instruction.sales_order_id).one()
    products, units = _names(db, instruction.lines)
    return generate_sales_document_pdf(
        SalesDocumentPdfData(
            **_base(db, instruction.organisation_id, instruction.customer_id),
            title="Delivery Note",
            number=instruction.delivery_number,
            header=[
                ("Date", _date(to_jdk_time(instruction.created_at))),
                ("Sales Order", order.order_number),
                ("Requested Delivery", _date(order.requested_delivery_date)),
            ],
            columns=_DELIVERY_COLUMNS,
            rows=[
                [
                    str(index),
                    products.get(line.product_id, f"#{line.product_id}"),
                    _quantity(line.quantity),
                    units.get(line.unit_of_measure_id, ""),
                    str(line.pallet_count) if line.pallet_count is not None else "-",
                ]
                for index, line in enumerate(sorted(instruction.lines, key=lambda line: line.id), start=1)
            ],
            signatures=["Delivered by", "Received by (customer)"],
        )
    )


def store_delivery_note_pdf(db: Session, instruction: DeliveryInstruction, user_id: int) -> FileRecord:
    db.flush()
    db.refresh(instruction)
    return _store(
        db, instruction.organisation_id, user_id, f"Delivery-Note-{instruction.delivery_number}.pdf",
        render_delivery_note(db, instruction), DELIVERY_NOTE_PDF, instruction.id,
    )
