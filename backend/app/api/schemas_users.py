"""Pydantic request/response models for native VINCO user management.

See `app/api/routers/users.py` and `app/services/user_service.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: VINCO's own simplified, employee-facing role labels -- see
#: user_service.py's ROLE_TO_SUPABASE_ROLE for how each maps onto the
#: real Supabase app_role enum that actually drives permission
#: enforcement (unchanged, still entirely via require_permission/can()).
AppUserRole = Literal["employee", "admin", "super_user", "super_admin"]

#: Mirrored by the frontend's own client-side username validation (the
#: Add User form) so a rejected username fails the same way in both
#: places, not silently stricter/looser on one side.
_USERNAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{2,63}$"


class AppUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: str
    role: AppUserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None
    employee_id: int | None = None
    must_change_password: bool = True
    password_changed_at: datetime | None = None


class AppUserCreate(BaseModel):
    """No `password` field: the backend always generates a fresh,
    cryptographically random temporary password (see
    user_service.generate_temporary_password) rather than trusting an
    admin to invent one -- see `AppUserCreateResult` for how it's
    returned, once, in the create response."""

    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    role: AppUserRole
    is_active: bool = True
    #: Optional link to an existing HR roster entry (`Employee.id`) -- see
    #: user_service.create_user for the existence/uniqueness checks. Not
    #: every VINCO login needs one (e.g. a system/admin account).
    employee_id: int | None = None

    @field_validator("username")
    @classmethod
    def _username_shape(cls, value: str) -> str:
        import re

        normalized = value.strip().lower()
        if not re.match(_USERNAME_PATTERN, normalized):
            raise ValueError(
                "Username must be 3-64 characters, lowercase letters/numbers/"
                "dots/hyphens/underscores, starting with a letter or number."
            )
        return normalized


class AppUserCreateResult(AppUserRead):
    """`AppUserRead` plus the one-time temporary password -- present ONLY
    in the immediate response to `POST /users`, never persisted (see
    AppUser -- there is no password column at all) and never returned by
    any other endpoint, including `GET /users`/`GET /users/{id}`."""

    temporary_password: str


class TemporaryPasswordIssued(BaseModel):
    """Response for `POST /users/{id}/reset-password`: the new,
    cryptographically random temporary password, shown to the admin
    exactly once. Same non-persistence guarantee as
    `AppUserCreateResult.temporary_password`."""

    temporary_password: str


class AppUserUpdate(BaseModel):
    """Display name and active status only -- role changes go through
    `AppUserRoleUpdate` / `PUT /users/{id}/role` instead, gated behind
    the stricter `admin.roles` permission rather than `admin.users`
    (matching the existing Supabase RLS policies' own split -- see
    `supabase/migrations/*.sql`'s `user_roles_manage` vs.
    `profiles_admin_manage` policies)."""

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class AppUserRoleUpdate(BaseModel):
    role: AppUserRole


class AppUserEmployeeLinkUpdate(BaseModel):
    #: `None` unlinks the account from any HR roster entry.
    employee_id: int | None = None


class AppUserSelfRead(BaseModel):
    """Response for `GET /users/me` -- deliberately a narrower shape than
    `AppUserRead`, not because anything in it is secret (it's the
    caller's own row), but because this endpoint's whole point is to be
    reachable by *any* authenticated user (no `admin.users` permission
    required, see routers/users.py) to answer exactly one question:
    "must I change my password before doing anything else". Callers that
    need the rest of the row (role, employee link, ...) for an admin UI
    already have `GET /users`/`GET /users/{id}`, which are correctly
    gated behind `admin.users`."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: str
    must_change_password: bool
