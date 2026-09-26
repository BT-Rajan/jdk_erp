from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

# Payment arrangements Admin may set on a customer (S0.2 / S14.2).
PAYMENT_BEFORE_DELIVERY = "before_delivery"
PAYMENT_AFTER_DELIVERY = "after_delivery"
PAYMENT_PLAN = "payment_plan"
PAYMENT_ARRANGEMENTS = (PAYMENT_BEFORE_DELIVERY, PAYMENT_AFTER_DELIVERY, PAYMENT_PLAN)


class Customer(Base, TimestampMixin, OrganisationScopedMixin):
    """The single authoritative customer record consumed by Sales
    (docs/modules/customers.md) -- audited against jdk_clean first
    (docs/audit/CUSTOMERS_AUDIT.md). Deliberately excludes every CRM/GL/
    credit/onboarding-workflow field jdk_clean's own Customer model
    carried with "no consumer anywhere in this app" (credit terms, bank
    accounts, follow-up/dunning, purchase-side supplier mirror, ID
    verification, avatar, tags, parent-company linking) -- none of those
    have a real consuming module in jdk_erp yet either, so none are
    built speculatively (Principle 5).

    `name` is intentionally NOT unique per organisation, unlike every
    other master built so far (Category, Team, Unit) -- those are
    internally curated classification labels; a customer's name is
    externally-given real-world business data, and two unrelated real
    businesses can legitimately share a name (jdk_clean's own Customer
    never deduped name either, by the same reasoning).

    `phone` is normalized to digits-only before storage (see
    app/schemas/customer.py's `_normalize_phone`) and enforced unique per
    organisation at the DB level when provided -- fixing the audit's one
    concrete, worth-fixing defect: jdk_clean re-derived this same
    normalization at *read* time on every create/update via an O(n) scan
    of every existing customer row; normalizing once at write time makes
    a plain indexed equality check sufficient instead.

    `assigned_to_user_id` is the one ownership pointer this master
    needs for salesman/manager visibility scoping
    (app/services/customer_scope.py) -- nullable (an unassigned/prospect
    customer is valid), SET NULL on the assignee's deletion. There is
    deliberately no `created_by` column: `app/services/audit_service.py`'s
    `customer_created` event's `actor_user_id` already records who
    created a customer, the same way it does for every other master --
    a second, redundant column here would duplicate that."""

    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("organisation_id", "code", name="uq_customers_organisation_id_code"),
        UniqueConstraint("organisation_id", "phone", name="uq_customers_organisation_id_phone"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    contact_person: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_to_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    # Standing payment arrangement decided by Admin (S0.2 / S14.2): payment
    # before delivery, after delivery, or an Admin-approved plan (described
    # in payment_plan_details). Required before a Sales Order can be
    # created; it records the arrangement only -- payments are Finance's.
    payment_arrangement: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payment_plan_details: Mapped[str | None] = mapped_column(Text, nullable=True)
