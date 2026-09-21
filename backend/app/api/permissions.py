from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.roles import VALID_ROLES
from app.core.validation import validate_permission_key
from app.models.role_permission import RolePermission
from app.models.user import User
from app.models.user_permission import UserPermission
from app.schemas.permission import EffectiveScopeOut, PermissionScopeIn, RolePermissionOut, UserPermissionOut
from app.services import authorization_service

router = APIRouter(prefix="/api/permissions", tags=["permissions"])


def _validate_role(role: str) -> None:
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"role must be one of {sorted(VALID_ROLES)}"
        )


def _validate_keys(module_key: str, action: str) -> None:
    try:
        validate_permission_key(module_key)
        validate_permission_key(action)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _get_user_in_org(db: Session, user_id: int, organisation_id: int) -> User:
    user = db.query(User).filter(User.id == user_id, User.organisation_id == organisation_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


# --- role-level defaults (docs/modules/permissions.md #4) -------------------


@router.get("/roles", response_model=list[RolePermissionOut])
def list_role_permissions(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[RolePermission]:
    return (
        db.query(RolePermission)
        .filter(RolePermission.organisation_id == admin.organisation_id)
        .order_by(RolePermission.role, RolePermission.module_key, RolePermission.action)
        .all()
    )


@router.put("/roles/{role}/{module_key}/{action}", response_model=RolePermissionOut)
def set_role_permission(
    role: str,
    module_key: str,
    action: str,
    payload: PermissionScopeIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RolePermission:
    """Admin-gated (docs/modules/permissions.md #9): a Manager or Team
    Member is never in ADMIN_ROLES, so both get a flat 403 here -- "cannot
    grant themselves or others higher privileges" and "cannot manage
    permissions" hold without any extra check. Upserts rather than
    erroring on a repeat call for the same (role, module_key, action)."""
    _validate_role(role)
    _validate_keys(module_key, action)

    grant = (
        db.query(RolePermission)
        .filter(
            RolePermission.organisation_id == admin.organisation_id,
            RolePermission.role == role,
            RolePermission.module_key == module_key,
            RolePermission.action == action,
        )
        .first()
    )
    if grant is None:
        grant = RolePermission(
            organisation_id=admin.organisation_id, role=role, module_key=module_key, action=action, scope=payload.scope
        )
    else:
        grant.scope = payload.scope
    db.add(grant)
    db.commit()
    db.refresh(grant)
    return grant


@router.delete("/roles/{role}/{module_key}/{action}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role_permission(
    role: str, module_key: str, action: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> None:
    grant = (
        db.query(RolePermission)
        .filter(
            RolePermission.organisation_id == admin.organisation_id,
            RolePermission.role == role,
            RolePermission.module_key == module_key,
            RolePermission.action == action,
        )
        .first()
    )
    if grant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role permission not found.")
    db.delete(grant)
    db.commit()


# --- per-user overrides (docs/modules/permissions.md #5/#6) -----------------


@router.get("/users/{user_id}", response_model=list[UserPermissionOut])
def list_user_permissions(
    user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> list[UserPermission]:
    _get_user_in_org(db, user_id, admin.organisation_id)
    return (
        db.query(UserPermission)
        .filter(UserPermission.user_id == user_id)
        .order_by(UserPermission.module_key, UserPermission.action)
        .all()
    )


@router.put("/users/{user_id}/{module_key}/{action}", response_model=UserPermissionOut)
def set_user_permission(
    user_id: int,
    module_key: str,
    action: str,
    payload: PermissionScopeIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserPermission:
    _validate_keys(module_key, action)
    _get_user_in_org(db, user_id, admin.organisation_id)

    grant = (
        db.query(UserPermission)
        .filter(UserPermission.user_id == user_id, UserPermission.module_key == module_key, UserPermission.action == action)
        .first()
    )
    if grant is None:
        grant = UserPermission(
            organisation_id=admin.organisation_id,
            user_id=user_id,
            module_key=module_key,
            action=action,
            scope=payload.scope,
        )
    else:
        grant.scope = payload.scope
    db.add(grant)
    db.commit()
    db.refresh(grant)
    return grant


@router.delete("/users/{user_id}/{module_key}/{action}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_permission(
    user_id: int,
    module_key: str,
    action: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    _get_user_in_org(db, user_id, admin.organisation_id)
    grant = (
        db.query(UserPermission)
        .filter(UserPermission.user_id == user_id, UserPermission.module_key == module_key, UserPermission.action == action)
        .first()
    )
    if grant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User permission not found.")
    db.delete(grant)
    db.commit()


# --- self-service check ------------------------------------------------


@router.get("/me", response_model=EffectiveScopeOut)
def my_effective_scope(
    module_key: str = Query(...),
    action: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EffectiveScopeOut:
    """A user checking their own effective scope isn't security-sensitive
    (Principle 3 -- visibility is a UI concern, not the enforcement
    itself), and a future frontend needs this to decide what to show."""
    scope = authorization_service.get_effective_scope(db, current_user, module_key, action)
    return EffectiveScopeOut(module_key=module_key, action=action, scope=scope)
