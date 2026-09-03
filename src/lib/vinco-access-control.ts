/**
 * Pure logic for the Employees & roles "access control center"
 * (summary cards, directory filter/search, role rollups, and the
 * last-active-Super-Admin safeguard's UI-side mirror) -- factored out so
 * it's unit-testable without rendering a component, matching this
 * codebase's existing convention (vinco-auth.ts, vinco-user-provisioning.ts).
 *
 * The real, authoritative last-active-Super-Admin guard lives server-side
 * (`backend/app/services/user_service.py`'s `LAST_ACTIVE_ROLE_GUARD`
 * checks) -- `wouldRemoveLastActiveSuperAdmin` below only mirrors that
 * rule so the UI can warn/confirm *before* sending a request that the
 * backend would reject anyway, per "frontend visibility is not
 * security."
 */

import type { AppUser, AppUserRole } from "@/lib/vinco-users";

export type EmployeeSummary = { id: number; full_name: string };

export type UserSummaryCounts = {
  total: number;
  active: number;
  inactive: number;
  byRole: Record<AppUserRole, number>;
  usersWithoutEmployee: number;
  employeesWithoutAccess: number;
  neverLoggedIn: number;
  mustChangePassword: number;
};

export function computeUserSummary(
  users: readonly AppUser[],
  employees: readonly EmployeeSummary[],
): UserSummaryCounts {
  const linkedEmployeeIds = new Set(
    users.filter((u) => u.employee_id != null).map((u) => u.employee_id as number),
  );
  const byRole: Record<AppUserRole, number> = {
    employee: 0,
    admin: 0,
    super_user: 0,
    super_admin: 0,
  };
  let active = 0;
  let usersWithoutEmployee = 0;
  let neverLoggedIn = 0;
  let mustChangePassword = 0;
  for (const u of users) {
    byRole[u.role]++;
    if (u.is_active) active++;
    if (u.employee_id == null) usersWithoutEmployee++;
    if (!u.last_login_at) neverLoggedIn++;
    if (u.must_change_password) mustChangePassword++;
  }
  return {
    total: users.length,
    active,
    inactive: users.length - active,
    byRole,
    usersWithoutEmployee,
    employeesWithoutAccess: employees.filter((e) => !linkedEmployeeIds.has(e.id)).length,
    neverLoggedIn,
    mustChangePassword,
  };
}

export type UserDirectoryFilter =
  | "all"
  | "active"
  | "inactive"
  | "employee"
  | "admin"
  | "super_user"
  | "super_admin"
  | "never_logged_in"
  | "no_employee"
  | "must_change_password";

/** `employeeNameById` lets search match on the linked employee's name,
 * not just the account's own username/display name. */
export function filterAndSearchUsers(
  users: readonly AppUser[],
  options: {
    filter: UserDirectoryFilter;
    search: string;
    employeeNameById: ReadonlyMap<number, string>;
  },
): AppUser[] {
  const query = options.search.trim().toLowerCase();
  return users.filter((u) => {
    switch (options.filter) {
      case "active":
        if (!u.is_active) return false;
        break;
      case "inactive":
        if (u.is_active) return false;
        break;
      case "employee":
      case "admin":
      case "super_user":
      case "super_admin":
        if (u.role !== options.filter) return false;
        break;
      case "never_logged_in":
        if (u.last_login_at) return false;
        break;
      case "no_employee":
        if (u.employee_id != null) return false;
        break;
      case "must_change_password":
        if (!u.must_change_password) return false;
        break;
      case "all":
        break;
    }
    if (!query) return true;
    const employeeName =
      u.employee_id != null ? (options.employeeNameById.get(u.employee_id) ?? "") : "";
    return (
      u.username.toLowerCase().includes(query) ||
      u.display_name.toLowerCase().includes(query) ||
      employeeName.toLowerCase().includes(query)
    );
  });
}

export type RoleSummaryRow = {
  role: AppUserRole;
  userCount: number;
  permissionCount: number;
};

export function computeRoleSummary(
  users: readonly AppUser[],
  permissionCountByRole: ReadonlyMap<string, number>,
): RoleSummaryRow[] {
  const roles: AppUserRole[] = ["super_admin", "super_user", "admin", "employee"];
  const userCounts = new Map<AppUserRole, number>();
  for (const u of users) userCounts.set(u.role, (userCounts.get(u.role) ?? 0) + 1);
  return roles.map((role) => ({
    role,
    userCount: userCounts.get(role) ?? 0,
    permissionCount: permissionCountByRole.get(role) ?? 0,
  }));
}

/**
 * Same rule as the backend's `LAST_ACTIVE_ROLE_GUARD`: would this
 * pending change (deactivating, or changing away from Super Admin) drop
 * the count of *other* active Super Admins to zero? UI-only -- always
 * re-checked and enforced server-side regardless of what this returns.
 */
export function wouldRemoveLastActiveSuperAdmin(
  users: readonly AppUser[],
  targetUserId: string,
  change: { is_active?: boolean; role?: AppUserRole },
): boolean {
  const target = users.find((u) => u.id === targetUserId);
  if (!target || target.role !== "super_admin" || !target.is_active) return false;

  const losesSuperAdminStatus =
    (change.is_active === false && change.role === undefined) ||
    (change.role !== undefined && change.role !== "super_admin");
  if (!losesSuperAdminStatus) return false;

  const otherActiveSuperAdmins = users.filter(
    (u) => u.id !== targetUserId && u.role === "super_admin" && u.is_active,
  ).length;
  return otherActiveSuperAdmins === 0;
}

/**
 * Decides what a permission-checklist checkbox toggle should actually
 * write to `user_permissions` (see `UserDetailSheet`'s Access tab and
 * `employees.tsx`'s `setPermissionOverrideMutation`).
 *
 * `user_permissions` is an *override* table, not a full copy of a
 * user's effective permissions -- ticking a checkbox back to exactly
 * what the user's role already grants by default should clear any
 * existing override row rather than pin a redundant explicit grant
 * (and likewise for unticking it back to the role's own "doesn't
 * grant" default). Only a genuine divergence from the role's default
 * is ever written as an explicit grant/deny row.
 */
export function computePermissionOverrideAction(
  checked: boolean,
  roleGrantsByDefault: boolean,
): "grant" | "deny" | "clear" {
  if (checked === roleGrantsByDefault) return "clear";
  return checked ? "grant" : "deny";
}
