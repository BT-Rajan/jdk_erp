from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Known security actions/module -- plain constants, not an enum. Business
# modules introduce their own free-form action/module strings the same
# way permissions' module_key/action are free-form
# (docs/modules/audit_trail.md #2, docs/modules/permissions.md #2) -- a
# new one is a data value written by a future module, not a Python
# constant this file has to grow.
LOGIN_SUCCESS = "login_success"
LOGIN_FAILURE = "login_failure"
LOGOUT = "logout"
PASSWORD_CHANGE = "password_change"
ROLE_CHANGED = "role_changed"
TEAM_ADDED = "team_added"
TEAM_REMOVED = "team_removed"
USER_CREATED = "user_created"
USER_STATUS_CHANGED = "user_status_changed"
EMAIL_ACCOUNT_UPDATED = "email_account_updated"
ORGANISATION_UPDATED = "organisation_updated"
ORGANISATION_STATUS_CHANGED = "organisation_status_changed"
SAME_DAY_CUTOFF_UPDATED = "same_day_cutoff_updated"
HOLIDAY_ADDED = "holiday_added"
HOLIDAY_REMOVED = "holiday_removed"
CATEGORY_CREATED = "category_created"
CATEGORY_UPDATED = "category_updated"
CATEGORY_STATUS_CHANGED = "category_status_changed"
UNIT_CREATED = "unit_created"
UNIT_UPDATED = "unit_updated"
UNIT_STATUS_CHANGED = "unit_status_changed"
CUSTOMER_CREATED = "customer_created"
CUSTOMER_UPDATED = "customer_updated"
CUSTOMER_STATUS_CHANGED = "customer_status_changed"
CUSTOMER_ASSIGNED = "customer_assigned"
SUPPLIER_CREATED = "supplier_created"
SUPPLIER_UPDATED = "supplier_updated"
SUPPLIER_STATUS_CHANGED = "supplier_status_changed"
PRODUCT_CREATED = "product_created"
PRODUCT_UPDATED = "product_updated"
PRODUCT_STATUS_CHANGED = "product_status_changed"
RAW_MATERIAL_CREATED = "raw_material_created"
RAW_MATERIAL_UPDATED = "raw_material_updated"
RAW_MATERIAL_STATUS_CHANGED = "raw_material_status_changed"
SUPPLIER_MATERIAL_ADDED = "supplier_material_added"
SUPPLIER_MATERIAL_UPDATED = "supplier_material_updated"
SUPPLIER_MATERIAL_REMOVED = "supplier_material_removed"
PRODUCTION_LINE_CREATED = "production_line_created"
PRODUCTION_LINE_UPDATED = "production_line_updated"
PRODUCTION_LINE_STATUS_CHANGED = "production_line_status_changed"
MACHINE_CREATED = "machine_created"
MACHINE_UPDATED = "machine_updated"
MACHINE_STATUS_CHANGED = "machine_status_changed"
WAREHOUSE_CREATED = "warehouse_created"
WAREHOUSE_UPDATED = "warehouse_updated"
WAREHOUSE_STATUS_CHANGED = "warehouse_status_changed"
BOM_CREATED = "bom_created"
BOM_UPDATED = "bom_updated"
BOM_STATUS_CHANGED = "bom_status_changed"
BOM_COMPONENT_ADDED = "bom_component_added"
BOM_COMPONENT_UPDATED = "bom_component_updated"
BOM_COMPONENT_REMOVED = "bom_component_removed"
PURCHASE_ORDER_CREATED = "purchase_order_created"
PURCHASE_ORDER_UPDATED = "purchase_order_updated"
PURCHASE_ORDER_STATUS_CHANGED = "purchase_order_status_changed"
PURCHASE_ORDER_LINE_ADDED = "purchase_order_line_added"
PURCHASE_ORDER_LINE_UPDATED = "purchase_order_line_updated"
PURCHASE_ORDER_LINE_REMOVED = "purchase_order_line_removed"
PURCHASE_ORDER_RECEIVED = "purchase_order_received"
PURCHASE_ORDER_ISSUED = "purchase_order_issued"
PURCHASE_ORDER_SUPPLIER_CONFIRMED = "purchase_order_supplier_confirmed"  # historical rows only
PURCHASE_ORDER_SUBMITTED = "purchase_order_submitted"
PURCHASE_ORDER_APPROVED = "purchase_order_approved"
PURCHASE_ORDER_RECONCILED = "purchase_order_reconciled"
PURCHASE_ORDER_FOLLOW_UP = "purchase_order_follow_up"
PURCHASE_ORDER_SENT = "purchase_order_sent"
PURCHASE_ORDER_SEND_FAILED = "purchase_order_send_failed"
PURCHASE_ORDER_PAYMENT_RECORDED = "purchase_order_payment_recorded"
PURCHASE_ORDER_PAYMENT_CANCELLED = "purchase_order_payment_cancelled"
# PURCHASE_ORDER_RECEIVED (above) is kept only for already-written
# historical AuditEvent rows from the removed receive-as-action flow --
# no code writes it anymore (docs/modules/purchase_orders.md Revision 4).
PURCHASE_ORDER_RECEIPT_CREATED = "purchase_order_receipt_created"
PURCHASE_ORDER_RECEIPT_POSTED = "purchase_order_receipt_posted"
PURCHASE_ORDER_RECEIPT_CANCELLED = "purchase_order_receipt_cancelled"
PURCHASE_ORDER_RECEIPT_REVERSED = "purchase_order_receipt_reversed"
RFQ_CREATED = "rfq_created"
RFQ_UPDATED = "rfq_updated"
RFQ_LINE_ADDED = "rfq_line_added"
RFQ_LINE_UPDATED = "rfq_line_updated"
RFQ_LINE_REMOVED = "rfq_line_removed"
RFQ_STATUS_CHANGED = "rfq_status_changed"
RFQ_RESPONSE_CAPTURED = "rfq_response_captured"
RFQ_DECIDED = "rfq_decided"
RFQ_CONVERTED = "rfq_converted"
RFQ_INVITATION_ADDED = "rfq_invitation_added"
RFQ_INVITATION_REMOVED = "rfq_invitation_removed"
RFQ_INVITATION_DECLINED = "rfq_invitation_declined"
RFQ_INVITATION_FOLLOW_UP_ADDED = "rfq_invitation_follow_up_added"
RFQ_SENT = "rfq_sent"
RFQ_SEND_FAILED = "rfq_send_failed"
DOCUMENT_TEMPLATE_UPDATED = "document_template_updated"
INVENTORY_ADJUSTMENT_CREATED = "inventory_adjustment_created"
INVENTORY_OPENING_STOCK_RECORDED = "inventory_opening_stock_recorded"
# Finished Goods Inventory's own write event -- reuses INVENTORY_MODULE
# below rather than a new module constant, the same "one Inventory
# domain" reasoning app/services/inventory_scope.py's module_key reuse
# already documents for Finished Goods Inventory's authorization.
FINISHED_GOODS_ADJUSTMENT_CREATED = "finished_goods_adjustment_created"
QUOTATION_CREATED = "quotation_created"
QUOTATION_UPDATED = "quotation_updated"
QUOTATION_ACCEPTED = "quotation_accepted"
QUOTATION_REJECTED = "quotation_rejected"
QUOTATION_RENEWED = "quotation_renewed"
QUOTATION_CONVERTED = "quotation_converted"
SALES_ORDER_CREATED = "sales_order_created"
SALES_ORDER_UPDATED = "sales_order_updated"
SALES_ORDER_CANCELLED = "sales_order_cancelled"
SALES_ORDER_HANDED_OFF = "sales_order_handed_off"
FULFILMENT_ASSESSED = "fulfilment_assessed"
# Production Requirement lifecycle (Production P1), module "production".
# Reservation + FG Allocation foundation, module "inventory" (allocation)
# and "sales" (reservation).
RESERVATION_CREATED = "reservation_created"
RESERVATION_CHANGED = "reservation_changed"
RESERVATION_RELEASED = "reservation_released"
FG_ALLOCATED = "fg_allocated"
FG_ALLOCATION_RELEASED = "fg_allocation_released"
FG_ALLOCATION_CONSUMED = "fg_allocation_consumed"
PRODUCTION_REQUIREMENT_CREATED = "requirement_created"
PRODUCTION_REQUIREMENT_BOM_RESOLVED = "requirement_bom_resolved"
PRODUCTION_REQUIREMENT_QUANTITY_CHANGED = "requirement_quantity_changed"
PRODUCTION_REQUIREMENT_REOPENED = "requirement_reopened"
PRODUCTION_REQUIREMENT_FULFILLED = "requirement_fulfilled"
PRODUCTION_REQUIREMENT_CANCELLED = "requirement_cancelled"
ASSISTANT_KEY_UPDATED = "assistant_key_updated"
DELIVERY_INSTRUCTION_CREATED = "delivery_instruction_created"
DELIVERY_SHIPMENT_UPDATED = "delivery_shipment_updated"
DELIVERY_FULFILLED = "delivery_fulfilled"
DELIVERY_NOT_FULFILLED = "delivery_not_fulfilled"
DELIVERY_RETRIED = "delivery_retried"
SALES_ORDER_DELIVERY_STATUS = "sales_order_delivery_status"
QUOTATION_PRICE_DECIDED = "price_decided"
FEASIBILITY_RECORDED = "feasibility_recorded"
FEASIBILITY_DECIDED = "feasibility_decided"
QUOTATION_READINESS_ASSESSED = "readiness_assessed"

