"""Tests for app/services/uom_conversion.py: the two deliberately
separate conversion mechanisms BOM validation is built on
(docs/modules/boms.md #3) -- a universal, dimensional ratio
(UnitOfMeasure.dimension/conversion_factor_to_base) and a
material-specific, single-hop ratio (RawMaterial.alternate_conversion_*).
These call resolve_conversion_ratio directly with plain, unpersisted
ORM instances -- the function takes pre-loaded rows as arguments and
never queries the database itself (this codebase has no relationship()
usage anywhere), so no db_session/fixtures are needed here."""
from decimal import Decimal

from app.models.raw_material import RawMaterial
from app.models.unit import UnitOfMeasure
from app.services.uom_conversion import resolve_conversion_ratio


def _unit(id_, dimension=None, factor=None):
    return UnitOfMeasure(id=id_, organisation_id=1, name=f"unit{id_}", code=f"U{id_}", dimension=dimension, conversion_factor_to_base=factor, is_active=True)


def _material(id_, unit_id, alt_unit_id=None, alt_factor=None):
    return RawMaterial(
        id=id_,
        organisation_id=1,
        code=f"RM{id_}",
        name=f"material{id_}",
        category_id=1,
        unit_of_measure_id=unit_id,
        alternate_conversion_unit_of_measure_id=alt_unit_id,
        alternate_conversion_factor=alt_factor,
        is_active=True,
    )


def test_same_unit_returns_ratio_of_one():
    kg = _unit(1, dimension="mass", factor=Decimal(1))
    assert resolve_conversion_ratio(kg, kg) == Decimal(1)


def test_universal_conversion_within_same_dimension():
    kg = _unit(1, dimension="mass", factor=Decimal(1))
    tonne = _unit(2, dimension="mass", factor=Decimal(1000))
    # 1 tonne = 1000 kg
    assert resolve_conversion_ratio(tonne, kg) == Decimal(1000)
    # 1 kg = 0.001 tonne
    assert resolve_conversion_ratio(kg, tonne) == Decimal(1) / Decimal(1000)


def test_no_conversion_across_different_dimensions_without_material_override():
    kg = _unit(1, dimension="mass", factor=Decimal(1))
    litre = _unit(2, dimension="volume", factor=Decimal(1))
    assert resolve_conversion_ratio(litre, kg) is None


def test_no_conversion_when_dimension_missing_on_either_side():
    kg = _unit(1, dimension="mass", factor=Decimal(1))
    bag = _unit(2, dimension=None, factor=None)
    assert resolve_conversion_ratio(bag, kg) is None


def test_material_specific_conversion_density():
    litre = _unit(1, dimension="volume", factor=Decimal(1))
    kg = _unit(2, dimension="mass", factor=Decimal(1))
    material_n = _material(1, unit_id=litre.id, alt_unit_id=kg.id, alt_factor=Decimal("1.25"))

    # 1 litre of Material N = 1.25 kg
    ratio = resolve_conversion_ratio(litre, kg, material=material_n, material_alternate_unit=kg)
    assert ratio == Decimal("1.25")

    # inverse direction: 1 kg of Material N = 1/1.25 litre
    inverse = resolve_conversion_ratio(kg, litre, material=material_n, material_alternate_unit=kg)
    assert inverse == Decimal(1) / Decimal("1.25")


def test_material_specific_conversion_packaging():
    bag = _unit(1, dimension=None, factor=None)
    kg = _unit(2, dimension="mass", factor=Decimal(1))
    material_p = _material(1, unit_id=bag.id, alt_unit_id=kg.id, alt_factor=Decimal(25))

    ratio = resolve_conversion_ratio(bag, kg, material=material_p, material_alternate_unit=kg)
    assert ratio == Decimal(25)


def test_material_specific_conversion_chains_one_universal_hop():
    """Material's alternate unit (kg) differs from the unit actually
    being converted to (tonne) -- resolves via one material-specific hop
    (bag->kg) plus one further universal hop (kg->tonne), never a
    multi-hop generic conversion graph (docs/modules/boms.md #16)."""
    bag = _unit(1, dimension=None, factor=None)
    kg = _unit(2, dimension="mass", factor=Decimal(1))
    tonne = _unit(3, dimension="mass", factor=Decimal(1000))
    material_p = _material(1, unit_id=bag.id, alt_unit_id=kg.id, alt_factor=Decimal(25))

    # 1 bag = 25 kg = 0.025 tonne
    ratio = resolve_conversion_ratio(bag, tonne, material=material_p, material_alternate_unit=kg)
    assert ratio == Decimal(25) / Decimal(1000)


def test_material_override_not_used_when_material_is_none():
    litre = _unit(1, dimension="volume", factor=Decimal(1))
    kg = _unit(2, dimension="mass", factor=Decimal(1))
    assert resolve_conversion_ratio(litre, kg, material=None, material_alternate_unit=None) is None


def test_material_override_ignored_when_it_does_not_apply_to_this_pair():
    """The material's alternate conversion is anchored to its own unit
    (litre) -- it must not be (mis)applied when neither side of the
    requested conversion is that material's own unit."""
    litre = _unit(1, dimension="volume", factor=Decimal(1))
    kg = _unit(2, dimension="mass", factor=Decimal(1))
    ml = _unit(3, dimension="volume", factor=Decimal("0.001"))
    material_n = _material(1, unit_id=litre.id, alt_unit_id=kg.id, alt_factor=Decimal("1.25"))

    # ml -> kg: neither unit is material_n's own unit (litre) -- must not
    # silently reuse the litre->kg density for a different volume unit.
    assert resolve_conversion_ratio(ml, kg, material=material_n, material_alternate_unit=kg) is None
