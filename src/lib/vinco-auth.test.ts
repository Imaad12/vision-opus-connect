/**
 * Covers the native VINCO username/password sign-in helper -- the
 * username-to-synthetic-email convention it and the backend must agree
 * on, and that different failure classes (wrong password, banned/
 * inactive account, network-level failure, empty fields) are classified
 * distinctly rather than collapsed into one opaque error.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const signInWithPassword = vi.fn();

vi.mock("@/integrations/supabase/client", () => ({
  supabase: { auth: { signInWithPassword } },
}));

const { signInWithUsernamePassword, usernameToEmail, USERNAME_EMAIL_DOMAIN } = await import(
  "./vinco-auth"
);

beforeEach(() => {
  signInWithPassword.mockReset();
});

describe("usernameToEmail", () => {
  it("appends the shared synthetic domain", () => {
    expect(usernameToEmail("jdoe")).toBe(`jdoe@${USERNAME_EMAIL_DOMAIN}`);
  });

  it("normalizes case and surrounding whitespace", () => {
    expect(usernameToEmail("  JDoe  ")).toBe(`jdoe@${USERNAME_EMAIL_DOMAIN}`);
  });
});

describe("signInWithUsernamePassword", () => {
  it("calls Supabase with the derived email, not the raw username", async () => {
    signInWithPassword.mockResolvedValue({ error: null });
    await signInWithUsernamePassword("jdoe", "correct-horse-battery");
    expect(signInWithPassword).toHaveBeenCalledWith({
      email: "jdoe@vinco.local",
      password: "correct-horse-battery",
    });
  });

  it("returns ok:true on success", async () => {
    signInWithPassword.mockResolvedValue({ error: null });
    const result = await signInWithUsernamePassword("jdoe", "correct-horse-battery");
    expect(result).toEqual({ ok: true });
  });

  it("classifies a plain wrong-password/unknown-username error as invalid_credentials", async () => {
    signInWithPassword.mockResolvedValue({
      error: { name: "AuthApiError", status: 400, message: "Invalid login credentials" },
    });
    const result = await signInWithUsernamePassword("jdoe", "wrong-password");
    expect(result).toEqual({ ok: false, kind: "invalid_credentials" });
  });

  it("classifies a user_banned code as inactive", async () => {
    signInWithPassword.mockResolvedValue({
      error: {
        name: "AuthApiError",
        status: 400,
        code: "user_banned",
        message: "User is banned",
      },
    });
    const result = await signInWithUsernamePassword("jdoe", "correct-horse-battery");
    expect(result).toEqual({ ok: false, kind: "inactive" });
  });

  it("classifies an AuthRetryableFetchError as network", async () => {
    signInWithPassword.mockResolvedValue({
      error: { name: "AuthRetryableFetchError", message: "fetch failed" },
    });
    const result = await signInWithUsernamePassword("jdoe", "correct-horse-battery");
    expect(result).toEqual({ ok: false, kind: "network" });
  });

  it("rejects empty username/password without calling Supabase at all", async () => {
    const result = await signInWithUsernamePassword("", "");
    expect(result).toEqual({ ok: false, kind: "empty" });
    expect(signInWithPassword).not.toHaveBeenCalled();
  });

  it("rejects a blank/whitespace-only username without calling Supabase", async () => {
    const result = await signInWithUsernamePassword("   ", "somepassword");
    expect(result).toEqual({ ok: false, kind: "empty" });
    expect(signInWithPassword).not.toHaveBeenCalled();
  });
});
