import { isTauri } from "@tauri-apps/api/core";
import { useNavigate } from "@tanstack/react-router";
import { ArrowRight, Building2, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { supabase } from "@/integrations/supabase/client";
import { useI18n } from "@/lib/i18n";
import { signInDesktopDevAccount } from "@/lib/tauri-dev-auth";

/**
 * Desktop MVP only -- see DESKTOP_AUTH_MVP.md. No form, no button, no
 * OAuth: the desktop build signs itself in automatically, this just shows
 * that it's in progress (or, on failure, a plain retry -- e.g. the
 * backend/Supabase is unreachable, or .env's dev credentials are wrong).
 */
function DesktopAutoSignInScreen({
  busy,
  error,
  onRetry,
}: {
  busy: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="grid size-10 place-items-center rounded-md bg-accent text-sm font-bold text-accent-foreground">
        VC
      </div>
      {error ? (
        <>
          <p className="max-w-sm text-sm text-muted-foreground">{error}</p>
          <Button onClick={onRetry}>Retry</Button>
        </>
      ) : (
        <>
          {busy ? <Loader2 className="size-5 animate-spin text-muted-foreground" /> : null}
          <p className="text-sm text-muted-foreground">Loading VINCO ERP…</p>
        </>
      )}
    </div>
  );
}

export function SignInScreen() {
  const { t, lang, toggle } = useI18n();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  // Desktop MVP only (see DESKTOP_AUTH_MVP.md): Google OAuth is parked, so
  // there is no login form to show here at all -- just an automatic sign-in
  // as the desktop build's dedicated internal account, with a plain loading
  // state while that's in flight, and a retry affordance if it fails (e.g.
  // the backend/Supabase is unreachable). No button, no browser, no OAuth.
  const [desktopAuthError, setDesktopAuthError] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    void supabase.auth.getSession().then(({ data }) => {
      if (data.session) setSignedIn(true);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) => {
      if (session) setSignedIn(true);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  // On the web build this screen is rarely reached already-signed-in
  // (Supabase's own redirect already lands the user on /dashboard
  // directly). On desktop, the auto-sign-in effect below establishes the
  // session while this route is still showing, so `signedIn` flipping
  // true is the actual signal to leave.
  useEffect(() => {
    if (signedIn) void navigate({ to: "/dashboard" });
  }, [signedIn, navigate]);

  useEffect(() => {
    if (!isTauri() || signedIn) return;
    let cancelled = false;
    setBusy(true);
    setDesktopAuthError(null);
    signInDesktopDevAccount()
      .catch((error: unknown) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "Sign-in failed";
        setDesktopAuthError(message);
        toast.error(message);
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
    // Re-runs after a failed attempt's Retry button bumps retryToken.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [retryToken]);

  const signIn = async () => {
    setBusy(true);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: window.location.origin + "/dashboard" },
    });
    if (error) {
      setBusy(false);
      toast.error(error.message ?? "Sign-in failed");
      return;
    }
    // On success, Supabase redirects the browser to Google immediately --
    // there is no further local state to update here before the page
    // navigates away.
  };

  if (isTauri()) {
    return <DesktopAutoSignInScreen busy={busy} error={desktopAuthError} onRetry={() => setRetryToken((n) => n + 1)} />;
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <section className="hero-mesh relative hidden flex-col justify-between p-10 lg:flex">
        <div className="flex items-center gap-3 text-primary-foreground">
          <div className="grid size-10 place-items-center rounded-md bg-accent text-sm font-bold text-accent-foreground">
            VC
          </div>
          <span className="text-sm font-semibold tracking-wide">{t("app.short")}</span>
        </div>
        <div className="max-w-md text-primary-foreground">
          <h2 className="text-3xl leading-tight font-semibold">{t("app.name")}</h2>
          <p className="mt-3 text-sm text-primary-foreground/75">{t("app.tagline")}</p>
          <ul className="mt-8 space-y-2 text-sm text-primary-foreground/70">
            <li>· {t("nav.quotations")} — {t("nav.approvals")}</li>
            <li>· {t("nav.projects")} — {t("nav.contracts")}</li>
            <li>· {t("nav.purchase_orders")} — {t("nav.suppliers")}</li>
            <li>· {t("nav.invoices")} — {t("nav.vat")}</li>
          </ul>
        </div>
        <p className="text-xs text-primary-foreground/50">Riyadh · Kingdom of Saudi Arabia</p>
      </section>

      <section className="flex flex-col items-center justify-center gap-6 px-6 py-16">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center justify-between">
            <div className="flex items-center gap-2 lg:hidden">
              <Building2 className="size-5 text-primary" />
              <span className="text-sm font-semibold">{t("app.short")}</span>
            </div>
            <Button variant="ghost" size="sm" onClick={toggle} className="ms-auto">
              {t("common.language")}
            </Button>
          </div>

          <h1 className="text-2xl font-semibold">{t("auth.open_workspace")}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{t("auth.company_only")}</p>

          {signedIn ? (
            <Button className="mt-8 w-full gap-2" onClick={() => navigate({ to: "/dashboard" })}>
              {t("nav.dashboard")} <ArrowRight className="size-4" />
            </Button>
          ) : (
            <Button className="mt-8 w-full gap-2" onClick={signIn} disabled={busy}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : null}
              {busy ? t("auth.signing_in") : t("auth.signin")}
            </Button>
          )}

          <p className="mt-6 text-xs text-muted-foreground" dir={lang === "ar" ? "rtl" : "ltr"}>
            {t("app.tagline")}
          </p>
        </div>
      </section>
    </div>
  );
}
