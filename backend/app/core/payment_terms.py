"""PO payment terms (docs/modules/purchase_orders.md Revision 8): one of
Advance, Prepaid (the PO is for record only -- Finance records the
payment already made), On Delivery, or "Others: <details>". Stored as
that text in `payment_terms`."""

ADVANCE = "Advance"
PREPAID = "Prepaid"
ON_DELIVERY = "On Delivery"
OTHERS = "Others"
PAYMENT_TERM_CHOICES = (ADVANCE, PREPAID, ON_DELIVERY)


def normalise_payment_terms(value: str) -> str:
    """Returns the stored form, or raises ValueError (a 422 on the field)."""
    value = (value or "").strip()
    for choice in PAYMENT_TERM_CHOICES:
        if value.lower() == choice.lower():
            return choice
    if value.lower().startswith(OTHERS.lower()):
        details = value[len(OTHERS):].lstrip(" :-").strip()
        if not details:
            raise ValueError("Describe the payment terms for Others.")
        return f"{OTHERS}: {details}"
    raise ValueError("Choose Advance, Prepaid, On Delivery or Others.")
