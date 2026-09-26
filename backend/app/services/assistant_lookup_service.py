"""Read-only lookups the JDK Assistant may call to answer "what's the
status of ..." questions (app/services/assistant_service.py).

Every lookup runs as the asking user: the same organisation boundary and
the same permission / customer-scope checks the matching screen's API
enforces. Nothing here writes -- no insert, update, delete or commit.

The tool list (TOOLS) is provider-neutral JSON Schema, sorted by name and
never built from request data, so the prompt prefix it forms stays
byte-identical between requests (prompt caching). Results are compact,
key-sorted JSON strings."""

import json
from decimal import Decimal
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.finished_goods_inventory import FinishedGoodsInventory
from app.models.inventory import RawMaterialInventory
from app.models.product import Product
from app.models.production_requirement import ProductionRequirement, SalesOrderLineFulfilment
from app.models.purchase_order import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderPayment,
    PurchaseOrderReceipt,
)
from app.models.quotation import CONVERTED, Quotation
from app.models.raw_material import RawMaterial
from app.models.rfq import Rfq, RfqSupplierInvitation
from app.models.sales_order import SalesOrder
from app.models.supplier import Supplier
from app.models.user import User
from app.models.warehouse import Warehouse
from app.services import (
    customer_scope,
    inventory_scope,
    purchase_order_service,
    purchase_payment_scope,
    purchase_scope,
    quotation_readiness_service,
    rfq_scope,
)

MAX_RESULTS = 10

_SEARCH_PROPERTIES = {
    "number": {"type": "string", "description": "The document number, or part of it."},
    "party": {"type": "string", "description": "Customer or supplier name, or part of it."},
    "status": {"type": "string", "description": "Only this status (e.g. draft, accepted, sent)."},
}


def _tool(name: str, description: str, properties: dict) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {"type": "object", "properties": properties, "additionalProperties": False},
    }


# Sorted by name; never changes at runtime (part of the cached prefix).
TOOLS: list[dict] = sorted(
    [
        _tool(
            "find_goods_receipts",
            "Goods receipts against purchase orders: status (draft/posted/cancelled/reversed), dates, PO number. "
            "Search by receipt number or PO number.",
            {"number": _SEARCH_PROPERTIES["number"], "status": _SEARCH_PROPERTIES["status"]},
        ),
        _tool(
            "find_purchase_orders",
            "Purchase orders: status, supplier, dates, final amount, amount paid, outstanding, receipts. "
            "Search by PO number, supplier name and/or status; newest first.",
            _SEARCH_PROPERTIES,
        ),
        _tool(
            "find_quotations",
            "Sales quotations: status, customer, dates, validity, total, price decision, readiness (what still "
            "blocks it) and its Sales Order if converted. Search by quotation number, customer name and/or "
            "status; newest first.",
            _SEARCH_PROPERTIES,
        ),
        _tool(
            "find_rfqs",
            "Requests for quotation to suppliers: status, priority, dates, invited suppliers and their replies, "
            "linked purchase order. Search by RFQ number, supplier name and/or status; newest first.",
            _SEARCH_PROPERTIES,
        ),
        _tool(
            "find_sales_orders",
            "Sales orders: status (handed_off/cancelled), customer, dates, total, lines, and per line how much "
            "is covered from finished goods stock and how much needs production. Search by order number, "
            "customer name and/or status; newest first.",
            _SEARCH_PROPERTIES,
        ),
        _tool(
            "find_supplier_payments",
            "Payments made to suppliers against purchase orders: amount, date, method, status. Search by "
            "payment number or PO number.",
            {"number": _SEARCH_PROPERTIES["number"], "status": _SEARCH_PROPERTIES["status"]},
        ),
        _tool(
            "get_stock",
            "Quantity on hand per warehouse for a finished product and/or a raw material, in its stock unit. "
            "Search by product or raw material name or code.",
            {"item": {"type": "string", "description": "Product or raw material name or code, or part of it."}},
        ),
    ],
    key=lambda tool: tool["name"],
)


def _dump(value: Any) -> str:
    def default(obj: Any) -> str:
        if isinstance(obj, Decimal):
            return format(obj.normalize(), "f")
        return str(obj)

    return json.dumps(value, sort_keys=True, default=default, separators=(",", ":"))


