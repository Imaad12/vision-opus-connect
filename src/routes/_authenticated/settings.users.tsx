import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Loader2, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { NoAccess, PageHeader } from "@/components/app-shell";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useMe } from "@/hooks/use-auth";
import { ApiError, api } from "@/lib/api";
import { formatDate, useI18n, type Lang } from "@/lib/i18n";

/**
 * Native VINCO user management -- creates/edits real accounts (username
 * + password) via the backend's /users routes (app/api/routers/users.py),
 * which are the ONLY thing that can create a Supabase Auth identity
 * (needs the service-role key, which only the backend holds -- see
 * app/api/auth.py's SupabaseAdmin). Distinct from the existing
 * /employees page: that page assigns a Supabase role to any EXISTING
 * Supabase identity (e.g. one that signed in via Google OAuth); this
 * page is specifically for creating and managing native
 * username/password accounts. Both remain useful and neither replaces
 * the other.
 */

type AppUserRole = "employee" | "admin" | "super_user" | "super_admin";

type AppUser = {
  id: string;
  username: string;
  display_name: string;
  role: AppUserRole;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  last_login_at: string | null;
};

const ROLE_LABELS: Record<AppUserRole, { en: string; ar: string }> = {
  employee: { en: "Employee", ar: "موظف" },
  admin: { en: "Admin", ar: "مسؤول" },
  super_user: { en: "Super User", ar: "مستخدم متميز" },
  super_admin: { en: "Super Admin", ar: "مسؤول النظام" },
};

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.describe();
  if (e instanceof Error) return e.message;
  return String(e);
}

export const Route = createFileRoute("/_authenticated/settings/users")({
  head: () => ({
    meta: [
      { title: "Users & Access — VINCO ERP" },
      { name: "description", content: "Create and manage VINCO user accounts, roles, and access." },
    ],
  }),
  component: UsersAccessPage,
});

