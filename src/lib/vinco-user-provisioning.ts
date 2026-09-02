/**
 * Pure logic for the "give an employee a VINCO login" form
 * (`add-vinco-user-dialog.tsx`) -- factored out so it's unit-testable
 * without rendering a component, matching this codebase's existing
 * convention (see vinco-auth.ts/tauri-dev-auth.ts: UI components stay
 * thin, the logic they call is what's tested directly).
 */

export type PasswordValidation = { ok: true } | { ok: false; kind: "mismatch" | "too_short" };

/** Same two rules the backend enforces (`AppUserCreate.password`,
 * `min_length=8`) -- checked here first so the error shows instantly,
 * not after a round trip, but the backend re-checks regardless. */
export function validateNewUserPassword(
  password: string,
  confirmPassword: string,
): PasswordValidation {
  if (password !== confirmPassword) return { ok: false, kind: "mismatch" };
  if (password.length < 8) return { ok: false, kind: "too_short" };
  return { ok: true };
}

export type SelectableEmployee = {
  id: number;
  full_name: string;
  position: string | null;
  department: string | null;
};

/**
 * The employee picker's candidate list: excludes anyone already linked
 * to a different VINCO login (duplicate-employee-link prevention at the
 * UI layer -- the backend enforces the same rule regardless, see
 * user_service.create_user), except the currently-selected employee
 * (never hide the admin's own in-progress selection), then applies the
 * free-text filter across name/position/department.
 */
export function filterSelectableEmployees(
  employees: SelectableEmployee[],
  options: {
    linkedEmployeeIds: ReadonlySet<number>;
    selectedEmployeeId: number | null;
    filterText: string;
  },
): SelectableEmployee[] {
  const filter = options.filterText.trim().toLowerCase();
  return employees.filter((e) => {
    if (e.id === options.selectedEmployeeId) return true;
    if (options.linkedEmployeeIds.has(e.id)) return false;
    if (!filter) return true;
    return (
      e.full_name.toLowerCase().includes(filter) ||
      (e.position ?? "").toLowerCase().includes(filter) ||
      (e.department ?? "").toLowerCase().includes(filter)
    );
  });
}
