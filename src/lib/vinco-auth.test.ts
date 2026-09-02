/**
 * Covers the native VINCO username/password sign-in helper -- the
 * username-to-synthetic-email convention it and the backend must agree
 * on, and that different failure classes (wrong password, banned/
 * inactive account, network-level failure, empty fields) are classified
 * distinctly rather than collapsed into one opaque error.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const signInWithPassword = vi.fn();
const updateUser = vi.fn();
const apiPost = vi.fn();

vi.mock("@/integrations/supabase/client", () => ({
  supabase: { auth: { signInWithPassword, updateUser } },
}));
vi.mock("@/lib/api", () => ({
  api: { post: apiPost },
}));

const { signInWithUsernamePassword, usernameToEmail, USERNAME_EMAIL_DOMAIN, changeOwnPassword } =
  await import("./vinco-auth");

beforeEach(() => {
  signInWithPassword.mockReset();
  updateUser.mockReset();
  apiPost.mockReset().mockResolvedValue(undefined);
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

  it("records the login on success", async () => {
    signInWithPassword.mockResolvedValue({ error: null });
    await signInWithUsernamePassword("jdoe", "correct-horse-battery");
    expect(apiPost).toHaveBeenCalledWith("/users/me/record-login", {});
  });

  it("does not record a login on failure", async () => {
    signInWithPassword.mockResolvedValue({
      error: { name: "AuthApiError", status: 400, message: "Invalid login credentials" },
    });
    await signInWithUsernamePassword("jdoe", "wrong-password");
    expect(apiPost).not.toHaveBeenCalled();
  });

  it("a failed login-record call does not make sign-in itself fail", async () => {
    signInWithPassword.mockResolvedValue({ error: null });
    apiPost.mockRejectedValue(new Error("backend unreachable"));
    const result = await signInWithUsernamePassword("jdoe", "correct-horse-battery");
    expect(result).toEqual({ ok: true });
  });
});

describe("changeOwnPassword", () => {
  it("rejects a mismatched confirmation without calling Supabase at all", async () => {
    const result = await changeOwnPassword("jdoe", "current-pw", "new-password-1", "different");
    expect(result).toEqual({ ok: false, kind: "mismatch" });
    expect(signInWithPassword).not.toHaveBeenCalled();
  });

  it("rejects a too-short new password without calling Supabase at all", async () => {
    const result = await changeOwnPassword("jdoe", "current-pw", "short", "short");
    expect(result).toEqual({ ok: false, kind: "too_short" });
    expect(signInWithPassword).not.toHaveBeenCalled();
  });

  it("re-verifies the current password against the derived synthetic email", async () => {
    signInWithPassword.mockResolvedValue({ error: null });
    updateUser.mockResolvedValue({ error: null });
    await changeOwnPassword("jdoe", "current-pw", "new-password-1", "new-password-1");
    expect(signInWithPassword).toHaveBeenCalledWith({
      email: "jdoe@vinco.local",
      password: "current-pw",
    });
  });

  it("fails with wrong_current when the current password is incorrect, and never calls updateUser", async () => {
    signInWithPassword.mockResolvedValue({
      error: { name: "AuthApiError", status: 400, message: "Invalid login credentials" },
    });
    const result = await changeOwnPassword(
      "jdoe",
      "wrong-current",
      "new-password-1",
      "new-password-1",
    );
    expect(result).toEqual({ ok: false, kind: "wrong_current" });
    expect(updateUser).not.toHaveBeenCalled();
  });

  it("classifies a network failure while re-verifying distinctly from a wrong password", async () => {
    signInWithPassword.mockResolvedValue({
      error: { name: "AuthRetryableFetchError", message: "fetch failed" },
    });
    const result = await changeOwnPassword(
      "jdoe",
      "current-pw",
      "new-password-1",
      "new-password-1",
    );
    expect(result).toEqual({ ok: false, kind: "network" });
  });

  it("changes the password via Supabase's own updateUser once re-verified", async () => {
    signInWithPassword.mockResolvedValue({ error: null });
    updateUser.mockResolvedValue({ error: null });
    await changeOwnPassword("jdoe", "current-pw", "new-password-1", "new-password-1");
    expect(updateUser).toHaveBeenCalledWith({ password: "new-password-1" });
  });

  it("reports failure if Supabase's updateUser itself fails", async () => {
    signInWithPassword.mockResolvedValue({ error: null });
    updateUser.mockResolvedValue({ error: { name: "AuthApiError", message: "weak password" } });
    const result = await changeOwnPassword(
      "jdoe",
      "current-pw",
      "new-password-1",
      "new-password-1",
    );
    expect(result).toEqual({ ok: false, kind: "unknown" });
  });

  it("tells the backend to clear must_change_password on success", async () => {
    signInWithPassword.mockResolvedValue({ error: null });
    updateUser.mockResolvedValue({ error: null });
    await changeOwnPassword("jdoe", "current-pw", "new-password-1", "new-password-1");
    expect(apiPost).toHaveBeenCalledWith("/users/me/password-changed", {});
  });

  it("still reports success if only the backend bookkeeping call fails", async () => {
    signInWithPassword.mockResolvedValue({ error: null });
    updateUser.mockResolvedValue({ error: null });
    apiPost.mockRejectedValue(new Error("backend unreachable"));
    const result = await changeOwnPassword(
      "jdoe",
      "current-pw",
      "new-password-1",
      "new-password-1",
    );
    expect(result).toEqual({ ok: true });
  });

  it("never calls the backend bookkeeping endpoint when the password change itself failed", async () => {
    signInWithPassword.mockResolvedValue({
      error: { name: "AuthApiError", status: 400, message: "Invalid login credentials" },
    });
    await changeOwnPassword("jdoe", "wrong-current", "new-password-1", "new-password-1");
    expect(apiPost).not.toHaveBeenCalled();
  });
});
