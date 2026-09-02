import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { TemporaryPasswordReveal } from "@/components/temporary-password-reveal";
import { useI18n } from "@/lib/i18n";

/**
 * Admin password-recovery dialog, shared by `settings.users.tsx` and
 * `employees.tsx` -- same `POST /users/{id}/reset-password` call either
 * page makes, one dialog rather than two copies.
 *
 * No password input at all (Part B4): the backend always generates a
 * fresh, cryptographically random temporary password -- there is no
 * reachable recovery email for a synthetic `@vinco.local` identity, so
 * this IS the recovery mechanism, not a fallback. Two phases: a confirm
 * step (nothing has happened yet), then -- once `result` is set by the
 * parent's mutation succeeding -- the same one-time reveal panel the
 * create flow uses.
 */
export function ResetVincoPasswordDialog({
  user,
  onOpenChange,
  busy,
  result,
  onGenerate,
  onDone,
}: {
  user: { id: string; username: string; display_name: string } | null;
  onOpenChange: (open: boolean) => void;
  busy: boolean;
  /** The newly generated temporary password, once the reset succeeded --
   * `null` while still on the confirm step. */
  result: string | null;
  onGenerate: () => void;
  onDone: () => void;
}) {
  const { t } = useI18n();

  return (
    <Dialog open={user !== null} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {result
              ? t("users.temp_password.reset_title")
              : `${t("users.reset_password.confirm_title")} — ${user?.display_name}`}
          </DialogTitle>
        </DialogHeader>
        {result && user ? (
          <TemporaryPasswordReveal
            username={user.username}
            temporaryPassword={result}
            onDone={onDone}
          />
        ) : (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              {t("users.reset_password.confirm_desc")}
            </p>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => onOpenChange(false)}
              >
                {t("common.cancel")}
              </Button>
              <Button type="button" disabled={busy} className="gap-2" onClick={onGenerate}>
                {busy ? <Loader2 className="size-4 animate-spin" /> : null}
                {t("users.reset_password.generate")}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
