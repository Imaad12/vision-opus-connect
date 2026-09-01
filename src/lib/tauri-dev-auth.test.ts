/**
 * Covers src/lib/tauri-dev-auth.ts's auto-login logic in isolation (no
 * real Supabase project, no real desktop runtime) -- see that file's doc
 * comment and DESKTOP_AUTH_MVP.md for what this exists to do and why.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getSession = vi.fn();
const signInWithPassword = vi.fn();

vi.mock("@/integrations/supabase/client", () => ({
  supabase: {
    auth: {
      getSession,
      signInWithPassword,
    },
  },
}));

const { signInDesktopDevAccount } = await import("./tauri-dev-auth");

beforeEach(() => {
  getSession.mockReset().mockResolvedValue({ data: { session: null } });
  signInWithPassword.mockReset().mockResolvedValue({ data: {}, error: null });
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("signInDesktopDevAccount", () => {
  it("does nothing if a session already exists (e.g. restored from the keychain)", async () => {
    getSession.mockResolvedValue({ data: { session: { access_token: "existing" } } });
    await signInDesktopDevAccount();
    expect(signInWithPassword).not.toHaveBeenCalled();
  });

  it("throws a clear error when the dev credentials env vars are unset", async () => {
    vi.stubEnv("VITE_DESKTOP_DEV_EMAIL", "");
    vi.stubEnv("VITE_DESKTOP_DEV_PASSWORD", "");
    await expect(signInDesktopDevAccount()).rejects.toThrow(/VITE_DESKTOP_DEV_EMAIL/);
    expect(signInWithPassword).not.toHaveBeenCalled();
  });

  it("signs in with the configured credentials when no session exists", async () => {
    vi.stubEnv("VITE_DESKTOP_DEV_EMAIL", "desktop-dev@vinco.internal");
    vi.stubEnv("VITE_DESKTOP_DEV_PASSWORD", "correct-horse-battery-staple");
    await signInDesktopDevAccount();
    expect(signInWithPassword).toHaveBeenCalledExactlyOnceWith({
      email: "desktop-dev@vinco.internal",
      password: "correct-horse-battery-staple",
    });
  });

  it("propagates a failed sign-in (e.g. wrong/disabled dev account)", async () => {
    vi.stubEnv("VITE_DESKTOP_DEV_EMAIL", "desktop-dev@vinco.internal");
    vi.stubEnv("VITE_DESKTOP_DEV_PASSWORD", "wrong-password");
    signInWithPassword.mockResolvedValue({
      data: {},
      error: { name: "AuthApiError", message: "Invalid login credentials", status: 400 },
    });
    await expect(signInDesktopDevAccount()).rejects.toMatchObject({
      message: "Invalid login credentials",
    });
  });
});
