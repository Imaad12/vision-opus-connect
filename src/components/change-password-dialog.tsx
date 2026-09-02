import { useQueryClient } from "@tanstack/react-query";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { SetOwnPasswordForm } from "@/components/set-own-password-form";
import { useOwnAppUser } from "@/hooks/use-auth";
import { useI18n } from "@/lib/i18n";

/**
 * Part B5: self-service password change, available any time to a
 * logged-in user for their own account only -- unlike the forced
 * first-login gate (`forced-password-change-gate.tsx`), this isn't
 * triggered by `must_change_password`; it's just always reachable (see
 * the "Change Password" action in `app-shell.tsx`'s header).
 *
 * Renders nothing (not even an empty dialog shell) until the caller's
 * own native VINCO username is known -- `changeOwnPassword` needs it to
 * re-verify the current password, and a caller with no native VINCO
 * login at all (`useOwnAppUser()` resolving to `null`) has nothing here
 * to change.
 */
export function ChangePasswordDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const meQuery = useOwnAppUser();

  if (!meQuery.data) return null;
  const username = meQuery.data.username;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t("users.change_password.title")}</DialogTitle>
          <DialogDescription>{t("users.change_password.description")}</DialogDescription>
        </DialogHeader>
        <SetOwnPasswordForm
          username={username}
          submitLabel={t("users.change_password.submit")}
          submittingLabel={t("auth.set_password.submitting")}
          onSuccess={() => {
            void queryClient.invalidateQueries({ queryKey: ["users-me"] });
            onOpenChange(false);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
