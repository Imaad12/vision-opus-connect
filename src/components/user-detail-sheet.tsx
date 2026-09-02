import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PERMISSION_GROUPS } from "@/hooks/use-auth";
import { db, type Row } from "@/lib/db";
import { formatDate, useI18n } from "@/lib/i18n";
import type { EmployeeSummary } from "@/lib/vinco-access-control";
import { APP_ROLE_TO_SUPABASE_ROLE, ROLE_LABELS, type AppUser } from "@/lib/vinco-users";

type LinkedEmployee = EmployeeSummary & { email: string | null };

/**
 * The Part 4 "user detail / access profile" view: Account, Authentication
 * (Part 12's safe login diagnostics live here), Access (effective
 * permissions grouped by module -- Part 6, using the real permission
 * names/groups already defined in `use-auth.ts`'s `PERMISSION_GROUPS`,
 * not a second permission vocabulary), Recovery (Part 7), and Activity
 * (that user's own slice of the existing `audit_logs` table).
 *
 * Destructive/privileged actions (reset password, activate/deactivate)
 * are NOT owned here -- they call back into `employees.tsx`, which
 * already owns those mutations and the Part 13 last-active-Super-Admin
 * guard, so there is exactly one place each of those actions is wired,
 * not a second copy inside this sheet.
 */
