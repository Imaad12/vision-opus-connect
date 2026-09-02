import { useNavigate } from "@tanstack/react-router";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { supabase } from "@/integrations/supabase/client";
import { SESSION_EXPIRED_FLAG_KEY } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { signInWithUsernamePassword, type SignInFailureKind } from "@/lib/vinco-auth";

/**
 * One VINCO login screen, identical on web and desktop -- username,
 * password, Sign In. No Google, no OAuth, no browser redirect, no
 * Supabase-branded UI, nothing platform-specific shown to the employee.
 *
 * Desktop previously auto-signed-in as a dedicated internal account
 * (see DESKTOP_AUTH_MVP.md and src/lib/tauri-dev-auth.ts) while native
 * VINCO login was being built; now that it exists, desktop uses the
 * exact same form as web. `tauri-dev-auth.ts` itself is intentionally
 * left in place (its own tests still pass) as a manual dev utility --
 * nothing here calls it anymore, on any build, so it cannot run
 * automatically in a production desktop build.
 */
export function SignInScreen() {
  const { t, lang, toggle } = useI18n();
  const navigate = useNavigate();
  const [signedIn, setSignedIn] = useState(false);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errorKind, setErrorKind] = useState<SignInFailureKind | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  // Guards against a double-submit firing two concurrent sign-in
  // attempts (e.g. a fast double Enter) racing each other -- `busy`
  // disabling the button/inputs already covers the common case, but
  // this ref is checked synchronously before any state update lands,
  // closing the gap between two submit events queued in the same tick.
  const submittingRef = useRef(false);

  useEffect(() => {
    try {
      if (sessionStorage.getItem(SESSION_EXPIRED_FLAG_KEY)) {
        setSessionExpired(true);
        sessionStorage.removeItem(SESSION_EXPIRED_FLAG_KEY);
      }
    } catch {
      // sessionStorage unavailable (locked-down/private context) --
      // simply skip showing the specific message, never block the
      // login screen over this.
    }
  }, []);

  useEffect(() => {
    void supabase.auth.getSession().then(({ data }) => {
      if (data.session) setSignedIn(true);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) => {
      if (session) setSignedIn(true);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  // Covers both platforms: on web, Supabase's own already-persisted
  // session flips `signedIn` almost immediately; on desktop, the same
  // thing happens once session_store.rs has restored a prior session
  // (see src/lib/tauri-storage.ts) -- either way, a valid existing
  // session skips the form and goes straight to the dashboard.
  useEffect(() => {
    if (signedIn) void navigate({ to: "/dashboard" });
  }, [signedIn, navigate]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (submittingRef.current) return;
    submittingRef.current = true;
    setErrorKind(null);
    setSessionExpired(false);
    setBusy(true);
    const result = await signInWithUsernamePassword(username, password);
    setBusy(false);
    submittingRef.current = false;
    if (!result.ok) {
      setErrorKind(result.kind);
      return;
    }
    // supabase.auth.onAuthStateChange above flips `signedIn`, which the
    // navigate effect then acts on -- no direct navigate() call needed
    // here.
  };

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
            <li>
              · {t("nav.quotations")} — {t("nav.approvals")}
            </li>
            <li>
              · {t("nav.projects")} — {t("nav.contracts")}
            </li>
            <li>
              · {t("nav.purchase_orders")} — {t("nav.suppliers")}
            </li>
            <li>
              · {t("nav.invoices")} — {t("nav.vat")}
            </li>
          </ul>
        </div>
        <p className="text-xs text-primary-foreground/50">Riyadh · Kingdom of Saudi Arabia</p>
      </section>

      <section className="flex flex-col items-center justify-center gap-6 px-6 py-16">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center justify-between">
            <div className="flex items-center gap-2 lg:hidden">
              <div className="grid size-8 place-items-center rounded-md bg-primary text-xs font-bold text-primary-foreground">
                VC
              </div>
              <span className="text-sm font-semibold">{t("app.short")}</span>
            </div>
            <Button variant="ghost" size="sm" onClick={toggle} className="ms-auto">
              {t("common.language")}
            </Button>
          </div>

          <h1 className="text-2xl font-semibold">{t("app.name")}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{t("auth.company_only")}</p>

          {signedIn ? (
            <Button className="mt-8 w-full gap-2" onClick={() => navigate({ to: "/dashboard" })}>
              {t("nav.dashboard")}
            </Button>
          ) : (
            <form className="mt-8 space-y-4" onSubmit={handleSubmit}>
              <div className="space-y-1.5">
                <Label htmlFor="vinco-username">{t("auth.username")}</Label>
                <Input
                  id="vinco-username"
                  autoComplete="username"
                  autoFocus
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={busy}
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="vinco-password">{t("auth.password")}</Label>
                <div className="relative">
                  <Input
                    id="vinco-password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    disabled={busy}
                    required
                    className="pe-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute inset-y-0 end-0 flex items-center px-3 text-muted-foreground hover:text-foreground"
                    aria-label={showPassword ? t("auth.hide_password") : t("auth.show_password")}
                    tabIndex={-1}
                  >
                    {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                  </button>
                </div>
              </div>
              {sessionExpired ? (
                <p className="text-sm text-destructive">{t("auth.session_expired")}</p>
              ) : null}
              {errorKind ? (
                <p className="text-sm text-destructive">{t(`auth.error.${errorKind}`)}</p>
              ) : null}
              <Button type="submit" className="w-full gap-2" disabled={busy}>
                {busy ? <Loader2 className="size-4 animate-spin" /> : null}
                {busy ? t("auth.signing_in") : t("auth.signin")}
              </Button>
            </form>
          )}

          <p className="mt-6 text-xs text-muted-foreground" dir={lang === "ar" ? "rtl" : "ltr"}>
            {t("app.tagline")}
          </p>
        </div>
      </section>
    </div>
  );
}
