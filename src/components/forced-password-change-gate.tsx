import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { SetOwnPasswordForm } from "@/components/set-own-password-form";
import { useOwnAppUser } from "@/hooks/use-auth";
import { useI18n } from "@/lib/i18n";

/**
 * Part B3: blocks the rest of the authenticated app -- web and desktop
 * alike, since both mount the same `_authenticated` route tree -- while
 * the signed-in account's `must_change_password` is true (an admin just
 * created it, or reset its password; see backend/app/services/
 * user_service.py). Wraps the whole authenticated layout (see
 * src/routes/_authenticated/route.tsx) rather than gating each page
 * individually, so there's exactly one place this is enforced, not one
 * per route.
 *
 * `GET /users/me` 404s for a caller with no native VINCO login (e.g. a
 * legacy/Google-linked account) -- treated exactly like
 * `must_change_password: false`, since the gate has nothing to enforce
 * for an account that was never given an admin-generated temporary
 * password in the first place. Any other fetch failure (backend
 * unreachable, unexpected 5xx) fails OPEN rather than locking a
 * legitimate, already-authenticated user out of the entire app over a
 * transient backend problem -- this screen is the UX enforcement of an
 * onboarding step, not the account's actual security boundary (that
 * remains Supabase's own password verification).
 */
export function ForcedPasswordChangeGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { t } = useI18n();

  const meQuery = useOwnAppUser();

  if (meQuery.isLoading) {
    return (
      <div className="grid min-h-screen place-items-center text-sm text-muted-foreground">
        {t("common.loading")}
      </div>
    );
  }

  if (meQuery.data?.must_change_password) {
    return (
      <div className="grid min-h-screen place-items-center px-6 py-16">
        <div className="w-full max-w-sm">
          <h1 className="text-2xl font-semibold">{t("auth.set_password.title")}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{t("auth.set_password.description")}</p>
          <div className="mt-8">
            <SetOwnPasswordForm
              username={meQuery.data.username}
              submitLabel={t("auth.set_password.submit")}
              submittingLabel={t("auth.set_password.submitting")}
              onSuccess={() => void queryClient.invalidateQueries({ queryKey: ["users-me"] })}
            />
          </div>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
