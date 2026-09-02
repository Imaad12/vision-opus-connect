from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class AppUser(Base, TimestampMixin):
    """A native VINCO user: the application-level profile and role for a
    Supabase Auth identity created through VINCO's own "Users & Access"
    admin UI (not the Google-OAuth-linked accounts the frontend also
    supports).

    `id` is the Supabase Auth user's real id (a UUID, stored as opaque
    text) -- not a FK, matching the existing convention for referencing a
    Supabase auth user id from this schema (see `Lead.owner_id`):
    `auth.users` lives in Supabase's own schema, not `vinco`, so a real
    foreign key isn't practical here.

    `role` is VINCO's own simplified, employee-facing label
    (employee/admin/super_user/super_admin) -- NOT the actual permission
    enforcement mechanism. Enforcement still flows entirely through
    Supabase's existing `user_roles`/`role_permissions`/`can()` (see
    `app/api/auth.py`'s `SupabaseAdmin.set_user_role`, which keeps a
    matching `public.user_roles` row in sync whenever this changes) --
    this column exists so VINCO's own UI has a fast, authoritative-for-
    display copy without an extra round trip per list-users render, per
    the explicit instruction that authorization must stay backend/
    Supabase-enforced, not merely reflected here.

    `employee_id` links this login to an HR roster entry (`Employee`,
    same `vinco` schema, so a real FK works here unlike `id` above) --
    nullable, since not every VINCO login corresponds to an HR employee
    (e.g. a system/admin account) and not every employee needs one; the
    unique constraint enforces at most one VINCO login per employee, so
    "does this employee have a VINCO login" is always a single answer.

    `must_change_password` is true whenever the current password was set
    by an admin (creation, or an admin-triggered reset) rather than
    chosen by the account holder -- the login flow forces a
    password-set screen while this is true (see
    src/routes/_authenticated/route.tsx), and clears it the moment the
    account holder sets their own password (first-login or self-service
    change). `password_changed_at` mirrors that: only ever set by the
    account holder's own change, never by an admin action, so it stays a
    genuine "the human last changed this" signal.
    """

    __tablename__ = "app_users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("employees.id"), nullable=True, unique=True
    )
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"AppUser(id={self.id!r}, username={self.username!r}, role={self.role!r})"
