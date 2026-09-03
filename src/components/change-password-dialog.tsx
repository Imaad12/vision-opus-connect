import { useQueryClient } from "@tanstack/react-query";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ClaimNativeIdentityForm } from "@/components/claim-native-identity-form";
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
 * Used to render nothing at all (not even an empty dialog shell) once
 * `useOwnAppUser()` resolved to `null` -- a real production bug: the
 * live Super Admin account was bootstrapped by `handle_new_user()`'s
 * "first Supabase user ever" trigger, which never creates an
 * `app_users` row, so `GET /users/me` 404s for it and clicking the key
 * icon did nothing visible at all. `null` here now means "no native
 * VINCO login yet" specifically, and renders `ClaimNativeIdentityForm`
 * -- the self-service migration path -- instead of a blank dialog.
 * `meQuery.isLoading` is checked separately so the loading state (not
 * yet resolved either way) doesn't briefly flash the claim form before
 * the real password-change form.
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

  if (meQuery.isLoading) return null;

  const invalidateAndClose = () => {
    void queryClient.invalidateQueries({ queryKey: ["users-me"] });
    onOpenChange(false);
  };

  if (!meQuery.data) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("users.claim.title")}</DialogTitle>
          </DialogHeader>
          <ClaimNativeIdentityForm onDone={invalidateAndClose} />
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t("users.change_password.title")}</DialogTitle>
          <DialogDescription>{t("users.change_password.description")}</DialogDescription>
        </DialogHeader>
        <SetOwnPasswordForm
          username={meQuery.data.username}
          submitLabel={t("users.change_password.submit")}
          submittingLabel={t("auth.set_password.submitting")}
          onSuccess={invalidateAndClose}
        />
      </DialogContent>
    </Dialog>
  );
}
