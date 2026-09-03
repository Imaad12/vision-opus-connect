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
import { computePermissionOverrideAction, type EmployeeSummary } from "@/lib/vinco-access-control";
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
  canManageOverrides,
  onSetPermissionOverride,
  permissionOverridePending,
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
  /** `admin.roles` -- the same permission the `user_permissions_manage`/
   * `user_roles_manage` RLS policies themselves require (see the
   * `20260818103534_...` migration). Without it the checklist below is
   * shown read-only: this sheet must never let someone toggle a
   * checkbox that the database would silently refuse to write. */
  canManageOverrides: boolean;
  /** Writes (or clears) one `user_permissions` override row -- see
   * `employees.tsx`'s `setPermissionOverrideMutation`, which is the
   * only place this ever actually writes to Supabase. "clear" removes
   * the override entirely so the permission goes back to following
   * whatever the user's role grants by default. */
  onSetPermissionOverride: (permission: string, action: "grant" | "deny" | "clear") => void;
  permissionOverridePending: boolean;
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
  // The backend's own `has_permission()` (see the `20260818103534_...`
  // migration) unconditionally grants a super_admin every permission
  // regardless of role_permissions/user_permissions content -- an
  // editable checklist for this role would be actively misleading,
  // since unchecking a box here could never actually restrict them.
  const isSuperAdmin = supabaseRole === "super_admin";
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
          <Badge variant={user.must_change_password ? "secondary" : "outline"}>
            {user.must_change_password
              ? t("users.password_status.pending")
              : t("users.password_status.ok")}
          </Badge>
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
            <DetailRow label={t("detail.auth.password_changed_at")}>
              {user.password_changed_at
                ? formatDate(user.password_changed_at, lang)
                : t("detail.auth.password_never_changed")}
            </DetailRow>
            {user.must_change_password ? (
              <p className="rounded-md bg-amber-500/10 p-2 text-xs text-amber-700 dark:text-amber-400">
                {t("detail.auth.must_change_password")}
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                {t("detail.auth.password_set_by_user")}
              </p>
            )}
            <p className="text-xs text-muted-foreground">{t("detail.auth.password_note")}</p>
          </TabsContent>

          <TabsContent value="access" className="space-y-4 text-sm">
            <DetailRow label={t("users.role")}>{ROLE_LABELS[user.role][lang]}</DetailRow>

            {isSuperAdmin ? (
              <p className="rounded-md bg-muted/60 p-3 text-xs text-muted-foreground">
                {t("detail.access.super_admin_note")}
              </p>
            ) : (
              <>
                {!canManageOverrides && (
                  <p className="rounded-md bg-muted/60 p-2 text-xs text-muted-foreground">
                    {t("detail.access.read_only_note")}
                  </p>
                )}
                <p className="text-xs text-muted-foreground">{t("detail.access.checklist_hint")}</p>
                <div className="space-y-4">
                  {PERMISSION_GROUPS.map((group) => (
                    <div key={group.key}>
                      <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        {lang === "ar" ? group.ar : group.en}
                      </p>
                      <div className="space-y-1 rounded-md border border-border/70 p-2">
                        {group.permissions.map((p) => {
                          const isGranted = grantedDirectly.includes(p);
                          const isDenied = deniedDirectly.includes(p);
                          const isOverridden = isGranted || isDenied;
                          const isChecked = effective.has(p);
                          return (
                            <div key={p} className="flex items-center justify-between gap-2 py-0.5">
                              <label className="flex flex-1 items-center gap-2">
                                <input
                                  type="checkbox"
                                  checked={isChecked}
                                  disabled={!canManageOverrides || permissionOverridePending}
                                  onChange={(e) =>
                                    onSetPermissionOverride(
                                      p,
                                      computePermissionOverrideAction(
                                        e.target.checked,
                                        rolePerms.has(p),
                                      ),
                                    )
                                  }
                                />
                                <span className="text-xs">{p}</span>
                              </label>
                              {isOverridden && (
                                <div className="flex items-center gap-1.5">
                                  <Badge
                                    variant={isGranted ? "default" : "destructive"}
                                    className="text-[10px] font-normal"
                                  >
                                    {isGranted
                                      ? t("detail.access.granted_directly")
                                      : t("detail.access.denied_directly")}
                                  </Badge>
                                  {canManageOverrides && (
                                    <button
                                      type="button"
                                      className="text-[10px] text-muted-foreground underline-offset-2 hover:underline"
                                      onClick={() => onSetPermissionOverride(p, "clear")}
                                    >
                                      {t("detail.access.reset_to_role_default")}
                                    </button>
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
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