def _denied(what: str) -> str:
    return _dump({"error": f"You do not have access to {what}."})


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _find_quotations(db: Session, user: User, args: dict) -> list[dict]:
    query = customer_scope.scope_by_customer(
        db, user, db.query(Quotation).filter(Quotation.organisation_id == user.organisation_id), Quotation.customer_id
    )
    if number := _text(args.get("number")):
        query = query.filter(Quotation.quotation_number.ilike(f"%{number}%"))
    if party := _text(args.get("party")):
        query = query.join(Customer, Customer.id == Quotation.customer_id).filter(Customer.name.ilike(f"%{party}%"))
    if status := _text(args.get("status")):
        query = query.filter(Quotation.status == status.lower())
    rows = []
    for q in query.order_by(Quotation.id.desc()).limit(MAX_RESULTS):
        row = {
            "number": q.quotation_number,
            "customer": q.customer_name,
            "status": q.status,
            "date": q.quotation_date,
            "valid_until": q.valid_until,
            "requested_delivery_date": q.requested_delivery_date,
            "total": q.total_amount,
            "currency": q.currency,
            "price_approval_required": q.price_approval_required,
            "price_decision": q.price_decision,
            "rejection_reason": q.rejection_reason,
        }
        if q.status == CONVERTED:
            row["sales_order"] = (
                db.query(SalesOrder.order_number).filter(SalesOrder.quotation_id == q.id).scalar()
            )
        else:
            readiness = quotation_readiness_service.assess(db, q)
            row["readiness"] = readiness.status
            row["readiness_reasons"] = readiness.reason_codes
        rows.append(row)
    return rows


def _find_sales_orders(db: Session, user: User, args: dict) -> list[dict]:
    query = customer_scope.scope_by_customer(
        db, user, db.query(SalesOrder).filter(SalesOrder.organisation_id == user.organisation_id), SalesOrder.customer_id
    )
    if number := _text(args.get("number")):
        query = query.filter(SalesOrder.order_number.ilike(f"%{number}%"))
    if party := _text(args.get("party")):
        query = query.join(Customer, Customer.id == SalesOrder.customer_id).filter(Customer.name.ilike(f"%{party}%"))
    if status := _text(args.get("status")):
        query = query.filter(SalesOrder.status == status.lower())
    rows = []
    for order in query.order_by(SalesOrder.id.desc()).limit(MAX_RESULTS):
        fulfilment = {
            f.sales_order_line_id: f
            for f in db.query(SalesOrderLineFulfilment).filter(SalesOrderLineFulfilment.sales_order_id == order.id)
        }
        requirements = {
            r.sales_order_line_id: r
            for r in db.query(ProductionRequirement).filter(ProductionRequirement.sales_order_id == order.id)
        }
        lines = []
        for line in order.lines:
            product = db.get(Product, line.product_id)
            entry = {"line": line.line_number, "product": product.name if product else line.product_id, "quantity": line.quantity}
            if (f := fulfilment.get(line.id)) is not None:
                entry["from_stock"] = f.fg_covered_quantity
                entry["to_produce"] = f.production_quantity
            if (r := requirements.get(line.id)) is not None:
                entry["production_requirement_status"] = r.status
            lines.append(entry)
        rows.append(
            {
                "number": order.order_number,
                "quotation": order.quotation_number,
                "customer": order.customer_name,
                "status": order.status,
                "order_date": order.order_date,
                "requested_delivery_date": order.requested_delivery_date,
                "total": order.total_amount,
                "currency": order.currency,
                "handed_off_at": order.handed_off_at,
                "cancellation_reason": order.cancellation_reason,
                "lines": lines,
            }
        )
    return rows


