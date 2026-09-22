from typing import Callable

from sqlalchemy.orm import Session

from app.models.user import User

# The mechanism for docs/modules/file_storage.md #5 ("a file must
# inherit the access rules of the record it belongs to") -- this module
# provides the hook, the future module owning an entity_type (Invoice,
# Quotation, ...) supplies the actual business rule by registering here,
# exactly the "common validation provides the mechanism, the module
# provides the business rule" boundary docs/modules/common_validation.md
# #6 already established. No entity type exists yet, so this registry
# starts empty -- organisation-scoping (checked before this ever runs)
# is the whole access rule until the first one registers.
EntityAccessCheck = Callable[[Session, User, int], bool]

_registry: dict[str, EntityAccessCheck] = {}


def register_entity_access_check(entity_type: str, checker: EntityAccessCheck) -> None:
    _registry[entity_type] = checker


def get_entity_access_check(entity_type: str) -> EntityAccessCheck | None:
    return _registry.get(entity_type)
