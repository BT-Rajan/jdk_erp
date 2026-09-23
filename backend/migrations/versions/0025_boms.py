"""add BOM tables and UoM/RawMaterial conversion columns (docs/modules/boms.md)

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Defensive: some deployments have hit a schema/alembic_version drift
    # where this migration's objects already exist physically (e.g. from
    # an earlier interrupted run) but alembic_version still shows 0024 --
    # every add_column/create_table/create_foreign_key/create_index below
    # is guarded by an inspector check so re-running this migration on an
    # already-drifted database is a no-op for each object it finds,
    # instead of failing with "duplicate column name"/"table already
    # exists". A clean database (nothing pre-existing) behaves exactly as
    # before -- every guard is simply true and every object is created.
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Both nullable, both-null-or-both-set (enforced in app/api/units.py) --
    # a unit that doesn't participate in universal dimensional conversion
    # (e.g. "pcs") simply carries neither (docs/audit/BOMS_AUDIT.md #5).
    uom_columns = {c["name"] for c in inspector.get_columns("units_of_measure")}
    with op.batch_alter_table("units_of_measure") as batch_op:
        if "dimension" not in uom_columns:
            batch_op.add_column(sa.Column("dimension", sa.String(length=40), nullable=True))
        if "conversion_factor_to_base" not in uom_columns:
            batch_op.add_column(sa.Column("conversion_factor_to_base", sa.Numeric(precision=18, scale=6), nullable=True))

    # Both nullable, both-null-or-both-set (enforced in
    # app/api/raw_materials.py) -- "1 [this material's own unit_of_measure]
    # = alternate_conversion_factor [alternate_conversion_unit_of_measure]"
    # (docs/audit/BOMS_AUDIT.md #5).
    raw_material_columns = {c["name"] for c in inspector.get_columns("raw_materials")}
    raw_material_fks = {fk["name"] for fk in inspector.get_foreign_keys("raw_materials")}
    raw_material_indexes = {idx["name"] for idx in inspector.get_indexes("raw_materials")}
    with op.batch_alter_table("raw_materials") as batch_op:
        if "alternate_conversion_unit_of_measure_id" not in raw_material_columns:
            batch_op.add_column(sa.Column("alternate_conversion_unit_of_measure_id", sa.Integer(), nullable=True))
        if "alternate_conversion_factor" not in raw_material_columns:
            batch_op.add_column(sa.Column("alternate_conversion_factor", sa.Numeric(precision=18, scale=6), nullable=True))
        if "fk_raw_materials_alternate_conversion_unit_of_measure_id_units_of_measure" not in raw_material_fks:
            batch_op.create_foreign_key(
                "fk_raw_materials_alternate_conversion_unit_of_measure_id_units_of_measure",
                "units_of_measure",
                ["alternate_conversion_unit_of_measure_id"],
                ["id"],
                ondelete="RESTRICT",
            )
        if "ix_raw_materials_alternate_conversion_unit_of_measure_id" not in raw_material_indexes:
            batch_op.create_index(
                "ix_raw_materials_alternate_conversion_unit_of_measure_id",
                ["alternate_conversion_unit_of_measure_id"],
            )

    # One BOM per product (UniqueConstraint) -- exactly one currently
    # authoritative recipe, no revision/version history
    # (docs/audit/BOMS_AUDIT.md #10).
    if not inspector.has_table("boms"):
        op.create_table(
            "boms",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "organisation_id",
                sa.Integer(),
                sa.ForeignKey("organisations.id", ondelete="RESTRICT", name="fk_boms_organisation_id_organisations"),
                nullable=False,
            ),
            sa.Column(
                "product_id",
                sa.Integer(),
                sa.ForeignKey("products.id", ondelete="RESTRICT", name="fk_boms_product_id_products"),
                nullable=False,
            ),
            sa.Column("base_quantity", sa.Numeric(precision=14, scale=4), nullable=False),
            sa.Column("status", sa.String(length=10), nullable=False, server_default="draft"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("organisation_id", "product_id", name="uq_boms_organisation_id_product_id"),
        )
        op.create_index("ix_boms_organisation_id", "boms", ["organisation_id"])
        op.create_index("ix_boms_product_id", "boms", ["product_id"])

    # No organisation_id of its own -- a pure join between an
    # (already organisation-scoped) Bom and a RawMaterial, the same shape
    # as UserTeam/SupplierMaterial (docs/audit/BOMS_AUDIT.md #9).
    if not inspector.has_table("bom_components"):
        op.create_table(
            "bom_components",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "bom_id",
                sa.Integer(),
                sa.ForeignKey("boms.id", ondelete="CASCADE", name="fk_bom_components_bom_id_boms"),
                nullable=False,
            ),
            sa.Column(
                "raw_material_id",
                sa.Integer(),
                sa.ForeignKey(
                    "raw_materials.id", ondelete="RESTRICT", name="fk_bom_components_raw_material_id_raw_materials"
                ),
                nullable=False,
            ),
            sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("bom_id", "raw_material_id", name="uq_bom_components_bom_id_raw_material_id"),
        )
        op.create_index("ix_bom_components_bom_id", "bom_components", ["bom_id"])
        op.create_index("ix_bom_components_raw_material_id", "bom_components", ["raw_material_id"])


def downgrade() -> None:
    op.drop_table("bom_components")
    op.drop_table("boms")

    with op.batch_alter_table("raw_materials") as batch_op:
        batch_op.drop_index("ix_raw_materials_alternate_conversion_unit_of_measure_id")
        batch_op.drop_constraint(
            "fk_raw_materials_alternate_conversion_unit_of_measure_id_units_of_measure", type_="foreignkey"
        )
        batch_op.drop_column("alternate_conversion_factor")
        batch_op.drop_column("alternate_conversion_unit_of_measure_id")

    with op.batch_alter_table("units_of_measure") as batch_op:
        batch_op.drop_column("conversion_factor_to_base")
        batch_op.drop_column("dimension")