def _find_rfqs(db: Session, user: User, args: dict) -> list[dict] | str:
    if not rfq_scope.can_perform(db, user, rfq_scope.VIEW):
        return _denied("RFQs")
    query = db.query(Rfq).filter(Rfq.organisation_id == user.organisation_id)
    if number := _text(args.get("number")):
        query = query.filter(Rfq.rfq_number.ilike(f"%{number}%"))
    if party := _text(args.get("party")):
        invited = (
            db.query(RfqSupplierInvitation.rfq_id)
            .join(Supplier, Supplier.id == RfqSupplierInvitation.supplier_id)
            .filter(Supplier.name.ilike(f"%{party}%"))
        )
        query = query.filter(Rfq.id.in_(invited))
    if status := _text(args.get("status")):
        query = query.filter(Rfq.status == status.lower())
    rows = []
    for rfq in query.order_by(Rfq.id.desc()).limit(MAX_RESULTS):
        invitations = (
            db.query(RfqSupplierInvitation, Supplier)
            .join(Supplier, Supplier.id == RfqSupplierInvitation.supplier_id)
            .filter(RfqSupplierInvitation.rfq_id == rfq.id)
            .order_by(Supplier.name)
            .all()
        )
        po_number = (
            db.query(PurchaseOrder.po_number).filter(PurchaseOrder.id == rfq.purchase_order_id).scalar()
            if rfq.purchase_order_id
            else None
        )
        rows.append(
            {
                "number": rfq.rfq_number,
                "status": rfq.status,
                "priority": rfq.priority,
                "date": rfq.rfq_date,
                "required_delivery_date": rfq.required_delivery_date,
                "suppliers": [{"supplier": s.name, "reply": i.status} for i, s in invitations],
                "purchase_order": po_number,
                "cancel_reason": rfq.cancel_reason,
            }
        )
    return rows


def _po_summary(db: Session, po: PurchaseOrder) -> dict:
    lines = db.query(PurchaseOrderLine).filter(PurchaseOrderLine.purchase_order_id == po.id).all()
    payments = db.query(PurchaseOrderPayment).filter(PurchaseOrderPayment.purchase_order_id == po.id).all()
    final = purchase_order_service.final_amount(po, lines)
    paid = purchase_order_service.paid_amount(payments)
    receipts = db.query(PurchaseOrderReceipt).filter(PurchaseOrderReceipt.purchase_order_id == po.id).all()
    supplier = db.get(Supplier, po.supplier_id)
    return {
        "number": po.po_number,
        "supplier": supplier.name if supplier else None,
        "status": po.status,
        "order_date": po.order_date,
        "expected_delivery_date": po.expected_delivery_date,
        "currency": po.currency,
        "final_amount": final,
        "paid": paid,
        "outstanding": final - paid,
        "payment_terms": po.payment_terms,
        "receipts": [{"number": r.receipt_number, "status": r.status, "date": r.receipt_date} for r in receipts],
        "cancel_reason": po.cancel_reason,
    }


def _find_purchase_orders(db: Session, user: User, args: dict) -> list[dict] | str:
    if not purchase_scope.can_perform(db, user, purchase_scope.VIEW):
        return _denied("purchase orders")
    query = db.query(PurchaseOrder).filter(PurchaseOrder.organisation_id == user.organisation_id)
    if number := _text(args.get("number")):
        query = query.filter(PurchaseOrder.po_number.ilike(f"%{number}%"))
    if party := _text(args.get("party")):
        query = query.join(Supplier, Supplier.id == PurchaseOrder.supplier_id).filter(Supplier.name.ilike(f"%{party}%"))
    if status := _text(args.get("status")):
        query = query.filter(PurchaseOrder.status == status.lower())
    return [_po_summary(db, po) for po in query.order_by(PurchaseOrder.id.desc()).limit(MAX_RESULTS)]


def _find_goods_receipts(db: Session, user: User, args: dict) -> list[dict] | str:
    if not (
        purchase_scope.can_perform(db, user, purchase_scope.VIEW)
        or purchase_scope.can_perform(db, user, purchase_scope.RECEIVE)
    ):
        return _denied("goods receipts")
    query = (
        db.query(PurchaseOrderReceipt, PurchaseOrder)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderReceipt.purchase_order_id)
        .filter(PurchaseOrderReceipt.organisation_id == user.organisation_id)
    )
    if number := _text(args.get("number")):
        query = query.filter(
            or_(PurchaseOrderReceipt.receipt_number.ilike(f"%{number}%"), PurchaseOrder.po_number.ilike(f"%{number}%"))
        )
    if status := _text(args.get("status")):
        query = query.filter(PurchaseOrderReceipt.status == status.lower())
    rows = []
    for receipt, po in query.order_by(PurchaseOrderReceipt.id.desc()).limit(MAX_RESULTS):
        warehouse = db.get(Warehouse, receipt.warehouse_id)
        rows.append(
            {
                "number": receipt.receipt_number,
                "purchase_order": po.po_number,
                "status": receipt.status,
                "date": receipt.receipt_date,
                "warehouse": warehouse.name if warehouse else None,
                "posted_at": receipt.posted_at,
                "reversal_reason": receipt.reversal_reason,
            }
        )
    return rows


