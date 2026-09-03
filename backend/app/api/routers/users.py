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

from app.api.auth import AuthenticatedUser, SupabaseAdmin
from app.api.deps import get_current_user, get_db, get_supabase_admin, require_permission
from app.api.schemas_users import (
    AppUserClaimRequest,
    AppUserCreate,
    AppUserCreateResult,
    AppUserEmployeeLinkUpdate,
    AppUserRead,
    AppUserRoleUpdate,
    AppUserSelfRead,
    AppUserUpdate,
    TemporaryPasswordIssued,
)
from app.services import user_service
from app.services.errors import ValidationError

router = APIRouter(prefix="/users", tags=["users"])


def _get_or_404(session: Session, user_id: str):
    user = user_service.get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


@router.post("/me/record-login", status_code=status.HTTP_204_NO_CONTENT)
def record_login(
    session: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> None:
    """No permission requirement beyond a valid token -- every user may
    record their own login. A no-op if the caller has no native VINCO
    account (see user_service.record_login)."""
    user_service.record_login(session, user_id=user.id)


@router.get("/me", response_model=AppUserSelfRead)
def get_own_user(
    session: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> AppUserSelfRead:
    """No permission requirement beyond a valid token, deliberately
    unlike `GET /users`/`GET /users/{id}` -- every user, including a
    plain Employee with no `admin.users` grant, must be able to check
    their own `must_change_password` status (the forced first-login
    gate, see `AppUserSelfRead`'s docstring) without needing admin
    permissions just to look at their own account. 404 if the caller has
    no native VINCO login at all (e.g. a legacy/Google-linked account) --
    the forced password-change gate simply doesn't apply to them, and
    the frontend should treat a 404 here exactly like
    `must_change_password: false`."""
    target = user_service.get_user(session, user.id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No native VINCO account.")
    return target


@router.post("/me/claim", response_model=AppUserCreateResult, status_code=status.HTTP_201_CREATED)
def claim_own_native_identity(
    payload: AppUserClaimRequest,
    session: Session = Depends(get_db),
    admin: SupabaseAdmin = Depends(get_supabase_admin),
    user: AuthenticatedUser = Depends(get_current_user),
) -> AppUserCreateResult:
    """No permission requirement beyond a valid token, deliberately --
    this is the self-service migration path for an account that (by
    definition) has no `app_users` row yet, so it can't be gated behind
    `admin.users` the way `POST /users` is. Safe regardless: it only
    ever touches the caller's OWN identity (`user.id`, from their
    verified token -- never a request parameter), and mirrors their own
    already-existing Supabase role rather than accepting one from the
    request (see `user_service.claim_native_identity`), so this can
    never grant elevated access or let one account claim another's."""
    try:
        app_user, temporary_password = user_service.claim_native_identity(
            session,
            admin,
            user_id=user.id,
            username=payload.username,
            display_name=payload.display_name,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return AppUserCreateResult(
        **AppUserRead.model_validate(app_user).model_dump(), temporary_password=temporary_password
    )


@router.post("/me/password-changed", status_code=status.HTTP_204_NO_CONTENT)
def mark_own_password_changed(
    session: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> None:
    """Bookkeeping only, called *after* the caller's own
    `supabase.auth.updateUser({password})` already succeeded from the
    frontend (see AUTH_SETUP notes in user_service.mark_password_changed)
    -- this endpoint never sees or sets a password itself, and (like
    `POST /me/record-login`) affects only the caller's own row: there is
    no `user_id` in the path or body, so an Employee can never use this
    to touch another account. A no-op if the caller has no native VINCO
    account."""
    user_service.mark_password_changed(session, user_id=user.id)


@router.get("", response_model=list[AppUserRead])
def list_users(
    session: Session = Depends(get_db),
    _user=Depends(require_permission("admin.users")),
) -> list[AppUserRead]:
    return list(user_service.list_users(session))


@router.post("", response_model=AppUserCreateResult, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AppUserCreate,
    session: Session = Depends(get_db),
    admin: SupabaseAdmin = Depends(get_supabase_admin),
    _user=Depends(require_permission("admin.users")),
) -> AppUserCreateResult:
    """No password in the request: the backend always generates a fresh
    temporary password (see user_service.create_user) and returns it
    here, once -- the response the frontend's "VINCO USER CREATED"
    dialog shows the admin (Copy Username / Copy Password / Done)."""
    try:
        app_user, temporary_password = user_service.create_user(
            session,
            admin,
            username=payload.username,
            display_name=payload.display_name,
            role=payload.role,
            is_active=payload.is_active,
            employee_id=payload.employee_id,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return AppUserCreateResult(
        **AppUserRead.model_validate(app_user).model_dump(), temporary_password=temporary_password
    )


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


@router.put("/{user_id}/employee-link", response_model=AppUserRead)
def update_employee_link(
    user_id: str,
    payload: AppUserEmployeeLinkUpdate,
    session: Session = Depends(get_db),
    _user=Depends(require_permission("admin.users")),
) -> AppUserRead:
    target = _get_or_404(session, user_id)
    try:
        return user_service.update_employee_link(session, target, employee_id=payload.employee_id)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/{user_id}/reset-password", response_model=TemporaryPasswordIssued)
def reset_password(
    user_id: str,
    session: Session = Depends(get_db),
    admin: SupabaseAdmin = Depends(get_supabase_admin),
    _user=Depends(require_permission("admin.users")),
) -> TemporaryPasswordIssued:
    """No request body: VINCO's actual account-recovery mechanism is an
    admin-generated temporary password (see user_service.reset_password),
    never an admin-invented one -- there is no reachable recovery email
    to send a reset link to (synthetic `@vinco.local` identities, see
    AppUser's docstring)."""
    target = _get_or_404(session, user_id)
    try:
        temporary_password = user_service.reset_password(session, target, admin)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return TemporaryPasswordIssued(temporary_password=temporary_password)
