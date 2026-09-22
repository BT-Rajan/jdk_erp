"""define explicit ON DELETE behaviour for every foreign key
(docs/modules/database_transaction_integrity.md #2)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-22

"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# Matches app.core.database.NAMING_CONVENTION -- lets batch mode assign a
# deterministic, addressable name to every existing anonymous FK
# constraint it reflects (SQLite never named them, since the original
# migrations declared bare ForeignKey("...") with no `name=`).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def upgrade() -> None:
    with op.batch_alter_table("users", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_users_organisation_id_organisations", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_users_organisation_id_organisations", "organisations", ["organisation_id"], ["id"], ondelete="RESTRICT"
        )

    with op.batch_alter_table("teams", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_teams_organisation_id_organisations", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_teams_organisation_id_organisations", "organisations", ["organisation_id"], ["id"], ondelete="RESTRICT"
        )

    with op.batch_alter_table("role_permissions", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_role_permissions_organisation_id_organisations", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_role_permissions_organisation_id_organisations",
            "organisations",
            ["organisation_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    with op.batch_alter_table("user_permissions", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_user_permissions_organisation_id_organisations", type_="foreignkey")
        batch_op.drop_constraint("fk_user_permissions_user_id_users", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_user_permissions_organisation_id_organisations",
            "organisations",
            ["organisation_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_user_permissions_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )

    with op.batch_alter_table("user_teams", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_user_teams_user_id_users", type_="foreignkey")
        batch_op.drop_constraint("fk_user_teams_team_id_teams", type_="foreignkey")
        batch_op.create_foreign_key("fk_user_teams_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE")
        batch_op.create_foreign_key("fk_user_teams_team_id_teams", "teams", ["team_id"], ["id"], ondelete="CASCADE")

    with op.batch_alter_table("refresh_tokens", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_refresh_tokens_user_id_users", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_refresh_tokens_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )

    with op.batch_alter_table("audit_events", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_audit_events_organisation_id", type_="foreignkey")
        # Both still carry the name from before auth_events was renamed
        # to audit_events (0008) -- fk_auth_events_*, not fk_audit_events_*
        # -- a small naming drift #1's "consistent naming" calls out, fixed
        # here alongside the ondelete change.
        batch_op.drop_constraint("fk_auth_events_user_id_users", type_="foreignkey")
        batch_op.drop_constraint("fk_auth_events_actor_user_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_audit_events_organisation_id", "organisations", ["organisation_id"], ["id"], ondelete="RESTRICT"
        )
        batch_op.create_foreign_key(
            "fk_audit_events_user_id_users", "users", ["user_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_foreign_key(
            "fk_audit_events_actor_user_id_users", "users", ["actor_user_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("audit_events", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_audit_events_actor_user_id_users", type_="foreignkey")
        batch_op.drop_constraint("fk_audit_events_user_id_users", type_="foreignkey")
        batch_op.drop_constraint("fk_audit_events_organisation_id", type_="foreignkey")
        batch_op.create_foreign_key("fk_auth_events_actor_user_id", "users", ["actor_user_id"], ["id"])
        batch_op.create_foreign_key("fk_auth_events_user_id_users", "users", ["user_id"], ["id"])
        batch_op.create_foreign_key("fk_audit_events_organisation_id", "organisations", ["organisation_id"], ["id"])

    with op.batch_alter_table("refresh_tokens", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_refresh_tokens_user_id_users", type_="foreignkey")
        batch_op.create_foreign_key("fk_refresh_tokens_user_id_users", "users", ["user_id"], ["id"])

    with op.batch_alter_table("user_teams", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_user_teams_team_id_teams", type_="foreignkey")
        batch_op.drop_constraint("fk_user_teams_user_id_users", type_="foreignkey")
        batch_op.create_foreign_key("fk_user_teams_team_id_teams", "teams", ["team_id"], ["id"])
        batch_op.create_foreign_key("fk_user_teams_user_id_users", "users", ["user_id"], ["id"])

    with op.batch_alter_table("user_permissions", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_user_permissions_user_id_users", type_="foreignkey")
        batch_op.drop_constraint("fk_user_permissions_organisation_id_organisations", type_="foreignkey")
        batch_op.create_foreign_key("fk_user_permissions_user_id_users", "users", ["user_id"], ["id"])
        batch_op.create_foreign_key(
            "fk_user_permissions_organisation_id_organisations", "organisations", ["organisation_id"], ["id"]
        )

    with op.batch_alter_table("role_permissions", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_role_permissions_organisation_id_organisations", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_role_permissions_organisation_id_organisations", "organisations", ["organisation_id"], ["id"]
        )

    with op.batch_alter_table("teams", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_teams_organisation_id_organisations", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_teams_organisation_id_organisations", "organisations", ["organisation_id"], ["id"]
        )

    with op.batch_alter_table("users", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_users_organisation_id_organisations", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_users_organisation_id_organisations", "organisations", ["organisation_id"], ["id"]
        )
