"""Native VINCO user management: creates and manages a real Supabase Auth
identity plus a `vinco.app_users` profile row, for VINCO's own
"Users & Access" admin UI.

VINCO's own `app_users.role` (employee/admin/super_user/super_admin) is
the employee-facing label; permission *enforcement* is entirely
unchanged and still flows through Supabase's real `app_role` enum /
`user_roles` / `role_permissions` / `can()` (see app/api/auth.py). This
module keeps the two in sync on every create/role-change rather than
letting `app_users.role` drift into being merely cosmetic.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import SupabaseAdmin, SupabaseAdminError
from app.models import AppUser, Employee
from app.services.errors import ValidationError

__all__ = [
    "USERNAME_EMAIL_DOMAIN",
    "LAST_ACTIVE_ROLE_GUARD",
    "list_users",
    "get_user",
    "create_user",
    "update_user",
    "update_user_role",
    "update_employee_link",
    "reset_password",
    "record_login",
]

#: The one role that can create/edit users and change roles by default
#: (see supabase/migrations/20260818103534_*.sql's DEFAULT ROLE
#: PERMISSIONS section -- `general_manager` only gets `admin.audit`,
#: `super_user` deliberately excludes every `admin.*` permission). If the
#: last *active* account holding this role were deactivated or demoted,
#: nobody could manage users or roles again -- not even by editing the
#: database directly through this same API, since every route that could
#: fix it requires admin.users/admin.roles. `update_user` and
#: `update_user_role` both refuse the specific change that would reach
#: zero.
LAST_ACTIVE_ROLE_GUARD = "super_admin"

#: Synthetic email domain for native VINCO accounts -- Supabase Auth
#: requires an email-shaped identifier, but employees only ever see and
#: type a username (see the login form). Never a real, reachable inbox;
#: `email_confirm: true` at creation time skips Supabase's normal
#: verification-email flow entirely, so nothing is ever sent to it.
#: MUST match the frontend's own construction of this address (see
#: src/lib/vinco-auth.ts) -- both sides derive the same value from the
#: same username rather than one of them looking it up from the other.
USERNAME_EMAIL_DOMAIN = "vinco.local"

#: VINCO's simplified role label -> the real Supabase app_role enum
#: value that actually drives permission enforcement. `super_user` maps
#: to the literal string "super_user", which requires the two Supabase
#: migrations `supabase/migrations/20260902000000_add_super_user_role.sql`
#: and `..._20260902000001_grant_super_user_permissions.sql` to have been
#: applied (`supabase db push`, same as every other migration in that
#: directory) -- assigning it before that fails loudly (see
#: SupabaseAdmin.set_user_role) rather than silently doing the wrong
#: thing. Those two migrations grant it a deliberately curated
#: permission set (every existing permission except admin.*).
ROLE_TO_SUPABASE_ROLE: dict[str, str] = {
    "employee": "employee",
    "admin": "general_manager",
    "super_user": "super_user",
    "super_admin": "super_admin",
}


def _username_email(username: str) -> str:
    return f"{username}@{USERNAME_EMAIL_DOMAIN}"


def _validate_employee_link(
    session: Session, employee_id: int, *, exclude_user_id: str | None = None
) -> Employee:
    """Shared by `create_user` and `update_employee_link`: an employee_id
    must name a real, non-deleted employee, and one not already linked to
    a *different* app_user (`exclude_user_id` lets an update re-validate
    without tripping over the row it's updating)."""
    employee = session.get(Employee, employee_id)
    if employee is None or employee.is_deleted:
        raise ValidationError(f"Employee {employee_id} not found.")
    stmt = select(AppUser).where(AppUser.employee_id == employee_id)
    if exclude_user_id is not None:
        stmt = stmt.where(AppUser.id != exclude_user_id)
    already_linked = session.execute(stmt).scalar_one_or_none()
    if already_linked is not None:
        raise ValidationError(
            f"{employee.full_name} already has a VINCO login ({already_linked.username!r})."
        )
    return employee


def _active_last_active_role_count(session: Session, *, excluding: str | None = None) -> int:
    """How many *active* accounts currently hold `LAST_ACTIVE_ROLE_GUARD`,
    optionally excluding one user (the one about to change) -- used to
    decide whether a pending deactivation/demotion would reach zero."""
    stmt = select(func.count()).select_from(AppUser).where(
        AppUser.role == LAST_ACTIVE_ROLE_GUARD, AppUser.is_active.is_(True)
    )
    if excluding is not None:
        stmt = stmt.where(AppUser.id != excluding)
    return session.execute(stmt).scalar_one()


def list_users(session: Session) -> list[AppUser]:
    return list(session.execute(select(AppUser).order_by(AppUser.username)).scalars().all())


def get_user(session: Session, user_id: str) -> AppUser | None:
    return session.get(AppUser, user_id)


def record_login(session: Session, *, user_id: str) -> None:
    """Best-effort last-login tracking for the caller's own account --
    a silent no-op when no app_users row exists (e.g. a legacy Supabase
    identity with no native VINCO login), not an error. Meant to be
    called once per interactive sign-in, right after
    `signInWithPassword` succeeds (see src/lib/vinco-auth.ts) -- never
    gated behind a permission, since every user may record their own
    login."""
    user = session.get(AppUser, user_id)
    if user is None:
        return
    user.last_login_at = datetime.now(timezone.utc)
    session.flush()


def create_user(
    session: Session,
    admin: SupabaseAdmin,
    *,
    username: str,
    display_name: str,
    password: str,
    role: str,
    is_active: bool,
    employee_id: int | None = None,
) -> AppUser:
    existing = session.execute(select(AppUser).where(AppUser.username == username)).scalar_one_or_none()
    if existing is not None:
        raise ValidationError(f"Username {username!r} is already taken.")

    supabase_role = ROLE_TO_SUPABASE_ROLE.get(role)
    if supabase_role is None:
        raise ValidationError(f"Unknown role {role!r}.")

    # Validated here, before any Supabase Auth call: a bad employee_id
    # must never leave behind a real, orphaned Supabase Auth identity
    # with no app_users row to show for it -- same reasoning as checking
    # the username above before create_auth_user runs.
    if employee_id is not None:
        _validate_employee_link(session, employee_id)

    try:
        user_id = admin.create_auth_user(
            email=_username_email(username), password=password, full_name=display_name
        )
        admin.set_user_role(user_id, supabase_role)
        if not is_active:
            admin.set_banned(user_id, banned=True)
    except SupabaseAdminError as exc:
        raise ValidationError(str(exc)) from exc

    app_user = AppUser(
        id=user_id,
        username=username,
        display_name=display_name,
        role=role,
        is_active=is_active,
        employee_id=employee_id,
    )
    session.add(app_user)
    session.flush()
    return app_user


def update_user(
    session: Session,
    user: AppUser,
    admin: SupabaseAdmin,
    *,
    display_name: str | None,
    is_active: bool | None,
) -> AppUser:
    if is_active is not None and is_active != user.is_active:
        if (
            not is_active
            and user.role == LAST_ACTIVE_ROLE_GUARD
            and _active_last_active_role_count(session, excluding=user.id) == 0
        ):
            raise ValidationError(
                "Cannot deactivate the last active Super Admin -- this would leave nobody "
                "able to manage users or roles. Make another account Super Admin first."
            )
        try:
            admin.set_banned(user.id, banned=not is_active)
        except SupabaseAdminError as exc:
            raise ValidationError(str(exc)) from exc
        user.is_active = is_active

    if display_name is not None:
        user.display_name = display_name

    session.flush()
    return user


def update_user_role(session: Session, user: AppUser, admin: SupabaseAdmin, *, role: str) -> AppUser:
    supabase_role = ROLE_TO_SUPABASE_ROLE.get(role)
    if supabase_role is None:
        raise ValidationError(f"Unknown role {role!r}.")

    if (
        role != LAST_ACTIVE_ROLE_GUARD
        and user.role == LAST_ACTIVE_ROLE_GUARD
        and user.is_active
        and _active_last_active_role_count(session, excluding=user.id) == 0
    ):
        raise ValidationError(
            "Cannot change the last active Super Admin's role -- this would leave nobody "
            "able to manage users or roles. Make another account Super Admin first."
        )

    try:
        admin.set_user_role(user.id, supabase_role)
    except SupabaseAdminError as exc:
        raise ValidationError(str(exc)) from exc

    user.role = role
    session.flush()
    return user


def update_employee_link(session: Session, user: AppUser, *, employee_id: int | None) -> AppUser:
    """Links or unlinks `user` from an HR roster entry -- the same
    existence/uniqueness rule `create_user` enforces at creation time,
    reusable here since a login's employee link can change later (a
    mis-linked account, or one that never had one)."""
    if employee_id is not None:
        _validate_employee_link(session, employee_id, exclude_user_id=user.id)
    user.employee_id = employee_id
    session.flush()
    return user


def reset_password(user: AppUser, admin: SupabaseAdmin, *, password: str) -> None:
    try:
        admin.set_password(user.id, password)
    except SupabaseAdminError as exc:
        raise ValidationError(str(exc)) from exc
