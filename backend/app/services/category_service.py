"""Category checks shared by Products and Raw Materials
(docs/modules/categories.md Revision 2)."""

from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.models.category import PRODUCT, Category

_LABELS = {PRODUCT: "product", "raw_material": "raw material"}


def resolve_category(db: Session, category_id: int, organisation_id: int, applies_to: str) -> Category:
    """An active category of the right type in this organisation."""
    category = (
        db.query(Category)
        .filter(Category.id == category_id, Category.organisation_id == organisation_id, Category.is_active.is_(True))
        .first()
    )
    if category is None:
        raise ValidationError(
            "category_id must be an active category in your organisation.",
            fields={"category_id": "Not a valid active category in your organisation."},
        )
    if category.applies_to != applies_to:
        raise ValidationError(
            f"{category.name} is a {_LABELS[category.applies_to]} category.",
            fields={"category_id": f"Choose a {_LABELS[applies_to]} category."},
        )
    return category
