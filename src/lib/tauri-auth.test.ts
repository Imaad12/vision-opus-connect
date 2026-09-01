/**
 * Covers the part of the desktop OAuth flow that's actually unit-testable
 * without a real Tauri runtime, browser, or Google/Supabase network call:
 * how a vinco://auth-callback URL gets parsed and routed once it reaches
 * this app (the root cause of the bug this file's implementation fixes --
 * see the module doc in tauri-auth.ts and DESKTOP_OAUTH_FIX.md). Opening
 * the system browser, the OS actually delivering the deep link, and the
 * real Google/Supabase exchange are exercised by the manual end-to-end
 * test documented there instead.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const exchangeCodeForSession = vi.fn();
const toastError = vi.fn();
const openUrl = vi.fn();
const onOpenUrl = vi.fn();
const getCurrent = vi.fn();

vi.mock("@/integrations/supabase/client", () => ({
  supabase: {
    auth: {
      exchangeCodeForSession,
      signInWithOAuth: vi.fn(),
    },
  },
}));
vi.mock("sonner", () => ({ toast: { error: toastError } }));
vi.mock("@tauri-apps/plugin-opener", () => ({ openUrl }));
vi.mock("@tauri-apps/plugin-deep-link", () => ({ onOpenUrl, getCurrent }));

const { handleAuthCallbackUrl, initTauriDeepLinkAuth, DESKTOP_OAUTH_REDIRECT_URL } =
  await import("./tauri-auth");

beforeEach(() => {
  exchangeCodeForSession.mockReset().mockResolvedValue({ data: {}, error: null });
  toastError.mockReset();
  openUrl.mockReset();
  onOpenUrl.mockReset().mockResolvedValue(() => {});
  getCurrent.mockReset().mockResolvedValue(null);
});

describe("handleAuthCallbackUrl", () => {
  it("ignores a URL that isn't the vinco:// auth callback", async () => {
    await handleAuthCallbackUrl("vinco://something-else?code=abc");
    expect(exchangeCodeForSession).not.toHaveBeenCalled();
    expect(toastError).not.toHaveBeenCalled();
  });

  it("exchanges the code from a successful PKCE callback", async () => {
    await handleAuthCallbackUrl(`${DESKTOP_OAUTH_REDIRECT_URL}?code=the-auth-code&sb_flow_id=xyz`);
    expect(exchangeCodeForSession).toHaveBeenCalledExactlyOnceWith("the-auth-code");
    expect(toastError).not.toHaveBeenCalled();
  });

  it("surfaces error_description without attempting an exchange", async () => {
    await handleAuthCallbackUrl(
      `${DESKTOP_OAUTH_REDIRECT_URL}?error=access_denied&error_description=User+denied+access`,
    );
    expect(exchangeCodeForSession).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalledExactlyOnceWith("User denied access");
  });

  it("falls back to the bare error code when error_description is absent", async () => {
    await handleAuthCallbackUrl(`${DESKTOP_OAUTH_REDIRECT_URL}?error=server_error`);
    expect(toastError).toHaveBeenCalledExactlyOnceWith("server_error");
  });

  it("does nothing for a callback with neither a code nor an error", async () => {
    await handleAuthCallbackUrl(`${DESKTOP_OAUTH_REDIRECT_URL}?state=abc`);
    expect(exchangeCodeForSession).not.toHaveBeenCalled();
    expect(toastError).not.toHaveBeenCalled();
  });

  it("surfaces a failed exchange (e.g. an expired or reused code)", async () => {
    exchangeCodeForSession.mockResolvedValue({
      data: {},
      error: { message: "invalid or expired flow state, no valid flow state found" },
    });
    await handleAuthCallbackUrl(`${DESKTOP_OAUTH_REDIRECT_URL}?code=stale`);
    expect(toastError).toHaveBeenCalledExactlyOnceWith(
      "invalid or expired flow state, no valid flow state found",
    );
  });

  it("does not throw on a malformed callback URL", async () => {
    await expect(
      handleAuthCallbackUrl("vinco://auth-callback??not a valid url:::"),
    ).resolves.not.toThrow();
  });
});

describe("initTauriDeepLinkAuth", () => {
  it("processes a cold-start launch URL from getCurrent() (app was closed)", async () => {
    getCurrent.mockResolvedValue([`${DESKTOP_OAUTH_REDIRECT_URL}?code=cold-start-code`]);
    await initTauriDeepLinkAuth();
    expect(exchangeCodeForSession).toHaveBeenCalledExactlyOnceWith("cold-start-code");
    expect(onOpenUrl).toHaveBeenCalledOnce();
  });
});
