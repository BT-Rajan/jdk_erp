from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
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

# docs/modules/rfq.md #9. response_received is never a direct transition
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

# docs/modules/rfq.md #2 -- a plain filter/sort/badge hint, never a
# workflow: nothing server-side behaves differently for `urgent`.
PRIORITY_NORMAL = "normal"
PRIORITY_URGENT = "urgent"
RFQ_PRIORITIES = (PRIORITY_NORMAL, PRIORITY_URGENT)

# docs/modules/rfq.md #4. `quoted` is only ever the side effect of a
# captured response; `declined` is a manual flag with no further
# behaviour.
INVITATION_SENT = "sent"
INVITATION_QUOTED = "quoted"
INVITATION_DECLINED = "declined"
INVITATION_STATUSES = (INVITATION_SENT, INVITATION_QUOTED, INVITATION_DECLINED)


class Rfq(Base, TimestampMixin, OrganisationScopedMixin):
    """The company's request for pricing/availability on specified raw
    materials, before any Purchase Order commitment exists
    (docs/modules/rfq.md, v2 -- docs/audit/RFQ_AUDIT_V2.md).

    No `supplier_id` on the header: who was asked lives on
    `RfqSupplierInvitation` rows (one or several per RFQ, #4), and the PO
    supplier comes from the selected response's invitation (#8).

    `team_id` reuses the existing `teams` table as the requesting
    department (docs/modules/teams.md). `requested_by_user_id` is stamped
    from the session user at creation and never edited. `priority` is
    display/filter only.

    Decision fields live flat on the header -- a decision is one
    explicit, auditable action, not an approval chain (#7).
    `purchase_order_id` is set only once conversion succeeds (#8)."""

    __tablename__ = "rfqs"
    __table_args__ = (UniqueConstraint("organisation_id", "rfq_number", name="uq_rfqs_organisation_id_rfq_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rfq_number: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=DRAFT, server_default=DRAFT)
    # 0 while a draft has never been submitted; each submit (first issue,
    # or a revision of an issued RFQ before any quote) adds one and
    # generates a fresh PDF per supplier -- earlier PDFs are kept.
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    priority: Mapped[str] = mapped_column(
        String(10), nullable=False, default=PRIORITY_NORMAL, server_default=PRIORITY_NORMAL
    )
    rfq_date: Mapped[date] = mapped_column(Date, nullable=False)
    required_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # use_alter=True: rfqs.selected_response_id -> rfq_responses ->
    # rfq_supplier_invitations -> rfqs is a FK cycle -- this defers the
    # constraint to an ALTER TABLE after all tables exist (mirrored in
    # migration 0028, which adds it only after rfq_responses exists).
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
    """One requested Raw Material in its requested unit
    (docs/modules/rfq.md #3). No price field -- an RFQ line is a request, never a commitment.
    `remarks` is a free-text grade/size/quality note on the request
    itself. No `organisation_id` of its own -- a child of an already
    organisation-scoped `Rfq`."""

    __tablename__ = "rfq_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_material_id: Mapped[int] = mapped_column(
        ForeignKey("raw_materials.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # The unit the quantity is requested in -- defaults to the material's
    # own unit, and is only ever accepted when it converts to that unit
    # (app/services/uom_conversion.py), so conversion to a PO never fails.
    unit_of_measure_id: Mapped[int] = mapped_column(
        ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    required_by_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)


class RfqSupplierInvitation(Base, TimestampMixin):
    """One invited supplier on one RFQ (docs/modules/rfq.md #4) -- a plain
    join row, not a bidding round or procurement event. `supplier_id` is
    immutable after creation; a supplier can be invited at most once per
    RFQ. No `organisation_id` of its own -- a child of an already
    organisation-scoped `Rfq`, same shape as `rfq_lines`."""

    __tablename__ = "rfq_supplier_invitations"
    __table_args__ = (
        UniqueConstraint("rfq_id", "supplier_id", name="uq_rfq_supplier_invitations_rfq_id_supplier_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=INVITATION_SENT, server_default=INVITATION_SENT
    )
    invited_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    last_emailed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RfqResponse(Base, TimestampMixin, OrganisationScopedMixin):
    """What one invited supplier actually offered, captured as structured,
    comparable data (docs/modules/rfq.md #5), with optional attached
    files (`entity_type="rfq_response"`) as supporting evidence. Always
    belongs to exactly one invitation, never directly to an Rfq. Never
    edited after creation -- a revised quote is a new row against the
    same invitation (#12). Keeps `organisation_id` so the file access
    checker can resolve isolation without a join."""

    __tablename__ = "rfq_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    invitation_id: Mapped[int] = mapped_column(
        ForeignKey("rfq_supplier_invitations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    response_received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    supplier_quotation_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    quotation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_terms: Mapped[str | None] = mapped_column(String(255), nullable=True)
    freight_terms: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class RfqResponseLine(Base, TimestampMixin):
    """One quoted price for one `RfqLine` within one response
    (docs/modules/rfq.md #5). A response need not quote every line, but
    each line it does quote must belong to the same RFQ (enforced in
    app/services/rfq_service.capture_response) and appears at most once.
    No `organisation_id` -- a child of an already-scoped `RfqResponse`."""

    __tablename__ = "rfq_response_lines"
    __table_args__ = (
        UniqueConstraint("response_id", "rfq_line_id", name="uq_rfq_response_lines_response_id_rfq_line_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    response_id: Mapped[int] = mapped_column(
        ForeignKey("rfq_responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rfq_line_id: Mapped[int] = mapped_column(ForeignKey("rfq_lines.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    delivery_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