def _find_supplier_payments(db: Session, user: User, args: dict) -> list[dict] | str:
    if not (
        purchase_scope.can_perform(db, user, purchase_scope.VIEW)
        or purchase_payment_scope.can_perform(db, user, purchase_payment_scope.CREATE)
    ):
        return _denied("supplier payments")
    query = (
        db.query(PurchaseOrderPayment, PurchaseOrder)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderPayment.purchase_order_id)
        .filter(PurchaseOrderPayment.organisation_id == user.organisation_id)
    )
    if number := _text(args.get("number")):
        query = query.filter(
            or_(PurchaseOrderPayment.payment_number.ilike(f"%{number}%"), PurchaseOrder.po_number.ilike(f"%{number}%"))
        )
    if status := _text(args.get("status")):
        query = query.filter(PurchaseOrderPayment.status == status.lower())
    return [
        {
            "number": payment.payment_number,
            "purchase_order": po.po_number,
            "status": payment.status,
            "date": payment.payment_date,
            "amount": payment.amount,
            "currency": po.currency,
            "method": payment.payment_method,
            "reference": payment.reference_number,
            "final_payment": payment.is_final,
            "cancellation_reason": payment.cancellation_reason,
        }
        for payment, po in query.order_by(PurchaseOrderPayment.id.desc()).limit(MAX_RESULTS)
    ]


def _get_stock(db: Session, user: User, args: dict) -> dict | str:
    item = _text(args.get("item"))
    if not item:
        return _dump({"error": "Say which product or raw material."})
    result: dict[str, Any] = {}
    if inventory_scope.can_perform(db, user, inventory_scope.VIEW):
        products = (
            db.query(Product)
            .filter(Product.organisation_id == user.organisation_id, or_(Product.name.ilike(f"%{item}%"), Product.code.ilike(f"%{item}%")))
            .order_by(Product.name)
            .limit(MAX_RESULTS)
            .all()
        )
        result["finished_goods"] = [
            {
                "product": p.name,
                "code": p.code,
                "warehouses": [
                    {"warehouse": w.name, "on_hand": inv.quantity_on_hand}
                    for inv, w in db.query(FinishedGoodsInventory, Warehouse)
                    .join(Warehouse, Warehouse.id == FinishedGoodsInventory.warehouse_id)
                    .filter(FinishedGoodsInventory.product_id == p.id)
                    .order_by(Warehouse.name)
                ],
            }
            for p in products
        ]
    # Raw material balances are shown on the Stock Reconciliation screen.
    if inventory_scope.can_perform(db, user, inventory_scope.RECONCILE):
        materials = (
            db.query(RawMaterial)
            .filter(
                RawMaterial.organisation_id == user.organisation_id,
                or_(RawMaterial.name.ilike(f"%{item}%"), RawMaterial.code.ilike(f"%{item}%")),
            )
            .order_by(RawMaterial.name)
            .limit(MAX_RESULTS)
            .all()
        )
        result["raw_materials"] = [
            {
                "raw_material": m.name,
                "code": m.code,
                "warehouses": [
                    {"warehouse": w.name, "on_hand": inv.quantity_on_hand}
                    for inv, w in db.query(RawMaterialInventory, Warehouse)
                    .join(Warehouse, Warehouse.id == RawMaterialInventory.warehouse_id)
                    .filter(RawMaterialInventory.raw_material_id == m.id)
                    .order_by(Warehouse.name)
                ],
            }
            for m in materials
        ]
    if not result:
        return _denied("stock levels")
    return result


_HANDLERS = {
    "find_goods_receipts": _find_goods_receipts,
    "find_purchase_orders": _find_purchase_orders,
    "find_quotations": _find_quotations,
    "find_rfqs": _find_rfqs,
    "find_sales_orders": _find_sales_orders,
    "find_supplier_payments": _find_supplier_payments,
    "get_stock": _get_stock,
}


def run(db: Session, user: User, name: str, args: dict | None) -> str:
    """Runs one lookup as `user` and returns its JSON result. An unknown
    tool or bad arguments come back as an error result, never raised."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return _dump({"error": f"Unknown lookup {name}."})
    result = handler(db, user, args if isinstance(args, dict) else {})
    if isinstance(result, str):
        return result
    if isinstance(result, list) and not result:
        return _dump({"results": [], "note": "Nothing found that you can see."})
    return _dump({"results": result} if isinstance(result, list) else result)
