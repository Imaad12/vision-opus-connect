import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { toast } from "sonner";

import { NoAccess, PageHeader } from "@/components/app-shell";
import { ROLE_LABELS, useMe, type AppRole } from "@/hooks/use-auth";
import { db, type Row } from "@/lib/db";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/_authenticated/employees")({
  head: () => ({
    meta: [
      { title: "Employees & roles — VINCO ERP" },
      {
        name: "description",
        content: "Assign employee roles and data scope so each team sees only what their job requires.",
      },
      { property: "og:title", content: "Employees & roles — VINCO ERP" },
      { property: "og:description", content: "Role and data-scope administration." },
    ],
  }),
  component: EmployeesPage,
});

function EmployeesPage() {
  const { t, lang } = useI18n();
  const me = useMe();
  const queryClient = useQueryClient();
  const allowed = me.canAny(["admin.users", "admin.roles"]);

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
      <PageHeader title={t("nav.employees")} description={t("emp.manage")} />
      <div className="surface-panel overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <th className="px-3 py-2.5 text-start">{t("common.details")}</th>
              <th className="px-3 py-2.5 text-start">{t("emp.roles")}</th>
              <th className="px-3 py-2.5 text-start">{t("emp.scope")}</th>
            </tr>
          </thead>
          <tbody>
            {(data.data?.profiles ?? []).map((p) => {
              const id = String(p["id"]);
              return (
                <tr key={id} className="border-b border-border/70 last:border-0">
                  <td className="px-3 py-2.5">
                    <p className="font-medium">{String(p["full_name"] || p["email"] || "—")}</p>
                    <p className="text-xs text-muted-foreground">{String(p["email"] ?? "")}</p>
                  </td>
                  <td className="px-3 py-2">
                    <select
                      className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                      value={roleOf(id)}
                      onChange={(e) => setRole.mutate({ userId: id, role: e.target.value })}
                    >
                      <option value="">{t("common.none")}</option>
                      {(Object.keys(ROLE_LABELS) as AppRole[]).map((r) => (
                        <option key={r} value={r}>
                          {ROLE_LABELS[r][lang]}
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
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
