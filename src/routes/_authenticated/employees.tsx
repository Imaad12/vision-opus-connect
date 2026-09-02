import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { AddVincoUserDialog } from "@/components/add-vinco-user-dialog";
import { NoAccess, PageHeader } from "@/components/app-shell";
import { ResetVincoPasswordDialog } from "@/components/reset-vinco-password-dialog";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { UserDetailSheet } from "@/components/user-detail-sheet";
import { useMe } from "@/hooks/use-auth";
import { logAudit } from "@/lib/audit";
import { ApiError, api } from "@/lib/api";
import { db, type Row } from "@/lib/db";
import { useI18n } from "@/lib/i18n";
import {
  computeRoleSummary,
  computeUserSummary,
  filterAndSearchUsers,
  wouldRemoveLastActiveSuperAdmin,
  type EmployeeSummary,
  type UserDirectoryFilter,
} from "@/lib/vinco-access-control";
import {
  APP_ROLE_TO_SUPABASE_ROLE,
  ROLE_LABELS,
  type AppUser,
  type AppUserRole,
} from "@/lib/vinco-users";

type Employee = EmployeeSummary & { email: string | null };

export const Route = createFileRoute("/_authenticated/employees")({
  head: () => ({
    meta: [
      { title: "Employees & roles — VINCO ERP" },
      {
        name: "description",
        content: "Give employees VINCO access, assign roles, and manage account access.",
      },
      { property: "og:title", content: "Employees & roles — VINCO ERP" },
      {
        property: "og:description",
        content: "Role, permission and account-access administration.",
      },
    ],
  }),
  component: EmployeesPage,
});

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.describe();
  if (e instanceof Error) return e.message;
  return String(e);
}

const FILTERS: UserDirectoryFilter[] = [
  "all",
  "active",
  "inactive",
  "employee",
  "admin",
  "super_user",
  "super_admin",
  "never_logged_in",
  "no_employee",
];

