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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import SupabaseAdmin, SupabaseAdminError
from app.models import AppUser
from app.services.errors import ValidationError

__all__ = [
    "USERNAME_EMAIL_DOMAIN",
    "list_users",
    "get_user",
    "create_user",
    "update_user",
    "update_user_role",
    "reset_password",
]

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


def list_users(session: Session) -> list[AppUser]:
    return list(session.execute(select(AppUser).order_by(AppUser.username)).scalars().all())


def get_user(session: Session, user_id: str) -> AppUser | None:
    return session.get(AppUser, user_id)


def create_user(
    session: Session,
    admin: SupabaseAdmin,
    *,
    username: str,
    display_name: str,
    password: str,
    role: str,
    is_active: bool,
) -> AppUser:
    existing = session.execute(select(AppUser).where(AppUser.username == username)).scalar_one_or_none()
    if existing is not None:
        raise ValidationError(f"Username {username!r} is already taken.")

    supabase_role = ROLE_TO_SUPABASE_ROLE.get(role)
    if supabase_role is None:
        raise ValidationError(f"Unknown role {role!r}.")

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

    try:
        admin.set_user_role(user.id, supabase_role)
    except SupabaseAdminError as exc:
        raise ValidationError(str(exc)) from exc

    user.role = role
    session.flush()
    return user


def reset_password(user: AppUser, admin: SupabaseAdmin, *, password: str) -> None:
    try:
        admin.set_password(user.id, password)
    except SupabaseAdminError as exc:
        raise ValidationError(str(exc)) from exc