export function UserDetailSheet({
  user,
  onOpenChange,
  allUsers,
  employees,
  linkedEmployee,
  supabaseIdentityExists,
  rolePermissions,
  userPermissions,
  onResetPassword,
  onToggleActive,
  toggleActivePending,
  onLinkEmployee,
  linkEmployeePending,
}: {
  user: AppUser | null;
  onOpenChange: (open: boolean) => void;
  allUsers: AppUser[];
  employees: EmployeeSummary[];
  linkedEmployee: LinkedEmployee | null;
  supabaseIdentityExists: boolean;
  rolePermissions: Row[];
  userPermissions: Row[];
  onResetPassword: () => void;
  onToggleActive: () => void;
  toggleActivePending: boolean;
  onLinkEmployee: (employeeId: number | null) => void;
  linkEmployeePending: boolean;
}) {
  const { t, lang } = useI18n();
  const [linking, setLinking] = useState(false);
  const [linkTarget, setLinkTarget] = useState("");

  const activityQuery = useQuery({
    queryKey: ["audit-logs", "app_users", user?.id],
    enabled: user !== null,
    queryFn: async () => {
      const { data } = await db
        .from("audit_logs")
        .select("*")
        .eq("entity_type", "app_users")
        .eq("entity_id", user!.id)
        .order("created_at", { ascending: false })
        .limit(50);
      return (data ?? []) as Row[];
    },
  });

  if (!user) return null;

  const supabaseRole = APP_ROLE_TO_SUPABASE_ROLE[user.role];
  const rolePerms = new Set(
    rolePermissions
      .filter((rp) => rp["role"] === supabaseRole)
      .map((rp) => String(rp["permission"])),
  );
  const myOverrides = userPermissions.filter((up) => up["user_id"] === user.id);
  const grantedDirectly = myOverrides
    .filter((o) => o["granted"] === true)
    .map((o) => String(o["permission"]));
  const deniedDirectly = myOverrides
    .filter((o) => o["granted"] === false)
    .map((o) => String(o["permission"]));
  const effective = new Set(rolePerms);
  for (const p of grantedDirectly) effective.add(p);
  for (const p of deniedDirectly) effective.delete(p);

  const unlinkedEmployees = employees.filter(
    (e) => e.id === user.employee_id || !allUsers.some((u) => u.employee_id === e.id),
  );

  return (
    <Sheet open={user !== null} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{user.display_name}</SheetTitle>
          <SheetDescription>@{user.username}</SheetDescription>
        </SheetHeader>

        <div className="mt-4 flex flex-wrap gap-2">
          <Badge variant={user.is_active ? "default" : "secondary"}>
            {user.is_active ? t("acc.filter.active") : t("acc.filter.inactive")}
          </Badge>
          <Badge variant="outline">{ROLE_LABELS[user.role][lang]}</Badge>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={onResetPassword}>
            {t("users.reset_password")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={toggleActivePending}
            onClick={onToggleActive}
          >
            {user.is_active ? t("users.deactivate") : t("users.activate")}
          </Button>
        </div>

        <Tabs defaultValue="account" className="mt-5">
          <TabsList className="grid w-full grid-cols-5">
            <TabsTrigger value="account">{t("detail.tab.account")}</TabsTrigger>
            <TabsTrigger value="auth">{t("detail.tab.authentication")}</TabsTrigger>
            <TabsTrigger value="access">{t("detail.tab.access")}</TabsTrigger>
            <TabsTrigger value="recovery">{t("detail.tab.recovery")}</TabsTrigger>
            <TabsTrigger value="activity">{t("detail.tab.activity")}</TabsTrigger>
          </TabsList>

          <TabsContent value="account" className="space-y-3 text-sm">
            <DetailRow label={t("detail.account.employee")}>
              {linkedEmployee ? (
                <div className="flex items-center gap-2">
                  <span>{linkedEmployee.full_name}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={linkEmployeePending}
                    onClick={() => {
                      if (window.confirm(t("detail.confirm.unlink_employee"))) onLinkEmployee(null);
                    }}
                  >
                    {t("detail.action.unlink_employee")}
                  </Button>
                </div>
              ) : linking ? (
                <div className="flex items-center gap-2">
                  <select
                    className="h-8 rounded-md border border-input bg-background px-2 text-xs"
                    value={linkTarget}
                    onChange={(e) => setLinkTarget(e.target.value)}
                  >
                    <option value="">{t("users.select_employee")}</option>
                    {unlinkedEmployees.map((e) => (
                      <option key={e.id} value={String(e.id)}>
                        {e.full_name}
                      </option>
                    ))}
                  </select>
                  <Button
                    size="sm"
                    disabled={!linkTarget || linkEmployeePending}
                    onClick={() => {
                      onLinkEmployee(Number(linkTarget));
                      setLinking(false);
                      setLinkTarget("");
                    }}
                  >
                    {t("common.save")}
                  </Button>
                </div>
              ) : (
                <Button variant="ghost" size="sm" onClick={() => setLinking(true)}>
                  {t("detail.action.link_employee")}
                </Button>
              )}
            </DetailRow>
            <DetailRow label={t("users.created")}>{formatDate(user.created_at, lang)}</DetailRow>
            <DetailRow label={t("users.last_login")}>
              {user.last_login_at ? formatDate(user.last_login_at, lang) : t("users.never")}
            </DetailRow>
            <DetailRow label={t("detail.account.updated")}>
              {formatDate(user.updated_at, lang)}
            </DetailRow>
          </TabsContent>

          <TabsContent value="auth" className="space-y-3 text-sm">
            <DetailRow label={t("detail.auth.login_identity")}>
              <code className="text-xs">{user.username}@vinco.local</code>
            </DetailRow>
            <DiagnosticLine ok label={t("detail.auth.vinco_account_exists")} />
            <DiagnosticLine
              ok={supabaseIdentityExists}
              label={t("detail.auth.supabase_identity_exists")}
            />
            <DiagnosticLine ok={user.is_active} label={t("detail.auth.account_active")} />
            <DiagnosticLine
              ok={user.employee_id != null}
              label={t("detail.auth.employee_linked")}
            />
            {!supabaseIdentityExists && (
              <p className="rounded-md bg-destructive/10 p-2 text-xs text-destructive">
                {t("detail.auth.supabase_identity_missing")}
              </p>
            )}
            <p className="text-xs text-muted-foreground">{t("detail.auth.password_note")}</p>
          </TabsContent>

          <TabsContent value="access" className="space-y-4 text-sm">
            <DetailRow label={t("users.role")}>{ROLE_LABELS[user.role][lang]}</DetailRow>
            {deniedDirectly.length > 0 || grantedDirectly.length > 0 ? (
              <div className="space-y-1">
                {grantedDirectly.map((p) => (
                  <div key={p} className="flex items-center justify-between text-xs">
                    <span>{p}</span>
                    <Badge variant="default">{t("detail.access.granted_directly")}</Badge>
                  </div>
                ))}
                {deniedDirectly.map((p) => (
                  <div key={p} className="flex items-center justify-between text-xs">
                    <span>{p}</span>
                    <Badge variant="destructive">{t("detail.access.denied_directly")}</Badge>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">{t("detail.access.no_overrides")}</p>
            )}
            <div>
              <p className="mb-2 font-medium">{t("detail.access.effective_permissions")}</p>
              <div className="space-y-3">
                {PERMISSION_GROUPS.map((group) => {
                  const held = group.permissions.filter((p) => effective.has(p));
                  if (held.length === 0) return null;
                  return (
                    <div key={group.key}>
                      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        {lang === "ar" ? group.ar : group.en}
                      </p>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {held.map((p) => (
                          <Badge key={p} variant="outline" className="font-normal">
                            {p}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </TabsContent>

          <TabsContent value="recovery" className="space-y-4 text-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {t("detail.recovery.title")}
            </p>
            <div className="rounded-md border border-border p-3">
              <p className="font-medium">{t("detail.recovery.admin_reset")}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("detail.recovery.admin_reset_desc")}
              </p>
              <Button variant="outline" size="sm" className="mt-2" onClick={onResetPassword}>
                {t("users.reset_password")}
              </Button>
            </div>
            <div className="rounded-md border border-border p-3">
              <div className="flex items-center justify-between">
                <p className="font-medium">{t("detail.recovery.email")}</p>
                <Badge variant={linkedEmployee?.email ? "secondary" : "outline"}>
                  {linkedEmployee?.email
                    ? t("detail.recovery.configured")
                    : t("detail.recovery.not_configured")}
                </Badge>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {linkedEmployee?.email
                  ? t("detail.recovery.configured_desc")
                  : t("detail.recovery.not_configured_desc")}
              </p>
            </div>
          </TabsContent>

          <TabsContent value="activity" className="space-y-2 text-sm">
            {activityQuery.isLoading && (
              <p className="text-muted-foreground">{t("common.loading")}</p>
            )}
            {!activityQuery.isLoading && (activityQuery.data ?? []).length === 0 && (
              <p className="text-muted-foreground">{t("detail.activity.empty")}</p>
            )}
            {(activityQuery.data ?? []).map((log) => (
              <div key={String(log["id"])} className="border-b border-border/70 pb-2 last:border-0">
                <p className="text-xs">{String(log["summary"] ?? log["action"])}</p>
                <p className="text-xs text-muted-foreground">
                  {String(log["actor_name"] ?? "—")} ·{" "}
                  {formatDate(log["created_at"] as string, lang)}
                </p>
              </div>
            ))}
          </TabsContent>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{children}</span>
    </div>
  );
}

function DiagnosticLine({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className={ok ? "text-emerald-600" : "text-destructive"}>{ok ? "✓" : "✗"}</span>
      <span>{label}</span>
    </div>
  );
}