function EmployeesPage() {
  const { t, lang } = useI18n();
  const me = useMe();
  const queryClient = useQueryClient();
  const canProvision = me.can("admin.users");
  const canManageRoles = me.can("admin.roles");

  const [addOpen, setAddOpen] = useState(false);
  const [resettingPassword, setResettingPassword] = useState<AppUser | null>(null);
  const [viewingUser, setViewingUser] = useState<AppUser | null>(null);
  const [filter, setFilter] = useState<UserDirectoryFilter>("all");
  const [search, setSearch] = useState("");

  const usersQuery = useQuery({
    queryKey: ["app-users"],
    enabled: canProvision,
    queryFn: () => api.get<AppUser[]>("/users"),
  });
  const employeesQuery = useQuery({
    queryKey: ["resource", "hr_employees"],
    enabled: canProvision,
    queryFn: () => api.get<Employee[]>("/employees"),
  });
  // Supabase-side data this page needs beyond app_users: which ids have a
  // real Auth identity (profiles), data-scope per user (unchanged
  // mechanism -- see setScope below), and the role/user permission rows
  // the detail sheet and role-summary section resolve effective
  // permissions from. `role_permissions`/`user_permissions` are real,
  // already-existing RBAC tables -- not a second permission system.
  const supaQuery = useQuery({
    queryKey: ["employees"],
    enabled: canProvision,
    queryFn: async () => {
      const [profiles, scopes, rolePerms, userPerms] = await Promise.all([
        db.from("profiles").select("id"),
        db.from("user_scopes").select("user_id, scope"),
        db.from("role_permissions").select("role, permission"),
        db.from("user_permissions").select("*"),
      ]);
      return {
        profileIds: new Set(((profiles.data ?? []) as Row[]).map((p) => String(p["id"]))),
        scopes: (scopes.data ?? []) as Row[],
        rolePermissions: (rolePerms.data ?? []) as Row[],
        userPermissions: (userPerms.data ?? []) as Row[],
      };
    },
  });

  const users = usersQuery.data ?? [];
  const employees = employeesQuery.data ?? [];
  const employeeById = new Map(employees.map((e) => [e.id, e]));

  const invalidateUsers = () => void queryClient.invalidateQueries({ queryKey: ["app-users"] });

  const roleMutation = useMutation({
    mutationFn: ({ id, role }: { id: string; role: AppUserRole }) =>
      api.put<AppUser>(`/users/${id}/role`, { role }),
    onSuccess: (updated, { role }) => {
      toast.success(t("common.saved"));
      invalidateUsers();
      void logAudit({
        action: "role_changed",
        entity_type: "app_users",
        entity_id: updated.id,
        summary: `Changed ${updated.username}'s role to ${role}`,
      });
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  const setScope = useMutation({
    mutationFn: async ({ userId, scope }: { userId: string; scope: string }) => {
      const { error } = await db
        .from("user_scopes")
        .upsert({ user_id: userId, scope }, { onConflict: "user_id" });
      if (error) throw error;
    },
    onSuccess: (_data, { userId, scope }) => {
      toast.success(t("common.saved"));
      void queryClient.invalidateQueries({ queryKey: ["employees"] });
      void logAudit({
        action: "data_scope_changed",
        entity_type: "app_users",
        entity_id: userId,
        summary: `Changed data scope to ${scope}`,
      });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const toggleActiveMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      api.put<AppUser>(`/users/${id}`, { is_active }),
    onSuccess: (updated, { is_active }) => {
      toast.success(t("common.saved"));
      invalidateUsers();
      void logAudit({
        action: is_active ? "account_activated" : "account_deactivated",
        entity_type: "app_users",
        entity_id: updated.id,
        summary: `${is_active ? "Activated" : "Deactivated"} ${updated.username}`,
      });
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  const resetPasswordMutation = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) =>
      api.post<void>(`/users/${id}/reset-password`, { password }),
    onSuccess: (_data, { id }) => {
      toast.success(t("common.saved"));
      setResettingPassword(null);
      const target = users.find((u) => u.id === id);
      void logAudit({
        action: "password_reset",
        entity_type: "app_users",
        entity_id: id,
        summary: `Reset password for ${target?.username ?? id}`,
      });
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  const linkEmployeeMutation = useMutation({
    mutationFn: ({ id, employee_id }: { id: string; employee_id: number | null }) =>
      api.put<AppUser>(`/users/${id}/employee-link`, { employee_id }),
    onSuccess: (updated, { employee_id }) => {
      toast.success(t("common.saved"));
      invalidateUsers();
      void logAudit({
        action: employee_id != null ? "employee_linked" : "employee_unlinked",
        entity_type: "app_users",
        entity_id: updated.id,
        summary:
          employee_id != null
            ? `Linked ${updated.username} to employee #${employee_id}`
            : `Unlinked ${updated.username} from their employee record`,
      });
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  const handleRoleChange = (target: AppUser, role: AppUserRole) => {
    if (wouldRemoveLastActiveSuperAdmin(users, target.id, { role })) {
      window.alert(t("detail.error.last_super_admin"));
      return;
    }
    if (target.role === "super_admin" || role === "super_admin") {
      if (!window.confirm(t("detail.confirm.role_change_super_admin"))) return;
    }
    roleMutation.mutate({ id: target.id, role });
  };

  const handleToggleActive = (target: AppUser) => {
    if (target.is_active) {
      if (wouldRemoveLastActiveSuperAdmin(users, target.id, { is_active: false })) {
        window.alert(t("detail.error.last_super_admin"));
        return;
      }
      if (!window.confirm(t("users.confirm_deactivate"))) return;
    }
    toggleActiveMutation.mutate({ id: target.id, is_active: !target.is_active });
  };

  if (!canProvision) {
    return (
      <>
        <PageHeader title={t("nav.employees")} />
        <NoAccess />
      </>
    );
  }

  const summary = computeUserSummary(users, employees);
  const employeeNameById = new Map(employees.map((e) => [e.id, e.full_name]));
  const visibleUsers = filterAndSearchUsers(users, { filter, search, employeeNameById });

  const permissionCountByRole = new Map<string, number>();
  for (const vincoRole of Object.keys(APP_ROLE_TO_SUPABASE_ROLE) as AppUserRole[]) {
    const supaRole = APP_ROLE_TO_SUPABASE_ROLE[vincoRole];
    permissionCountByRole.set(
      vincoRole,
      (supaQuery.data?.rolePermissions ?? []).filter((rp) => rp["role"] === supaRole).length,
    );
  }
  const roleSummary = computeRoleSummary(users, permissionCountByRole);

  const scopeOf = (userId: string) =>
    String(
      (supaQuery.data?.scopes ?? []).find((s) => s["user_id"] === userId)?.["scope"] ?? "assigned",
    );

  const linkedEmployeeFor = (u: AppUser) =>
    u.employee_id != null ? (employeeById.get(u.employee_id) ?? null) : null;

  return (
    <>
      <PageHeader
        title={t("nav.employees")}
        description={t("acc.description")}
        actions={
          <Button className="gap-2" onClick={() => setAddOpen(true)}>
            <Plus className="size-4" /> {t("users.add_vinco_user")}
          </Button>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
        <SummaryCard label={t("acc.summary.total")} value={summary.total} />
        <SummaryCard label={t("acc.summary.active")} value={summary.active} />
        <SummaryCard label={t("acc.summary.inactive")} value={summary.inactive} />
        <SummaryCard label={t("acc.summary.super_admins")} value={summary.byRole.super_admin} />
        <SummaryCard label={t("acc.summary.super_users")} value={summary.byRole.super_user} />
        <SummaryCard label={t("acc.summary.admins")} value={summary.byRole.admin} />
        <SummaryCard label={t("acc.summary.no_employee")} value={summary.usersWithoutEmployee} />
        <SummaryCard label={t("acc.summary.no_access")} value={summary.employeesWithoutAccess} />
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
              filter === f
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-background text-muted-foreground hover:bg-muted"
            }`}
          >
            {t(`acc.filter.${f}`)}
          </button>
        ))}
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("acc.search_placeholder")}
          className="ms-auto h-8 min-w-[220px] rounded-md border border-input bg-background px-3 text-sm"
        />
      </div>

      <div className="surface-panel overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <th className="px-3 py-2.5 text-start">{t("detail.account.employee")}</th>
              <th className="px-3 py-2.5 text-start">{t("users.display_name")}</th>
              <th className="px-3 py-2.5 text-start">{t("users.username")}</th>
              <th className="px-3 py-2.5 text-start">{t("users.role")}</th>
              <th className="px-3 py-2.5 text-start">{t("users.data_scope")}</th>
              <th className="px-3 py-2.5 text-start">{t("users.status")}</th>
              <th className="px-3 py-2.5 text-start">{t("users.last_login")}</th>
              <th className="px-3 py-2.5 text-start">{t("users.created")}</th>
              <th className="px-3 py-2.5 text-start">{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {usersQuery.isLoading && (
              <tr>
                <td colSpan={9} className="px-3 py-8 text-center text-muted-foreground">
                  {t("common.loading")}
                </td>
              </tr>
            )}
            {!usersQuery.isLoading && visibleUsers.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-8 text-center text-muted-foreground">
                  {t("common.empty")}
                </td>
              </tr>
            )}
            {visibleUsers.map((u) => {
              const employee = linkedEmployeeFor(u);
              return (
                <tr key={u.id} className="border-b border-border/70 last:border-0">
                  <td className="px-3 py-2.5">{employee?.full_name ?? "—"}</td>
                  <td className="px-3 py-2.5">
                    <button
                      className="font-medium text-start hover:underline"
                      onClick={() => setViewingUser(u)}
                    >
                      {u.display_name}
                    </button>
                  </td>
                  <td className="px-3 py-2.5 text-muted-foreground">{u.username}</td>
                  <td className="px-3 py-2">
                    <select
                      className="h-9 rounded-md border border-input bg-background px-2 text-sm disabled:opacity-60"
                      value={u.role}
                      disabled={!canManageRoles || roleMutation.isPending}
                      onChange={(e) => handleRoleChange(u, e.target.value as AppUserRole)}
                    >
                      {(Object.keys(ROLE_LABELS) as AppUserRole[]).map((r) => (
                        <option key={r} value={r}>
                          {ROLE_LABELS[r][lang]}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <select
                      className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                      value={scopeOf(u.id)}
                      onChange={(e) => setScope.mutate({ userId: u.id, scope: e.target.value })}
                    >
                      <option value="all">All company data</option>
                      <option value="assigned">Assigned records</option>
                      <option value="own">Own records only</option>
                    </select>
                  </td>
                  <td className="px-3 py-2.5">
                    <StatusBadge value={u.is_active ? "ACTIVE" : "INACTIVE"} />
                  </td>
                  <td className="px-3 py-2.5 text-muted-foreground">
                    {u.last_login_at
                      ? new Date(u.last_login_at).toLocaleDateString(lang === "ar" ? "ar" : "en-US")
                      : t("users.never")}
                  </td>
                  <td className="px-3 py-2.5 text-muted-foreground">
                    {new Date(u.created_at).toLocaleDateString(lang === "ar" ? "ar" : "en-US")}
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={toggleActiveMutation.isPending}
                        onClick={() => handleToggleActive(u)}
                      >
                        {u.is_active ? t("users.deactivate") : t("users.activate")}
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => setResettingPassword(u)}>
                        {t("users.reset_password")}
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="surface-panel mt-4 overflow-x-auto">
        <div className="border-b border-border px-3 py-2.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("acc.roles_title")}
        </div>
        <table className="w-full text-sm">
          <tbody>
            {roleSummary.map((r) => (
              <tr
                key={r.role}
                className="cursor-pointer border-b border-border/70 last:border-0 hover:bg-muted/30"
                onClick={() => setFilter(r.role)}
              >
                <td className="px-3 py-2.5 font-medium">{ROLE_LABELS[r.role][lang]}</td>
                <td className="px-3 py-2.5 text-muted-foreground">
                  {r.permissionCount} {t("acc.roles.permission_count")}
                </td>
                <td className="px-3 py-2.5 text-muted-foreground">
                  {r.userCount} {t("acc.roles.user_count")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <AddVincoUserDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onCreated={(user) =>
          void logAudit({
            action: "user_created",
            entity_type: "app_users",
            entity_id: user.id,
            summary: `Created VINCO login ${user.username}`,
          })
        }
      />

      <ResetVincoPasswordDialog
        user={resettingPassword}
        onOpenChange={(open) => !open && setResettingPassword(null)}
        busy={resetPasswordMutation.isPending}
        onSubmit={(password) =>
          resettingPassword && resetPasswordMutation.mutate({ id: resettingPassword.id, password })
        }
      />

      <UserDetailSheet
        user={viewingUser}
        onOpenChange={(open) => !open && setViewingUser(null)}
        allUsers={users}
        employees={employees}
        linkedEmployee={viewingUser ? linkedEmployeeFor(viewingUser) : null}
        supabaseIdentityExists={
          viewingUser ? (supaQuery.data?.profileIds.has(viewingUser.id) ?? false) : false
        }
        rolePermissions={supaQuery.data?.rolePermissions ?? []}
        userPermissions={supaQuery.data?.userPermissions ?? []}
        onResetPassword={() => viewingUser && setResettingPassword(viewingUser)}
        onToggleActive={() => viewingUser && handleToggleActive(viewingUser)}
        toggleActivePending={toggleActiveMutation.isPending}
        onLinkEmployee={(employeeId) =>
          viewingUser &&
          linkEmployeeMutation.mutate({ id: viewingUser.id, employee_id: employeeId })
        }
        linkEmployeePending={linkEmployeeMutation.isPending}
      />
    </>
  );
}

function SummaryCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="surface-panel px-3 py-3">
      <p className="num text-2xl font-semibold">{value}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}
