import { Loader2 } from "lucide-react";
import { useState, type FormEvent } from "react";

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
import { useI18n } from "@/lib/i18n";

/**
 * Reset-password form shared by `settings.users.tsx` and `employees.tsx`
 * -- same `POST /users/{id}/reset-password` call either page makes, one
 * dialog rather than two copies of the same validation.
 */
export function ResetVincoPasswordDialog({
  user,
  onOpenChange,
  busy,
  onSubmit,
}: {
  user: { id: string; display_name: string } | null;
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
