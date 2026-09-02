import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { filterSelectableEmployees, validateNewUserPassword } from "@/lib/vinco-user-provisioning";
import { ROLE_LABELS, type AppUser, type AppUserRole } from "@/lib/vinco-users";

/**
 * The single "give an employee a VINCO login" workflow: creates a real
 * Supabase Auth account plus its `app_users` row via the existing
 * `POST /users` API (`user_service.create_user`) -- no separate/parallel
 * creation path. Shared by every page that can provision access
 * (`employees.tsx`, `hr-employees.tsx`) so there is exactly one place
 * this form's validation and API call live, per the standing instruction
 * not to build a second user-management system alongside the existing
 * one.
 *
 * Employee and existing-user data are fetched here, only while open, and
 * under the SAME react-query keys the pages that display them already
 * use (`["resource", "hr_employees"]` for the HR roster -- matching
 * `resource-page.tsx`'s own key for that table -- and `["app-users"]` for
 * native logins, matching `settings.users.tsx`) so this dialog reads and
 * invalidates the exact same cache those pages render from, rather than
 * a second, independently-fetched copy.
 */

type Employee = {
  id: number;
  full_name: string;
  position: string | null;
  department: string | null;
};

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.describe();
  if (e instanceof Error) return e.message;
  return String(e);
}

export function AddVincoUserDialog({
  open,
  onOpenChange,
  defaultEmployeeId,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Pre-selects and locks the employee -- used when opened from a
   * specific employee's "Give VINCO access" action, so the admin can't
   * accidentally provision the form for a different person. */
  defaultEmployeeId?: number | null;
  onCreated?: (user: AppUser) => void;
}) {
  const { t, lang } = useI18n();
  const queryClient = useQueryClient();

  const [employeeId, setEmployeeId] = useState<string>("");
  const [employeeFilter, setEmployeeFilter] = useState("");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [displayNameTouched, setDisplayNameTouched] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [role, setRole] = useState<AppUserRole>("employee");
  const [formError, setFormError] = useState<string | null>(null);
  const submittingRef = useRef(false);

  const locked = defaultEmployeeId != null;

  const employeesQuery = useQuery({
    queryKey: ["resource", "hr_employees"],
    enabled: open,
    queryFn: () => api.get<Employee[]>("/employees"),
  });
  const usersQuery = useQuery({
    queryKey: ["app-users"],
    enabled: open,
    queryFn: () => api.get<AppUser[]>("/users"),
  });

  // Re-seed whenever the dialog is (re)opened, rather than only on first
  // mount -- the same dialog instance is reused across opens from
  // resource-page.tsx-style parents that don't remount it per row.
  useEffect(() => {
    if (!open) return;
    setEmployeeId(defaultEmployeeId != null ? String(defaultEmployeeId) : "");
    setEmployeeFilter("");
    setUsername("");
    setDisplayName("");
    setDisplayNameTouched(false);
    setPassword("");
    setConfirmPassword("");
    setRole("employee");
    setFormError(null);
    submittingRef.current = false;
  }, [open, defaultEmployeeId]);

  // Auto-fill display name from the selected employee, but only until the
  // admin edits it themselves -- matches the ticket's "automatically
  // populated ... but editable" requirement.
  useEffect(() => {
    if (displayNameTouched) return;
    const employee = (employeesQuery.data ?? []).find((e) => String(e.id) === employeeId);
    if (employee) setDisplayName(employee.full_name);
  }, [employeeId, employeesQuery.data, displayNameTouched]);

  const linkedEmployeeIds = new Set(
    (usersQuery.data ?? [])
      .filter((u) => u.employee_id != null)
      .map((u) => u.employee_id as number),
  );

  const selectableEmployees = filterSelectableEmployees(employeesQuery.data ?? [], {
    linkedEmployeeIds,
    selectedEmployeeId: employeeId ? Number(employeeId) : null,
    filterText: employeeFilter,
  });

  const createMutation = useMutation({
    mutationFn: (payload: {
      username: string;
      display_name: string;
      password: string;
      role: AppUserRole;
      is_active: boolean;
      employee_id: number | null;
    }) => api.post<AppUser>("/users", payload),
    onSuccess: (user) => {
      toast.success(t("common.saved"));
      void queryClient.invalidateQueries({ queryKey: ["app-users"] });
      void queryClient.invalidateQueries({ queryKey: ["employees"] });
      onCreated?.(user);
      onOpenChange(false);
    },
    onError: (e: Error) => {
      toast.error(errorMessage(e));
      submittingRef.current = false;
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (submittingRef.current) return;

    const validation = validateNewUserPassword(password, confirmPassword);
    if (!validation.ok) {
      setFormError(
        t(validation.kind === "mismatch" ? "users.password_mismatch" : "users.password_too_short"),
      );
      return;
    }
    setFormError(null);
    submittingRef.current = true;
    createMutation.mutate({
      username,
      display_name: displayName,
      password,
      role,
      is_active: true,
      employee_id: employeeId ? Number(employeeId) : null,
    });
  };

  const busy = createMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("users.add_vinco_user")}</DialogTitle>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-1.5">
            <Label htmlFor="vinco-user-employee">{t("users.employee")}</Label>
            {locked ? (
              <Input
                id="vinco-user-employee"
                value={
                  (employeesQuery.data ?? []).find((e) => String(e.id) === employeeId)?.full_name ??
                  t("common.loading")
                }
                disabled
              />
            ) : (
              <>
                <Input
                  value={employeeFilter}
                  onChange={(e) => setEmployeeFilter(e.target.value)}
                  placeholder={t("users.search_employee")}
                  className="mb-1.5"
                />
                <select
                  id="vinco-user-employee"
                  className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                  value={employeeId}
                  onChange={(e) => setEmployeeId(e.target.value)}
                >
                  <option value="">{t("users.no_employee_link")}</option>
                  {selectableEmployees.length === 0 && employeeFilter.trim() ? (
                    <option value="" disabled>
                      {t("users.no_matching_employees")}
                    </option>
                  ) : null}
                  {selectableEmployees.map((e) => (
                    <option key={e.id} value={String(e.id)}>
                      {e.full_name}
                      {e.position ? ` — ${e.position}` : ""}
                    </option>
                  ))}
                </select>
              </>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="vinco-user-display-name">{t("users.display_name")}</Label>
            <Input
              id="vinco-user-display-name"
              value={displayName}
              onChange={(e) => {
                setDisplayName(e.target.value);
                setDisplayNameTouched(true);
              }}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="vinco-user-username">{t("users.username")}</Label>
            <Input
              id="vinco-user-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="off"
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="vinco-user-password">{t("auth.password")}</Label>
            <Input
              id="vinco-user-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="vinco-user-confirm-password">{t("users.confirm_password")}</Label>
            <Input
              id="vinco-user-confirm-password"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="vinco-user-role">{t("users.role")}</Label>
            <select
              id="vinco-user-role"
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={role}
              onChange={(e) => setRole(e.target.value as AppUserRole)}
            >
              {(Object.keys(ROLE_LABELS) as AppUserRole[]).map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABELS[r][lang]}
                </option>
              ))}
            </select>
          </div>
          {formError ? <p className="text-sm text-destructive">{formError}</p> : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => onOpenChange(false)}
            >
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={busy} className="gap-2">
              {busy ? <Loader2 className="size-4 animate-spin" /> : null}
              {t("users.create_user")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
