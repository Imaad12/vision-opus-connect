import { describe, expect, it } from "vitest";

import { filterSelectableEmployees, validateNewUserPassword } from "./vinco-user-provisioning";

describe("validateNewUserPassword", () => {
  it("accepts a matching password of at least 8 characters", () => {
    expect(validateNewUserPassword("correct-horse", "correct-horse")).toEqual({ ok: true });
  });

  it("rejects mismatched passwords", () => {
    expect(validateNewUserPassword("correct-horse", "wrong-password")).toEqual({
      ok: false,
      kind: "mismatch",
    });
  });

  it("rejects a matching password shorter than 8 characters", () => {
    expect(validateNewUserPassword("short1", "short1")).toEqual({ ok: false, kind: "too_short" });
  });

  it("checks length only once passwords match (mismatch takes priority)", () => {
    expect(validateNewUserPassword("a", "b")).toEqual({ ok: false, kind: "mismatch" });
  });
});

describe("filterSelectableEmployees", () => {
  const employees = [
    { id: 1, full_name: "Priya Patel", position: "Site Engineer", department: "Projects" },
    { id: 2, full_name: "Sam Employee", position: "Accountant", department: "Finance" },
    { id: 3, full_name: "Already Linked", position: "Manager", department: "Sales" },
  ];

  it("excludes employees already linked to a VINCO login", () => {
    const result = filterSelectableEmployees(employees, {
      linkedEmployeeIds: new Set([3]),
      selectedEmployeeId: null,
      filterText: "",
    });
    expect(result.map((e) => e.id)).toEqual([1, 2]);
  });

  it("never hides the currently-selected employee, even if linked", () => {
    const result = filterSelectableEmployees(employees, {
      linkedEmployeeIds: new Set([3]),
      selectedEmployeeId: 3,
      filterText: "",
    });
    expect(result.map((e) => e.id)).toContain(3);
  });

  it("filters by name case-insensitively", () => {
    const result = filterSelectableEmployees(employees, {
      linkedEmployeeIds: new Set(),
      selectedEmployeeId: null,
      filterText: "priya",
    });
    expect(result.map((e) => e.id)).toEqual([1]);
  });

  it("filters by position and department too", () => {
    expect(
      filterSelectableEmployees(employees, {
        linkedEmployeeIds: new Set(),
        selectedEmployeeId: null,
        filterText: "finance",
      }).map((e) => e.id),
    ).toEqual([2]);

    expect(
      filterSelectableEmployees(employees, {
        linkedEmployeeIds: new Set(),
        selectedEmployeeId: null,
        filterText: "accountant",
      }).map((e) => e.id),
    ).toEqual([2]);
  });

  it("returns everyone unlinked when the filter is empty", () => {
    const result = filterSelectableEmployees(employees, {
      linkedEmployeeIds: new Set(),
      selectedEmployeeId: null,
      filterText: "   ",
    });
    expect(result).toHaveLength(3);
  });
});