SECURITY_MODULE = "security"
COMMUNICATION_MODULE = "communication"
ORGANISATION_MODULE = "organisation"
# Shared by every Phase 2 master-data entity (Categories, then Units of
# Measure, Products, ...) -- one module name for "master data changed",
# not a new constant invented per entity (docs/ENGINEERING_PRINCIPLES.md
# #2 one source of truth).
MASTER_DATA_MODULE = "master_data"
# Phase 4 -- Purchase Order lifecycle/receiving events
# (docs/modules/purchase_orders.md).
PROCUREMENT_MODULE = "procurement"
# Controlled Stock Adjustments -- the Inventory module's own events,
# distinct from PROCUREMENT_MODULE the same way its own
# app/services/inventory_scope.py's module_key is distinct from
# purchase_scope.py's.
INVENTORY_MODULE = "inventory"
# Phase 3 -- Sales documents (quotations, and later orders/delivery notes).
SALES_MODULE = "sales"
# Production demand arising from handed-off Sales Orders (S15.2).
PRODUCTION_MODULE = "production"
# Delivery Instructions -- shipment tranches of Sales Orders (Delivery D2).
DELIVERY_MODULE = "delivery"


class AuditEvent(Base):
    """The one audit trail for both security and business events
    (docs/modules/audit_trail.md) -- generalized from the security-only
    AuthEvent built during the session/security phase, rather than kept
    as a second, parallel table (see docs/audit/AUDIT_TRAIL_AUDIT.md).
    One row per event, not per changed field (unlike jdk_clean's
    audit_log) -- details holds whatever field-level change matters as a
    compact string. Doubles as the login-lockout counter -- see
    app/services/auth_service.py -- so lockout state has exactly one
    source of truth instead of a second table to keep in sync."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_entity_type_entity_id", "entity_type", "entity_id"),
        Index("ix_audit_events_module_created_at", "module", "created_at"),
        # The exact shape of auth_service.login()'s lockout-count query
        # (action + username_attempted equality, created_at range) -- runs
        # on every login attempt, so this is a real hot path, not a
        # speculative index (docs/modules/database_transaction_integrity.md
        # #3). Its leading column (username_attempted) also makes the old
        # standalone index on that column redundant -- dropped alongside
        # this one in migration 0012.
        Index("ix_audit_events_username_attempted_action_created_at", "username_attempted", "action", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nullable: an unresolvable login attempt (unknown username) has no
    # organisation to attribute the event to. RESTRICT: an audit trail is
    # exactly the "important business record" #2 says deletion must not
    # orphan (docs/modules/database_transaction_integrity.md).
    organisation_id: Mapped[int | None] = mapped_column(
        ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    module: Mapped[str] = mapped_column(String(30), nullable=False)
    # The user this event is *about* (e.g. whose role changed). SET NULL,
    # not RESTRICT: the audit row itself must outlive the user it
    # references (these columns are already nullable for exactly this
    # "subject no longer resolvable" case).
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # Who *performed* the action, when different from user_id (an admin
    # changing someone else's role). None for a not-yet-resolved actor
    # (an unknown-username login attempt) or a system-initiated action.
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Short machine-oriented code (e.g. "bad_password", "locked_out") --
    # kept distinct from `details`, which is the longer human-readable
    # before/after narrative docs/modules/audit_trail.md #5 shows.
    reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    username_attempted: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
