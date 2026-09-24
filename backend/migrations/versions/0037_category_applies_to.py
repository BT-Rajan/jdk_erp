"""Category type: a category is for Products or for Raw Materials, never
both (docs/modules/categories.md Revision 2)

Backfill, so no record changes meaning:
- used only by raw materials -> `raw_material`;
- otherwise (used only by products, or unused) -> `product`;
- used by both -> stays `product`, and a copy named "<name> (Raw
  Material)" with the next category code is created for its raw
  materials, which are repointed to it.

Revision ID: 0037
Revises: 0036
Create Date: 2026-09-25

"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("categories") as batch_op:
        batch_op.add_column(sa.Column("applies_to", sa.String(length=20), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT c.id, c.organisation_id, c.name, c.description, c.is_active,
                   (SELECT COUNT(*) FROM products p WHERE p.category_id = c.id) AS products,
                   (SELECT COUNT(*) FROM raw_materials m WHERE m.category_id = c.id) AS materials
            FROM categories c ORDER BY c.id
            """
        )
    ).fetchall()
    now = datetime.utcnow()
    for row in rows:
        applies_to = "raw_material" if row.materials and not row.products else "product"
        bind.execute(sa.text("UPDATE categories SET applies_to = :a WHERE id = :id"), {"a": applies_to, "id": row.id})
        if not (row.products and row.materials):
            continue
        count = bind.execute(
            sa.text("SELECT COUNT(*) FROM categories WHERE organisation_id = :o"), {"o": row.organisation_id}
        ).scalar()
        bind.execute(
            sa.text(
                """
                INSERT INTO categories (organisation_id, name, code, description, is_active, applies_to, created_at, updated_at)
                VALUES (:o, :name, :code, :description, :active, 'raw_material', :now, :now)
                """
            ),
            {
                "o": row.organisation_id,
                "name": f"{row.name} (Raw Material)"[:80],
                "code": f"5{count + 1:05d}",
                "description": row.description,
                "active": row.is_active,
                "now": now,
            },
        )
        new_id = bind.execute(
            sa.text("SELECT id FROM categories WHERE organisation_id = :o AND code = :code"),
            {"o": row.organisation_id, "code": f"5{count + 1:05d}"},
        ).scalar()
        bind.execute(sa.text("UPDATE raw_materials SET category_id = :new WHERE category_id = :old"), {"new": new_id, "old": row.id})

    with op.batch_alter_table("categories") as batch_op:
        batch_op.alter_column("applies_to", existing_type=sa.String(length=20), nullable=False)


def downgrade() -> None:
    # Split copies stay as ordinary categories; only the type goes.
    with op.batch_alter_table("categories") as batch_op:
        batch_op.drop_column("applies_to")
