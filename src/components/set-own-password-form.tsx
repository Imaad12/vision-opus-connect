import { Loader2 } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useI18n } from "@/lib/i18n";
import { changeOwnPassword, type ChangeOwnPasswordFailureKind } from "@/lib/vinco-auth";

/**
 * Current/new/confirm password form shared by the forced first-login
 * gate (Part B3 -- `forced-password-change-gate.tsx`) and logged-in
 * users' self-service "Change Password" (Part B5). Both call the exact
 * same `changeOwnPassword` (`vinco-auth.ts`), which only ever affects
 * the caller's own account -- there is no user-id input anywhere in
 * this form.
 */
export function SetOwnPasswordForm({
  username,
  onSuccess,
  submitLabel,
  submittingLabel,
}: {
  username: string;
  onSuccess: () => void;
  submitLabel: string;
  submittingLabel: string;
}) {
  const { t } = useI18n();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [errorKind, setErrorKind] = useState<ChangeOwnPasswordFailureKind | null>(null);
  const submittingRef = useRef(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (submittingRef.current) return;
    submittingRef.current = true;
    setErrorKind(null);
    setBusy(true);
    const result = await changeOwnPassword(username, currentPassword, newPassword, confirmPassword);
    setBusy(false);
    submittingRef.current = false;
    if (!result.ok) {
      setErrorKind(result.kind);
      return;
    }
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    onSuccess();
  };

  const errorMessage = (() => {
    switch (errorKind) {
      case null:
        return null;
      case "mismatch":
        return t("users.password_mismatch");
      case "too_short":
        return t("users.password_too_short");
      case "wrong_current":
        return t("auth.set_password.wrong_current");
      case "network":
        return t("auth.error.network");
      case "unknown":
        return t("auth.set_password.unknown_error");
    }
  })();

  return (
    <form className="space-y-4" onSubmit={handleSubmit}>
      <div className="space-y-1.5">
        <Label htmlFor="own-current-password">{t("users.current_password")}</Label>
        <Input
          id="own-current-password"
          type="password"
          autoComplete="current-password"
          value={currentPassword}
          onChange={(e) => setCurrentPassword(e.target.value)}
          disabled={busy}
          required
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="own-new-password">{t("users.new_password")}</Label>
        <Input
          id="own-new-password"
          type="password"
          autoComplete="new-password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          disabled={busy}
          required
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="own-confirm-password">{t("users.confirm_password")}</Label>
        <Input
          id="own-confirm-password"
          type="password"
          autoComplete="new-password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          disabled={busy}
          required
        />
      </div>
      {errorMessage ? <p className="text-sm text-destructive">{errorMessage}</p> : null}
      <Button type="submit" className="w-full gap-2" disabled={busy}>
        {busy ? <Loader2 className="size-4 animate-spin" /> : null}
        {busy ? submittingLabel : submitLabel}
      </Button>
    </form>
  );
}
