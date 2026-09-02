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
import { useMe, ROLE_LABELS as SUPABASE_ROLE_LABELS, type AppRole } from "@/hooks/use-auth";
import { ApiError, api } from "@/lib/api";
import { db, type Row } from "@/lib/db";
import { useI18n } from "@/lib/i18n";
import { type AppUser } from "@/lib/vinco-users";

export const Route = createFileRoute("/_authenticated/employees")({
  head: () => ({
    meta: [
      { title: "Employees & roles — VINCO ERP" },
      {
        name: "description",
        content: "Give employees VINCO access, assign roles, and manage data scope.",
      },
      { property: "og:title", content: "Employees & roles — VINCO ERP" },
      { property: "og:description", content: "Role and data-scope administration." },
    ],
  }),
  component: EmployeesPage,
});

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.describe();
  if (e instanceof Error) return e.message;
  return String(e);
}

function EmployeesPage() {
  const { t, lang } = useI18n();
  const me = useMe();
  const queryClient = useQueryClient();
  const allowed = me.canAny(["admin.users", "admin.roles"]);
  const canProvision = me.can("admin.users");

  const [addOpen, setAddOpen] = useState(false);
  const [resettingPassword, setResettingPassword] = useState<AppUser | null>(null);

  // The existing role/data-scope editor (unchanged below): every
  // Supabase profile, not just ones with a native VINCO login -- a
  // legacy or Google-linked identity can still be role-assigned here.
  const data = useQuery({
    queryKey: ["employees"],
    enabled: allowed,
    queryFn: async () => {
      const [profiles, roles, scopes] = await Promise.all([
        db.from("profiles").select("*").order("full_name"),
        db.from("user_roles").select("user_id, role"),
        db.from("user_scopes").select("user_id, scope"),
      ]);
      return {
        profiles: (profiles.data ?? []) as Row[],
        roles: (roles.data ?? []) as Row[],
        scopes: (scopes.data ?? []) as Row[],
      };
    },
  });

  // Native VINCO logins -- for the added Username/Status/Actions columns
  // and the "+ Add VINCO User" workflow. Same `["app-users"]` query the
  // existing Users & Access page and the shared dialog use, so a create/
  // reset/deactivate from any of them keeps this page's view current.
  const usersQuery = useQuery({
    queryKey: ["app-users"],
    enabled: canProvision,
    queryFn: () => api.get<AppUser[]>("/users"),
  });
  const appUserByProfileId = new Map((usersQuery.data ?? []).map((u) => [u.id, u]));

  const setRole = useMutation({
    mutationFn: async ({ userId, role }: { userId: string; role: string }) => {
      const del = await db.from("user_roles").delete().eq("user_id", userId);
      if (del.error) throw del.error;
      const ins = await db.from("user_roles").insert({ user_id: userId, role });
      if (ins.error) throw ins.error;
    },
    onSuccess: () => {
      toast.success(t("common.saved"));
      void queryClient.invalidateQueries({ queryKey: ["employees"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const setScope = useMutation({
    mutationFn: async ({ userId, scope }: { userId: string; scope: string }) => {
      const { error } = await db
        .from("user_scopes")
        .upsert({ user_id: userId, scope }, { onConflict: "user_id" });
      if (error) throw error;
    },
    onSuccess: () => {
      toast.success(t("common.saved"));
      void queryClient.invalidateQueries({ queryKey: ["employees"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const toggleActiveMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      api.put<AppUser>(`/users/${id}`, { is_active }),
    onSuccess: () => {
      toast.success(t("common.saved"));
      void queryClient.invalidateQueries({ queryKey: ["app-users"] });
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  const resetPasswordMutation = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) =>
      api.post<void>(`/users/${id}/reset-password`, { password }),
    onSuccess: () => {
      toast.success(t("common.saved"));
      setResettingPassword(null);
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  if (!allowed) {
    return (
      <>
        <PageHeader title={t("nav.employees")} />
        <NoAccess />
      </>
    );
  }

  const roleOf = (id: string) =>
    String((data.data?.roles ?? []).find((r) => r["user_id"] === id)?.["role"] ?? "");
  const scopeOf = (id: string) =>
    String((data.data?.scopes ?? []).find((r) => r["user_id"] === id)?.["scope"] ?? "assigned");

  return (
    <>
      <PageHeader
        title={t("nav.employees")}
        description={t("emp.manage")}
        actions={
          canProvision ? (
            <Button className="gap-2" onClick={() => setAddOpen(true)}>
              <Plus className="size-4" /> {t("users.add_vinco_user")}
            </Button>
          ) : undefined
        }
      />
      <div className="surface-panel overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <th className="px-3 py-2.5 text-start">{t("common.details")}</th>
              <th className="px-3 py-2.5 text-start">{t("users.username")}</th>
              <th className="px-3 py-2.5 text-start">{t("emp.roles")}</th>
              <th className="px-3 py-2.5 text-start">{t("emp.scope")}</th>
              <th className="px-3 py-2.5 text-start">{t("users.status")}</th>
              <th className="px-3 py-2.5 text-start">{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {(data.data?.profiles ?? []).map((p) => {
              const id = String(p["id"]);
              const appUser = appUserByProfileId.get(id);
              return (
                <tr key={id} className="border-b border-border/70 last:border-0">
                  <td className="px-3 py-2.5">
                    <p className="font-medium">{String(p["full_name"] || p["email"] || "—")}</p>
                    <p className="text-xs text-muted-foreground">{String(p["email"] ?? "")}</p>
                  </td>
                  <td className="px-3 py-2.5 text-muted-foreground">{appUser?.username ?? "—"}</td>
                  <td className="px-3 py-2">
                    <select
                      className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                      value={roleOf(id)}
                      onChange={(e) => setRole.mutate({ userId: id, role: e.target.value })}
                    >
                      <option value="">{t("common.none")}</option>
                      {(Object.keys(SUPABASE_ROLE_LABELS) as AppRole[]).map((r) => (
                        <option key={r} value={r}>
                          {SUPABASE_ROLE_LABELS[r][lang]}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <select
                      className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                      value={scopeOf(id)}
                      onChange={(e) => setScope.mutate({ userId: id, scope: e.target.value })}
                    >
                      <option value="all">All company data</option>
                      <option value="assigned">Assigned records</option>
                      <option value="own">Own records only</option>
                    </select>
                  </td>
                  <td className="px-3 py-2.5">
                    {appUser ? (
                      <StatusBadge value={appUser.is_active ? "ACTIVE" : "INACTIVE"} />
                    ) : (
                      <span className="text-xs text-muted-foreground">
                        {t("users.no_vinco_login")}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    {appUser && canProvision ? (
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={toggleActiveMutation.isPending}
                          onClick={() => {
                            if (appUser.is_active && !window.confirm(t("users.confirm_deactivate")))
                              return;
                            toggleActiveMutation.mutate({
                              id: appUser.id,
                              is_active: !appUser.is_active,
                            });
                          }}
                        >
                          {appUser.is_active ? t("users.deactivate") : t("users.activate")}
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setResettingPassword(appUser)}
                        >
                          {t("users.reset_password")}
                        </Button>
                      </div>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {canProvision && (
        <>
          <AddVincoUserDialog open={addOpen} onOpenChange={setAddOpen} />

          <ResetVincoPasswordDialog
            user={resettingPassword}
            onOpenChange={(open) => !open && setResettingPassword(null)}
            busy={resetPasswordMutation.isPending}
            onSubmit={(password) =>
              resettingPassword &&
              resetPasswordMutation.mutate({ id: resettingPassword.id, password })
            }
          />
        </>
      )}
    </>
  );
}
