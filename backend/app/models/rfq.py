from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

DRAFT = "draft"
ISSUED = "issued"
RESPONSE_RECEIVED = "response_received"
SELECTED = "selected"
REJECTED = "rejected"
CANCELLED = "cancelled"
CONVERTED = "converted"
RFQ_STATUSES = (DRAFT, ISSUED, RESPONSE_RECEIVED, SELECTED, REJECTED, CANCELLED, CONVERTED)

# docs/modules/rfq.md #3. response_received is never a direct transition
# target -- it's the side effect app/services/rfq_service.capture_response
# applies, the same "side effect of an action, never a direct
# status-change target" discipline app/models/purchase_order.py already
# established for partially_received/fully_received. selected/rejected
# are only reached via the explicit decide action; converted only via
# the convert-to-PO action.
ALLOWED_STATUS_TRANSITIONS = {
    DRAFT: {ISSUED, CANCELLED},
    ISSUED: {CANCELLED},
    RESPONSE_RECEIVED: {CANCELLED},
    SELECTED: {CANCELLED, CONVERTED},
    REJECTED: set(),
    CANCELLED: set(),
    CONVERTED: set(),
}


class Rfq(Base, TimestampMixin, OrganisationScopedMixin):
    """The company's request to one supplier for pricing/availability on
    specified raw materials, before any Purchase Order commitment exists
    (docs/modules/rfq.md) -- audited against jdk_clean first
    (docs/audit/RFQ_AUDIT.md), which has no RFQ concept at all.

    `supplier_id` is immutable after creation, the same discipline
    `PurchaseOrder.supplier_id` already established -- one RFQ is always
    for exactly one supplier (docs/modules/rfq.md #10); no vendor-
    comparison/bidding model is built.

    Decision fields (`decided_by_user_id`/`decided_at`/`decision_note`/
    `selected_response_id`) live flat on the header rather than a
    separate entity -- a decision is one explicit, auditable action, not
    an approval chain (docs/modules/rfq.md #6). `purchase_order_id` is
    set only once `convert_to_purchase_order` succeeds
    (docs/modules/rfq.md #8) -- never editable directly."""

    __tablename__ = "rfqs"
    __table_args__ = (UniqueConstraint("organisation_id", "rfq_number", name="uq_rfqs_organisation_id_rfq_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rfq_number: Mapped[str] = mapped_column(String(10), nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=DRAFT, server_default=DRAFT)
    rfq_date: Mapped[date] = mapped_column(Date, nullable=False)
    required_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # use_alter=True: rfqs.selected_response_id and rfq_responses.rfq_id
    # form a circular FK pair -- this defers the constraint to an ALTER
    # TABLE after both tables exist, the standard SQLAlchemy way to break
    # a two-table dependency cycle (mirrored in the migration, which adds
    # this same constraint only after rfq_responses is created).
    selected_response_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "rfq_responses.id", ondelete="SET NULL", use_alter=True, name="fk_rfqs_selected_response_id_rfq_responses"
        ),
        nullable=True,
        index=True,
    )
    purchase_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="SET NULL"), nullable=True, index=True
    )


class RfqLine(Base, TimestampMixin):
    """One requested Raw Material, in the material's own
    `unit_of_measure_id` -- no purchase UoM, the same decision
    docs/modules/purchase_orders.md #5 already made, applying here for
    the identical reason (docs/modules/rfq.md #2). No price field -- an
    RFQ line is a request, never a commitment. No `organisation_id` of
    its own -- a child of an already organisation-scoped `Rfq`, the same
    shape `purchase_order_lines` already uses."""

    __tablename__ = "rfq_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_material_id: Mapped[int] = mapped_column(
        ForeignKey("raw_materials.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)


class RfqResponse(Base, TimestampMixin, OrganisationScopedMixin):
    """Evidence that the supplier responded, not a re-typed structured
    quotation (docs/modules/rfq.md #5) -- the attached file(s) (linked
    via the existing generic `files` table, `entity_type="rfq_response"`)
    *are* the record of what was offered. Multiple rows per Rfq are
    supported (a revised quote later is a new row, never an edit to this
    one -- docs/modules/rfq.md #9's historical-integrity rule), always
    for the same supplier the Rfq itself already names."""

    __tablename__ = "rfq_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False, index=True)
    response_received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
