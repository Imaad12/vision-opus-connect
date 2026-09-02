import { describe, expect, it } from "vitest";

import {
  computeRoleSummary,
  computeUserSummary,
  filterAndSearchUsers,
  wouldRemoveLastActiveSuperAdmin,
  type EmployeeSummary,
} from "./vinco-access-control";
import type { AppUser } from "./vinco-users";

function user(overrides: Partial<AppUser> = {}): AppUser {
  return {
    id: "u1",
    username: "jdoe",
    display_name: "Jane Doe",
    role: "employee",
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    last_login_at: null,
    employee_id: null,
    ...overrides,
  };
}

describe("computeUserSummary", () => {
  const employees: EmployeeSummary[] = [
    { id: 1, full_name: "Linked" },
    { id: 2, full_name: "Unlinked" },
  ];

  it("counts totals, active/inactive, and role breakdown", () => {
    const users = [
      user({ id: "u1", role: "employee", is_active: true }),
      user({ id: "u2", role: "admin", is_active: false }),
      user({ id: "u3", role: "super_admin", is_active: true }),
    ];
    const summary = computeUserSummary(users, employees);
    expect(summary.total).toBe(3);
    expect(summary.active).toBe(2);
    expect(summary.inactive).toBe(1);
    expect(summary.byRole).toEqual({ employee: 1, admin: 1, super_user: 0, super_admin: 1 });
  });

  it("counts users without a linked employee", () => {
    const users = [user({ id: "u1", employee_id: 1 }), user({ id: "u2", employee_id: null })];
    expect(computeUserSummary(users, employees).usersWithoutEmployee).toBe(1);
  });

  it("counts employees without any linked user", () => {
    const users = [user({ id: "u1", employee_id: 1 })];
    expect(computeUserSummary(users, employees).employeesWithoutAccess).toBe(1);
  });

  it("counts users who have never logged in", () => {
    const users = [
      user({ id: "u1", last_login_at: null }),
      user({ id: "u2", last_login_at: "2026-01-01T00:00:00Z" }),
    ];
    expect(computeUserSummary(users, employees).neverLoggedIn).toBe(1);
  });
});

describe("filterAndSearchUsers", () => {
  const employeeNameById = new Map([[1, "Priya Patel"]]);
  const users = [
    user({
      id: "u1",
      username: "priya",
      display_name: "Priya P.",
      role: "admin",
      is_active: true,
      employee_id: 1,
    }),
    user({
      id: "u2",
      username: "sam",
      display_name: "Sam Employee",
      role: "employee",
      is_active: false,
      employee_id: null,
    }),
    user({
      id: "u3",
      username: "boss",
      display_name: "Boss",
      role: "super_admin",
      is_active: true,
      last_login_at: "2026-01-01T00:00:00Z",
    }),
  ];

  it("returns everyone for filter 'all' with no search", () => {
    expect(
      filterAndSearchUsers(users, { filter: "all", search: "", employeeNameById }),
    ).toHaveLength(3);
  });

  it("filters by active/inactive", () => {
    expect(
      filterAndSearchUsers(users, { filter: "active", search: "", employeeNameById }).map(
        (u) => u.id,
      ),
    ).toEqual(["u1", "u3"]);
    expect(
      filterAndSearchUsers(users, { filter: "inactive", search: "", employeeNameById }).map(
        (u) => u.id,
      ),
    ).toEqual(["u2"]);
  });

  it("filters by role", () => {
    expect(
      filterAndSearchUsers(users, { filter: "super_admin", search: "", employeeNameById }).map(
        (u) => u.id,
      ),
    ).toEqual(["u3"]);
  });

  it("filters by never logged in", () => {
    expect(
      filterAndSearchUsers(users, { filter: "never_logged_in", search: "", employeeNameById }).map(
        (u) => u.id,
      ),
    ).toEqual(["u1", "u2"]);
  });

  it("filters by no linked employee", () => {
    expect(
      filterAndSearchUsers(users, { filter: "no_employee", search: "", employeeNameById }).map(
        (u) => u.id,
      ),
    ).toEqual(["u2", "u3"]);
  });

  it("searches by username, display name, and linked employee name", () => {
    expect(
      filterAndSearchUsers(users, { filter: "all", search: "sam", employeeNameById }).map(
        (u) => u.id,
      ),
    ).toEqual(["u2"]);
    expect(
      filterAndSearchUsers(users, { filter: "all", search: "priya patel", employeeNameById }).map(
        (u) => u.id,
      ),
    ).toEqual(["u1"]);
  });

  it("combines filter and search", () => {
    expect(
      filterAndSearchUsers(users, { filter: "active", search: "boss", employeeNameById }).map(
        (u) => u.id,
      ),
    ).toEqual(["u3"]);
  });
});

describe("computeRoleSummary", () => {
  it("returns user and permission counts per role in a fixed order", () => {
    const users = [
      user({ id: "u1", role: "employee" }),
      user({ id: "u2", role: "employee" }),
      user({ id: "u3", role: "super_admin" }),
    ];
    const permissionCounts = new Map([
      ["super_admin", 40],
      ["employee", 10],
    ]);
    const summary = computeRoleSummary(users, permissionCounts);
    expect(summary.map((r) => r.role)).toEqual(["super_admin", "super_user", "admin", "employee"]);
    expect(summary.find((r) => r.role === "super_admin")).toEqual({
      role: "super_admin",
      userCount: 1,
      permissionCount: 40,
    });
    expect(summary.find((r) => r.role === "employee")).toEqual({
      role: "employee",
      userCount: 2,
      permissionCount: 10,
    });
    expect(summary.find((r) => r.role === "admin")).toEqual({
      role: "admin",
      userCount: 0,
      permissionCount: 0,
    });
  });
});

describe("wouldRemoveLastActiveSuperAdmin", () => {
  it("blocks deactivating the only active Super Admin", () => {
    const users = [user({ id: "boss", role: "super_admin", is_active: true })];
    expect(wouldRemoveLastActiveSuperAdmin(users, "boss", { is_active: false })).toBe(true);
  });

  it("allows deactivating a Super Admin when another is active", () => {
    const users = [
      user({ id: "boss1", role: "super_admin", is_active: true }),
      user({ id: "boss2", role: "super_admin", is_active: true }),
    ];
    expect(wouldRemoveLastActiveSuperAdmin(users, "boss1", { is_active: false })).toBe(false);
  });

  it("blocks demoting the only active Super Admin", () => {
    const users = [user({ id: "boss", role: "super_admin", is_active: true })];
    expect(wouldRemoveLastActiveSuperAdmin(users, "boss", { role: "admin" })).toBe(true);
  });

  it("does not block re-promoting to Super Admin", () => {
    const users = [user({ id: "boss", role: "super_admin", is_active: true })];
    expect(wouldRemoveLastActiveSuperAdmin(users, "boss", { role: "super_admin" })).toBe(false);
  });

  it("does not flag a non-Super-Admin target", () => {
    const users = [user({ id: "plain", role: "employee", is_active: true })];
    expect(wouldRemoveLastActiveSuperAdmin(users, "plain", { is_active: false })).toBe(false);
  });

  it("does not flag an already-inactive Super Admin", () => {
    const users = [user({ id: "boss", role: "super_admin", is_active: false })];
    expect(wouldRemoveLastActiveSuperAdmin(users, "boss", { role: "admin" })).toBe(false);
  });
});
