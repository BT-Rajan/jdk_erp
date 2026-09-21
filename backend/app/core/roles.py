"""The four roles docs/modules/roles_rbac.md #2 names -- a small, fixed
set, not data an organisation configures, so this is a plain constant,
not a database table (see that document's implementation-approach
section for why)."""

SUPER_ADMIN = "super_admin"
ADMIN = "admin"
MANAGER = "manager"
TEAM_MEMBER = "team_member"

VALID_ROLES = {SUPER_ADMIN, ADMIN, MANAGER, TEAM_MEMBER}

# Both operate within their own organisation identically today --
# super_admin's cross-organisation capability (docs/modules/organisation.md
# #6) isn't built yet. See docs/modules/roles_rbac.md's implementation
# section.
ADMIN_ROLES = {SUPER_ADMIN, ADMIN}