function UsersAccessPage() {
  const { t, lang } = useI18n();
  const me = useMe();
  const queryClient = useQueryClient();
  const canManage = me.can("admin.users");
  const canManageRoles = me.can("admin.roles");

  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<AppUser | null>(null);
  const [resettingPassword, setResettingPassword] = useState<AppUser | null>(null);

  const usersQuery = useQuery({
    queryKey: ["app-users"],
    enabled: canManage,
    queryFn: () => api.get<AppUser[]>("/users"),
  });

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ["app-users"] });

  const createMutation = useMutation({
    mutationFn: (payload: {
      username: string;
      display_name: string;
      password: string;
      role: AppUserRole;
      is_active: boolean;
    }) => api.post<AppUser>("/users", payload),
    onSuccess: () => {
      toast.success(t("common.saved"));
      setCreateOpen(false);
      invalidate();
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      ...payload
    }: {
      id: string;
      display_name?: string;
      is_active?: boolean;
    }) => api.put<AppUser>(`/users/${id}`, payload),
    onSuccess: () => {
      toast.success(t("common.saved"));
      setEditing(null);
      invalidate();
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  const roleMutation = useMutation({
    mutationFn: ({ id, role }: { id: string; role: AppUserRole }) =>
      api.put<AppUser>(`/users/${id}/role`, { role }),
    onSuccess: () => {
      toast.success(t("common.saved"));
      invalidate();
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

  if (!canManage) {
    return (
      <>
        <PageHeader title={t("users.title")} />
        <NoAccess />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={t("users.title")}
        description={t("users.description")}
        actions={
          <Button className="gap-2" onClick={() => setCreateOpen(true)}>
            <Plus className="size-4" /> {t("users.add")}
          </Button>
        }
      />

      <div className="surface-panel overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <th className="px-3 py-2.5 text-start">{t("common.details")}</th>
              <th className="px-3 py-2.5 text-start">{t("users.username")}</th>
              <th className="px-3 py-2.5 text-start">{t("users.role")}</th>
              <th className="px-3 py-2.5 text-start">{t("common.status")}</th>
              <th className="px-3 py-2.5 text-start">{t("users.last_login")}</th>
              <th className="px-3 py-2.5 text-start">{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {usersQuery.isLoading && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-muted-foreground">
                  {t("common.loading")}
                </td>
              </tr>
            )}
            {usersQuery.isError && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-destructive">
                  {t("common.load_failed")}: {errorMessage(usersQuery.error)}
                </td>
              </tr>
            )}
            {!usersQuery.isLoading && !usersQuery.isError && (usersQuery.data ?? []).length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-muted-foreground">
                  {t("common.empty")}
                </td>
              </tr>
            )}
            {(usersQuery.data ?? []).map((u) => (
              <tr key={u.id} className="border-b border-border/70 last:border-0">
                <td className="px-3 py-2.5 font-medium">{u.display_name}</td>
                <td className="px-3 py-2.5 text-muted-foreground">{u.username}</td>
                <td className="px-3 py-2">
                  <select
                    className="h-9 rounded-md border border-input bg-background px-2 text-sm disabled:opacity-60"
                    value={u.role}
                    disabled={!canManageRoles || roleMutation.isPending}
                    onChange={(e) => roleMutation.mutate({ id: u.id, role: e.target.value as AppUserRole })}
                  >
                    {(Object.keys(ROLE_LABELS) as AppUserRole[]).map((r) => (
                      <option key={r} value={r}>
                        {ROLE_LABELS[r][lang]}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="px-3 py-2.5">
                  <StatusBadge value={u.is_active ? "ACTIVE" : "INACTIVE"} />
                </td>
                <td className="px-3 py-2.5 text-muted-foreground">
                  {u.last_login_at ? formatDate(u.last_login_at, lang) : t("common.none")}
                </td>
                <td className="px-3 py-2.5">
                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" size="sm" onClick={() => setEditing(u)}>
                      {t("common.edit")}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={updateMutation.isPending}
                      onClick={() => updateMutation.mutate({ id: u.id, is_active: !u.is_active })}
                    >
                      {u.is_active ? t("users.deactivate") : t("users.activate")}
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setResettingPassword(u)}>
                      {t("users.reset_password")}
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <CreateUserDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        busy={createMutation.isPending}
        onSubmit={(payload) => createMutation.mutate(payload)}
        lang={lang}
      />

      <EditUserDialog
        key={editing?.id ?? "none"}
        user={editing}
        onOpenChange={(open) => !open && setEditing(null)}
        busy={updateMutation.isPending}
        onSubmit={(payload) => editing && updateMutation.mutate({ id: editing.id, ...payload })}
      />

      <ResetPasswordDialog
        user={resettingPassword}
        onOpenChange={(open) => !open && setResettingPassword(null)}
        busy={resetPasswordMutation.isPending}
        onSubmit={(password) =>
          resettingPassword && resetPasswordMutation.mutate({ id: resettingPassword.id, password })
        }
      />
    </>
  );
}

function CreateUserDialog({
  open,
  onOpenChange,
  busy,
  onSubmit,
  lang,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  busy: boolean;
  onSubmit: (payload: {
    username: string;
    display_name: string;
    password: string;
    role: AppUserRole;
    is_active: boolean;
  }) => void;
  lang: Lang;
}) {
  const { t } = useI18n();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [role, setRole] = useState<AppUserRole>("employee");
  const [active, setActive] = useState(true);
  const [formError, setFormError] = useState<string | null>(null);

  const reset = () => {
    setUsername("");
    setDisplayName("");
    setPassword("");
    setConfirmPassword("");
    setRole("employee");
    setActive(true);
    setFormError(null);
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (password !== confirmPassword) {
      setFormError(t("users.password_mismatch"));
      return;
    }
    if (password.length < 8) {
      setFormError(t("users.password_too_short"));
      return;
    }
    setFormError(null);
    onSubmit({ username, display_name: displayName, password, role, is_active: active });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("users.add")}</DialogTitle>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-1.5">
            <Label htmlFor="new-user-display-name">{t("users.display_name")}</Label>
            <Input
              id="new-user-display-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-user-username">{t("users.username")}</Label>
            <Input
              id="new-user-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="off"
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-user-password">{t("auth.password")}</Label>
            <Input
              id="new-user-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-user-confirm-password">{t("users.confirm_password")}</Label>
            <Input
              id="new-user-confirm-password"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-user-role">{t("users.role")}</Label>
            <select
              id="new-user-role"
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
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            {t("common.status")}: {active ? t("users.activate") : t("users.deactivate")}
          </label>
          {formError ? <p className="text-sm text-destructive">{formError}</p> : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={busy} className="gap-2">
              {busy ? <Loader2 className="size-4 animate-spin" /> : null}
              {t("users.add")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EditUserDialog({
  user,
  onOpenChange,
  busy,
  onSubmit,
}: {
  user: AppUser | null;
  onOpenChange: (open: boolean) => void;
  busy: boolean;
  onSubmit: (payload: { display_name: string }) => void;
}) {
  const { t } = useI18n();
  // Initialized once from `user` -- safe because the parent remounts
  // this component (`key={editing?.id}`) every time a different user is
  // being edited, so this never needs to re-seed after mount.
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");

  return (
    <Dialog open={user !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("common.edit")}</DialogTitle>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit({ display_name: displayName });
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="edit-user-display-name">{t("users.display_name")}</Label>
            <Input
              id="edit-user-display-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={busy} className="gap-2">
              {busy ? <Loader2 className="size-4 animate-spin" /> : null}
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ResetPasswordDialog({
  user,
  onOpenChange,
  busy,
  onSubmit,
}: {
  user: AppUser | null;
  onOpenChange: (open: boolean) => void;
  busy: boolean;
  onSubmit: (password: string) => void;
}) {
  const { t } = useI18n();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (password !== confirmPassword) {
      setFormError(t("users.password_mismatch"));
      return;
    }
    if (password.length < 8) {
      setFormError(t("users.password_too_short"));
      return;
    }
    onSubmit(password);
    setPassword("");
    setConfirmPassword("");
    setFormError(null);
  };

  return (
    <Dialog open={user !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {t("users.reset_password")} — {user?.display_name}
          </DialogTitle>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-1.5">
            <Label htmlFor="reset-password-new">{t("users.new_password")}</Label>
            <Input
              id="reset-password-new"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="reset-password-confirm">{t("users.confirm_password")}</Label>
            <Input
              id="reset-password-confirm"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </div>
          {formError ? <p className="text-sm text-destructive">{formError}</p> : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={busy} className="gap-2">
              {busy ? <Loader2 className="size-4 animate-spin" /> : null}
              {t("users.reset_password")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
