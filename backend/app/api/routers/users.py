"""Native VINCO user management -- "Users & Access" in the frontend.

Permission gating mirrors the existing Supabase RLS policies exactly
(see `supabase/migrations/*.sql`'s `profiles_admin_manage` vs.
`user_roles_manage` policies): `admin.users` covers create/list/edit
(display name, active status), `admin.roles` is required separately for
changing what a user is allowed to do. Both permissions already existed
in the `app_permission` enum before this feature -- no new permission
values were needed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import SupabaseAdmin
from app.api.deps import get_db, get_supabase_admin, require_permission
from app.api.schemas_users import (
    AppUserCreate,
    AppUserPasswordReset,
    AppUserRead,
    AppUserRoleUpdate,
    AppUserUpdate,
)
from app.services import user_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/users", tags=["users"])


def _get_or_404(session: Session, user_id: str):
    user = user_service.get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


@router.get("", response_model=list[AppUserRead])
def list_users(
    session: Session = Depends(get_db),
    _user=Depends(require_permission("admin.users")),
) -> list[AppUserRead]:
    return list(user_service.list_users(session))


@router.post("", response_model=AppUserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AppUserCreate,
    session: Session = Depends(get_db),
    admin: SupabaseAdmin = Depends(get_supabase_admin),
    _user=Depends(require_permission("admin.users")),
) -> AppUserRead:
    try:
        return user_service.create_user(
            session,
            admin,
            username=payload.username,
            display_name=payload.display_name,
            password=payload.password,
            role=payload.role,
            is_active=payload.is_active,
            employee_id=payload.employee_id,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.put("/{user_id}", response_model=AppUserRead)
def update_user(
    user_id: str,
    payload: AppUserUpdate,
    session: Session = Depends(get_db),
    admin: SupabaseAdmin = Depends(get_supabase_admin),
    _user=Depends(require_permission("admin.users")),
) -> AppUserRead:
    target = _get_or_404(session, user_id)
    try:
        return user_service.update_user(
            session, target, admin, display_name=payload.display_name, is_active=payload.is_active
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.put("/{user_id}/role", response_model=AppUserRead)
def update_user_role(
    user_id: str,
    payload: AppUserRoleUpdate,
    session: Session = Depends(get_db),
    admin: SupabaseAdmin = Depends(get_supabase_admin),
    _user=Depends(require_permission("admin.roles")),
) -> AppUserRead:
    target = _get_or_404(session, user_id)
    try:
        return user_service.update_user_role(session, target, admin, role=payload.role)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: str,
    payload: AppUserPasswordReset,
    session: Session = Depends(get_db),
    admin: SupabaseAdmin = Depends(get_supabase_admin),
    _user=Depends(require_permission("admin.users")),
) -> None:
    target = _get_or_404(session, user_id)
    try:
        user_service.reset_password(target, admin, password=payload.password)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
