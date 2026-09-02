/**
 * Covers the native VINCO username/password sign-in helper -- the
 * username-to-synthetic-email convention it and the backend must agree
 * on, and that a Supabase sign-in failure (wrong password, unknown
 * username, or a deactivated/banned account -- Supabase reports all
 * three the same way) surfaces as one generic, non-enumerating message.
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

  it("returns a generic message on failure, not Supabase's raw error text", async () => {
    signInWithPassword.mockResolvedValue({ error: { message: "Invalid login credentials" } });
    const result = await signInWithUsernamePassword("jdoe", "wrong-password");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.message).toBe("Incorrect username or password.");
  });

  it("rejects empty username/password without calling Supabase at all", async () => {
    const result = await signInWithUsernamePassword("", "");
    expect(result.ok).toBe(false);
    expect(signInWithPassword).not.toHaveBeenCalled();
  });
});
