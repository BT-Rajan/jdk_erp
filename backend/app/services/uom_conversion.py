"""Resolves whether a valid quantity conversion exists between two units
of measure, and at what ratio -- the crux of docs/modules/boms.md #5.

Two, and only two, conversion mechanisms exist, deliberately kept
separate (docs/audit/BOMS_AUDIT.md #4/#5):

- **Universal conversion** (Case A): two units share the same
  `UnitOfMeasure.dimension` (e.g. kg and tonne both "mass"). This is a
  true physical ratio, independent of what's being measured, and is
  always safe to apply.
- **Material-specific conversion** (Case B): a single configured hop on
  a specific `RawMaterial` (e.g. "1 litre of Material N = 1.25 kg"),
  optionally chained with one further universal hop on the far side
  (e.g. that 1.25 kg then converts universally to tonnes). This is never
  inferred or assumed -- it only applies to the one material it's
  configured on, and only when that material's own unit is one side of
  the conversion.

There is deliberately no generic multi-hop conversion graph, no rules
engine, and no silent fallback -- if neither mechanism bridges two
units, `resolve_conversion_ratio` returns `None` and the caller (BOM
component validation) must reject the operation with a clear error,
never assume equivalence or round away the gap (docs/modules/boms.md #5).

This codebase has no SQLAlchemy `relationship()` usage anywhere -- every
module resolves foreign keys via explicit queries at the API layer
(see e.g. app/api/products.py's Category/UnitOfMeasure lookups). This
service follows the same convention: it takes already-loaded
`UnitOfMeasure` rows as plain arguments rather than lazy-loading via an
ORM relationship."""

from decimal import Decimal

from app.models.raw_material import RawMaterial
from app.models.unit import UnitOfMeasure


def resolve_conversion_ratio(
    from_unit: UnitOfMeasure,
    to_unit: UnitOfMeasure,
    material: RawMaterial | None = None,
    material_alternate_unit: UnitOfMeasure | None = None,
) -> Decimal | None:
    """Returns the factor F such that `1 [from_unit] = F [to_unit]`, or
    None if no valid conversion path exists. `material` +
    `material_alternate_unit` (the `UnitOfMeasure` row for
    `material.alternate_conversion_unit_of_measure_id`, pre-loaded by the
    caller) enable the material-specific hop (Case B) -- it is only ever
    applied when `from_unit` (or, symmetrically, `to_unit`) is that
    material's own `unit_of_measure_id`, never for an arbitrary pair of
    units."""
    if from_unit.id == to_unit.id:
        return Decimal(1)

    universal = _universal_ratio(from_unit, to_unit)
    if universal is not None:
        return universal

    if material is not None and material_alternate_unit is not None and material.alternate_conversion_factor is not None:
        if from_unit.id == material.unit_of_measure_id:
            return _material_specific_ratio(to_unit, material.alternate_conversion_factor, material_alternate_unit)
        # Symmetric: also resolve when the caller asks the other
        # direction (`1 [to_unit] = F [from_unit]`, inverted).
        if to_unit.id == material.unit_of_measure_id:
            inverse = _material_specific_ratio(from_unit, material.alternate_conversion_factor, material_alternate_unit)
            return None if inverse is None else Decimal(1) / inverse

    return None


def _universal_ratio(from_unit: UnitOfMeasure, to_unit: UnitOfMeasure) -> Decimal | None:
    if (
        from_unit.dimension is None
        or to_unit.dimension is None
        or from_unit.conversion_factor_to_base is None
        or to_unit.conversion_factor_to_base is None
        or from_unit.dimension != to_unit.dimension
    ):
        return None
    return from_unit.conversion_factor_to_base / to_unit.conversion_factor_to_base


def _material_specific_ratio(
    to_unit: UnitOfMeasure, factor: Decimal, alt_unit: UnitOfMeasure
) -> Decimal | None:
    """The material's own unit converts to `alt_unit` at `factor`.
    Bridges to `to_unit` directly if it *is* `alt_unit`, or via one
    further universal hop if `alt_unit` and `to_unit` share a dimension."""
    if alt_unit.id == to_unit.id:
        return factor
    universal_leg = _universal_ratio(alt_unit, to_unit)
    if universal_leg is None:
        return None
    return factor * universal_leg
