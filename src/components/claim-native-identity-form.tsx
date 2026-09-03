import { useState, type FormEvent } from "react";

import { TemporaryPasswordReveal } from "@/components/temporary-password-reveal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { AppUserCreateResult } from "@/lib/vinco-users";

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.describe();
  if (e instanceof Error) return e.message;
  return String(e);
}

/**
 * Self-service migration path for a real, already-signed-in Supabase
 * identity with no `vinco.app_users` row -- the exact shape of the
 * production Super Admin account, which was bootstrapped by
 * `handle_new_user()`'s "first Supabase user ever = super_admin"
 * trigger (see supabase/migrations) rather than through the native
 * `POST /users` flow. `GET /users/me` 404ing for such an account is
 * also why `ChangePasswordDialog` used to render nothing at all for it
 * (see that component) -- this form is what it renders instead.
 *
 * Calls `POST /users/me/claim` (`backend/app/api/routers/users.py`),
 * which never creates a new Supabase identity: it repoints THIS SAME
 * one's login email at the synthetic `<username>@vinco.local` address
 * and sets a fresh temporary password on it, mirroring the caller's
 * own already-existing Supabase role (never accepted from this form).
 */
export function ClaimNativeIdentityForm({ onDone }: { onDone: () => void }) {
  const { t } = useI18n();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [claimed, setClaimed] = useState<AppUserCreateResult | null>(null);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    api
      .post<AppUserCreateResult>("/users/me/claim", { username, display_name: displayName })
      .then((result) => setClaimed(result))
      .catch((err: unknown) => setError(errorMessage(err)))
      .finally(() => setBusy(false));
  };

  if (claimed) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">{t("users.claim.success_note")}</p>
        <TemporaryPasswordReveal
          username={claimed.username}
          temporaryPassword={claimed.temporary_password}
          onDone={onDone}
        />
      </div>
    );
  }

  return (
    <form className="space-y-4" onSubmit={handleSubmit}>
      <p className="text-sm text-muted-foreground">{t("users.claim.description")}</p>
      <div className="space-y-1.5">
        <Label htmlFor="claim-display-name">{t("users.display_name")}</Label>
        <Input
          id="claim-display-name"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          required
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="claim-username">{t("users.username")}</Label>
        <Input
          id="claim-username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="off"
          required
        />
      </div>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      <Button type="submit" disabled={busy} className="w-full">
        {busy ? t("users.claim.submitting") : t("users.claim.submit")}
      </Button>
    </form>
  );
}
