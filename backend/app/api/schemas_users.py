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


class AppUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)
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


class AppUserPasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=200)
