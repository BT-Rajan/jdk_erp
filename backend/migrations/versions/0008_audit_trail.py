"""generalize auth_events into audit_events (security + business events)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-21

"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("auth_events", "audit_events")

    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.alter_column(
            "event_type",
            new_column_name="action",
            existing_type=sa.String(length=20),
            existing_nullable=False,
            nullable=False,
        )
        batch_op.add_column(
            sa.Column(
                "organisation_id",
                sa.Integer(),
                sa.ForeignKey("organisations.id", name="fk_audit_events_organisation_id"),
                nullable=True,
            )
        )
        # "security" backfills every pre-existing row (all of them were
        # security events before this migration); new rows always pass
        # module explicitly via audit_service.log_event.
        batch_op.add_column(sa.Column("module", sa.String(length=30), nullable=False, server_default="security"))
        batch_op.add_column(sa.Column("entity_type", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("entity_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("result", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("details", sa.Text(), nullable=True))

        # Drop the FK before the index that backs it -- MySQL rejects
        # DROP INDEX on an index a foreign key still relies on (error 1553).
        # The name is the one alembic assigned at table-creation time via
        # app.core.database.NAMING_CONVENTION (see env.py's target_metadata),
        # not MySQL's own auto-naming; 0010 re-derives it under the new
        # table name and gives it an explicit ondelete behaviour.
        batch_op.drop_constraint("fk_auth_events_user_id_users", type_="foreignkey")
        batch_op.drop_index("ix_auth_events_user_id")
        batch_op.drop_index("ix_auth_events_username_attempted")
        batch_op.drop_index("ix_auth_events_created_at")

        batch_op.create_index("ix_audit_events_organisation_id", ["organisation_id"])
        batch_op.create_index("ix_audit_events_user_id", ["user_id"])
        batch_op.create_index("ix_audit_events_username_attempted", ["username_attempted"])
        batch_op.create_index("ix_audit_events_created_at", ["created_at"])
        batch_op.create_index("ix_audit_events_entity_type_entity_id", ["entity_type", "entity_id"])
        batch_op.create_index("ix_audit_events_module_created_at", ["module", "created_at"])

        # Re-add the FK under its original name (from before the rename) --
        # 0010 looks it up as "fk_auth_events_user_id_users" and swaps it
        # for a differently-named one with explicit ON DELETE behaviour, so
        # it needs to still exist here, not just the column.
        batch_op.create_foreign_key("fk_auth_events_user_id_users", "users", ["user_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("audit_events") as batch_op:
        # Same rule in reverse: drop each FK before the index backing it.
        # organisation_id's FK is also dropped here since the column itself
        # is dropped below (no need to recreate it, unlike user_id's).
        batch_op.drop_constraint("fk_auth_events_user_id_users", type_="foreignkey")
        batch_op.drop_constraint("fk_audit_events_organisation_id", type_="foreignkey")

        batch_op.drop_index("ix_audit_events_module_created_at")
        batch_op.drop_index("ix_audit_events_entity_type_entity_id")
        batch_op.drop_index("ix_audit_events_created_at")
        batch_op.drop_index("ix_audit_events_username_attempted")
        batch_op.drop_index("ix_audit_events_user_id")
        batch_op.drop_index("ix_audit_events_organisation_id")

        batch_op.drop_column("details")
        batch_op.drop_column("result")
        batch_op.drop_column("entity_id")
        batch_op.drop_column("entity_type")
        batch_op.drop_column("module")
        batch_op.drop_column("organisation_id")
        batch_op.alter_column(
            "action",
            new_column_name="event_type",
            existing_type=sa.String(length=20),
            existing_nullable=False,
            nullable=False,
        )

        batch_op.create_index("ix_auth_events_created_at", ["created_at"])
        batch_op.create_index("ix_auth_events_username_attempted", ["username_attempted"])
        batch_op.create_index("ix_auth_events_user_id", ["user_id"])
        batch_op.create_foreign_key("fk_auth_events_user_id_users", "users", ["user_id"], ["id"])

    op.rename_table("audit_events", "auth_events")
