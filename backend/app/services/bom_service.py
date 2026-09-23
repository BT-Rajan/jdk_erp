"""BOM component validation and the two calculations built on top of it
-- percentage display and production material requirements
(docs/modules/boms.md). Both calculations are pure/stateless: given a
BOM, its components, and the master-data rows they reference, they
return a value with no side effects and no persistence of their own.
Whichever future Production Order module snapshots a requirement onto
its own transaction row is responsible for capturing the result at that
point in time -- this service never caches or remembers a prior answer
(docs/audit/BOMS_AUDIT.md #7/#8)."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.core.errors import ValidationError
from app.models.product import Product
from app.models.raw_material import RawMaterial
from app.models.unit import UnitOfMeasure
from app.services.uom_conversion import resolve_conversion_ratio


@dataclass
class ComponentConversion:
    ratio_to_product_unit: Decimal | None
    error: str | None


def check_component_conversion(
    product: Product,
    product_unit: UnitOfMeasure,
    raw_material: RawMaterial,
    material_unit: UnitOfMeasure,
    material_alternate_unit: UnitOfMeasure | None,
) -> ComponentConversion:
    """Resolves whether `raw_material`'s own unit can be related to
    `product`'s own unit at all -- the validation docs/modules/boms.md #5
    requires before a component can be saved. Returns the ratio
    (`1 [material_unit] = ratio [product_unit]`) needed for percentage
    display, or a clear, named error if no valid conversion exists."""
    ratio = resolve_conversion_ratio(
        material_unit, product_unit, material=raw_material, material_alternate_unit=material_alternate_unit
    )
    if ratio is None:
        return ComponentConversion(
            ratio_to_product_unit=None,
            error=(
                f"Cannot establish a valid quantity conversion between {product.name} ({product_unit.code}) "
                f"and {raw_material.name} ({material_unit.code}). Configure the required material-specific "
                f"conversion on {raw_material.name} before adding it to this BOM."
            ),
        )
    return ComponentConversion(ratio_to_product_unit=ratio, error=None)


def require_valid_component_conversion(
    product: Product,
    product_unit: UnitOfMeasure,
    raw_material: RawMaterial,
    material_unit: UnitOfMeasure,
    material_alternate_unit: UnitOfMeasure | None,
) -> Decimal:
    """Same check as `check_component_conversion`, raising `ValidationError`
    instead of returning the failure -- used at the point a component is
    added or edited, where an invalid conversion must block the save
    rather than merely be reported (docs/modules/boms.md #5: "the BoM
    must be rejected/saved as incomplete rather than silently calculating
    an incorrect quantity")."""
    result = check_component_conversion(product, product_unit, raw_material, material_unit, material_alternate_unit)
    if result.ratio_to_product_unit is None:
        raise ValidationError(
            result.error or "Invalid unit conversion.",
            fields={"raw_material_id": "No valid quantity conversion to the Product's unit of measure."},
        )
    return result.ratio_to_product_unit


def component_percentage(component_quantity: Decimal, ratio_to_product_unit: Decimal, base_quantity: Decimal) -> Decimal:
    """`percentage` is always derived from the authoritative `quantity`,
    never a second, independently-editable value (docs/modules/boms.md
    #8) -- `(component quantity, expressed in the Product's own unit) /
    base_quantity * 100`. Quantized to 6 decimal places so the displayed
    precision doesn't vary with how many hops (docs/modules/boms.md #3)
    a given component's conversion happened to take."""
    quantity_in_product_unit = component_quantity * ratio_to_product_unit
    percentage = (quantity_in_product_unit / base_quantity) * 100
    return percentage.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def required_quantity(component_quantity: Decimal, production_quantity: Decimal, base_quantity: Decimal) -> Decimal:
    """docs/modules/boms.md #7: `Required = Component Qty * Production
    Qty / Base Qty`. `production_quantity` is assumed to already be
    expressed in the BOM's own base unit (the Product's unit_of_measure)
    -- the same assumption jdk_clean's own `explode_requirements` makes
    (docs/audit/BOMS_AUDIT.md #6), which is exactly why this ratio needs
    no unit conversion of its own: it is dimensionless as long as both
    sides share a unit, and the result is already in the component's own
    unit (`component_quantity`'s unit), never converted away
    (docs/modules/boms.md #6). Quantized to 4 decimal places -- the same
    `Numeric(14, 4)` precision every stored quantity in this codebase
    uses -- so a Decimal division that doesn't happen to terminate
    early (e.g. 1/3) never displays with a misleadingly different
    number of decimal places than the quantities it was computed from."""
    return (component_quantity * production_quantity / base_quantity).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
