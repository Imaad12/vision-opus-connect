/**
 * Shared types for native VINCO users (`vinco.app_users`, via the
 * backend's `/users` API -- see `backend/app/api/schemas_users.py` and
 * `backend/app/services/user_service.py`).
 *
 * Factored out of `settings.users.tsx` (where this used to live only
 * locally) so `employees.tsx`, `hr-employees.tsx`, and
 * `add-vinco-user-dialog.tsx` can all reference the exact same role
 * labels and response shape instead of redefining them -- see the
 * "EXISTING EMPLOYEE -> GIVE VINCO LOGIN" provisioning workflow that
 * reuses this from three different entry points.
 */

export type AppUserRole = "employee" | "admin" | "super_user" | "super_admin";

export type AppUser = {
  id: string;
  username: string;
  display_name: string;
  role: AppUserRole;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  last_login_at: string | null;
  employee_id: number | null;
};

export const ROLE_LABELS: Record<AppUserRole, { en: string; ar: string }> = {
  employee: { en: "Employee", ar: "موظف" },
  admin: { en: "Admin", ar: "مسؤول" },
  super_user: { en: "Super User", ar: "مستخدم متميز" },
  super_admin: { en: "Super Admin", ar: "مسؤول النظام" },
};

/**
 * MUST match `backend/app/services/user_service.py`'s
 * `ROLE_TO_SUPABASE_ROLE` exactly -- the frontend has no endpoint that
 * returns this mapping dynamically, so it's duplicated here rather than
 * fetched. Used only to resolve "what real Supabase role does this
 * VINCO role enforce as" for read-only display (effective permissions in
 * the user detail view) -- role *assignment* always goes through the
 * backend's `/users/{id}/role`, which is the actual source of truth.
 */
export const APP_ROLE_TO_SUPABASE_ROLE: Record<AppUserRole, string> = {
  employee: "employee",
  admin: "general_manager",
  super_user: "super_user",
  super_admin: "super_admin",
};
