"""RFQ v2: supplier invitations, structured response lines, header
department/requester/priority, line remarks (docs/modules/rfq.md v2,
docs/audit/RFQ_AUDIT_V2.md)

Existing v1 data is carried forward, never dropped: every RFQ's single
`rfqs.supplier_id` becomes one `rfq_supplier_invitations` row (`quoted`
if it already had a response, else `sent`), and every existing
`rfq_responses` row is re-pointed from `rfq_id` to that invitation. v1
responses were attachment-only, so they simply have no response lines --
converting such an RFQ still works, with each unit price entered by hand
exactly as in v1.

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rfqs") as batch_op:
        batch_op.add_column(sa.Column("priority", sa.String(length=10), nullable=False, server_default="normal"))
        batch_op.add_column(
            sa.Column(
                "team_id",
                sa.Integer(),
                sa.ForeignKey("teams.id", ondelete="SET NULL", name="fk_rfqs_team_id_teams"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "requested_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_rfqs_requested_by_user_id_users"),
                nullable=True,
            )
        )
        batch_op.create_index("ix_rfqs_team_id", ["team_id"])

    with op.batch_alter_table("rfq_lines") as batch_op:
        batch_op.add_column(sa.Column("remarks", sa.Text(), nullable=True))

    op.create_table(
        "rfq_supplier_invitations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "rfq_id",
            sa.Integer(),
            sa.ForeignKey("rfqs.id", ondelete="CASCADE", name="fk_rfq_supplier_invitations_rfq_id_rfqs"),
            nullable=False,
        ),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("suppliers.id", ondelete="RESTRICT", name="fk_rfq_supplier_invitations_supplier_id_suppliers"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="sent"),
        sa.Column("invited_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("rfq_id", "supplier_id", name="uq_rfq_supplier_invitations_rfq_id_supplier_id"),
    )
    op.create_index("ix_rfq_supplier_invitations_rfq_id", "rfq_supplier_invitations", ["rfq_id"])
    op.create_index("ix_rfq_supplier_invitations_supplier_id", "rfq_supplier_invitations", ["supplier_id"])

    # One invitation per existing RFQ, from its v1 header supplier.
    op.execute(
        """
        INSERT INTO rfq_supplier_invitations (rfq_id, supplier_id, status, invited_at, created_at, updated_at)
        SELECT r.id,
               r.supplier_id,
               CASE WHEN EXISTS (SELECT 1 FROM rfq_responses rr WHERE rr.rfq_id = r.id) THEN 'quoted' ELSE 'sent' END,
               r.created_at,
               r.created_at,
               r.updated_at
        FROM rfqs r
        """
    )

    with op.batch_alter_table("rfq_responses") as batch_op:
        batch_op.add_column(sa.Column("invitation_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("supplier_quotation_number", sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column("quotation_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("valid_until", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("payment_terms", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("delivery_terms", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("freight_terms", sa.String(length=255), nullable=True))

    # Exactly one invitation exists per rfq_id at this point (the INSERT
    # above), so this correlated subquery is always single-row.
    op.execute(
        """
        UPDATE rfq_responses
        SET invitation_id = (
            SELECT i.id FROM rfq_supplier_invitations i WHERE i.rfq_id = rfq_responses.rfq_id
        )
        """
    )

    with op.batch_alter_table("rfq_responses") as batch_op:
        batch_op.alter_column("invitation_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_rfq_responses_invitation_id_rfq_supplier_invitations",
            "rfq_supplier_invitations",
            ["invitation_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_rfq_responses_invitation_id", ["invitation_id"])
        batch_op.drop_constraint("fk_rfq_responses_rfq_id_rfqs", type_="foreignkey")
        batch_op.drop_index("ix_rfq_responses_rfq_id")
        batch_op.drop_column("rfq_id")

    with op.batch_alter_table("rfqs") as batch_op:
        batch_op.drop_constraint("fk_rfqs_supplier_id_suppliers", type_="foreignkey")
        batch_op.drop_index("ix_rfqs_supplier_id")
        batch_op.drop_column("supplier_id")

    op.create_table(
        "rfq_response_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "response_id",
            sa.Integer(),
            sa.ForeignKey("rfq_responses.id", ondelete="CASCADE", name="fk_rfq_response_lines_response_id_rfq_responses"),
            nullable=False,
        ),
        sa.Column(
            "rfq_line_id",
            sa.Integer(),
            sa.ForeignKey("rfq_lines.id", ondelete="CASCADE", name="fk_rfq_response_lines_rfq_line_id_rfq_lines"),
            nullable=False,
        ),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("delivery_days", sa.Integer(), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("response_id", "rfq_line_id", name="uq_rfq_response_lines_response_id_rfq_line_id"),
    )
    op.create_index("ix_rfq_response_lines_response_id", "rfq_response_lines", ["response_id"])
    op.create_index("ix_rfq_response_lines_rfq_line_id", "rfq_response_lines", ["rfq_line_id"])


def downgrade() -> None:
    # v1 can only represent one supplier per RFQ. Refuse rather than
    # silently discard every invitation but one (and their responses).
    bind = op.get_bind()
    not_single = bind.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM rfqs r
            WHERE (SELECT COUNT(*) FROM rfq_supplier_invitations i WHERE i.rfq_id = r.id) <> 1
            """
        )
    ).scalar()
    if not_single:
        raise RuntimeError(
            f"Cannot downgrade RFQ v2 -> v1: {not_single} RFQ(s) do not have exactly one invited supplier, "
            "which v1's single rfqs.supplier_id cannot represent."
        )

    op.drop_index("ix_rfq_response_lines_rfq_line_id", table_name="rfq_response_lines")
    op.drop_index("ix_rfq_response_lines_response_id", table_name="rfq_response_lines")
    op.drop_table("rfq_response_lines")

    with op.batch_alter_table("rfqs") as batch_op:
        batch_op.add_column(sa.Column("supplier_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE rfqs
        SET supplier_id = (SELECT i.supplier_id FROM rfq_supplier_invitations i WHERE i.rfq_id = rfqs.id)
        """
    )
    with op.batch_alter_table("rfqs") as batch_op:
        batch_op.alter_column("supplier_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_rfqs_supplier_id_suppliers", "suppliers", ["supplier_id"], ["id"], ondelete="RESTRICT"
        )
        batch_op.create_index("ix_rfqs_supplier_id", ["supplier_id"])

    with op.batch_alter_table("rfq_responses") as batch_op:
        batch_op.add_column(sa.Column("rfq_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE rfq_responses
        SET rfq_id = (SELECT i.rfq_id FROM rfq_supplier_invitations i WHERE i.id = rfq_responses.invitation_id)
        """
    )
    with op.batch_alter_table("rfq_responses") as batch_op:
        batch_op.alter_column("rfq_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key("fk_rfq_responses_rfq_id_rfqs", "rfqs", ["rfq_id"], ["id"], ondelete="CASCADE")
        batch_op.create_index("ix_rfq_responses_rfq_id", ["rfq_id"])
        batch_op.drop_constraint("fk_rfq_responses_invitation_id_rfq_supplier_invitations", type_="foreignkey")
        batch_op.drop_index("ix_rfq_responses_invitation_id")
        for column in (
            "invitation_id",
            "supplier_quotation_number",
            "quotation_date",
            "valid_until",
            "payment_terms",
            "delivery_terms",
            "freight_terms",
        ):
            batch_op.drop_column(column)

    op.drop_index("ix_rfq_supplier_invitations_supplier_id", table_name="rfq_supplier_invitations")
    op.drop_index("ix_rfq_supplier_invitations_rfq_id", table_name="rfq_supplier_invitations")
    op.drop_table("rfq_supplier_invitations")

    with op.batch_alter_table("rfq_lines") as batch_op:
        batch_op.drop_column("remarks")

    with op.batch_alter_table("rfqs") as batch_op:
        batch_op.drop_index("ix_rfqs_team_id")
        batch_op.drop_constraint("fk_rfqs_requested_by_user_id_users", type_="foreignkey")
        batch_op.drop_constraint("fk_rfqs_team_id_teams", type_="foreignkey")
        batch_op.drop_column("requested_by_user_id")
        batch_op.drop_column("team_id")
        batch_op.drop_column("priority")
