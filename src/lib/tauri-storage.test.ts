/**
 * Covers the desktop Supabase session storage adapter's mapping onto the
 * Rust session-store commands (src-tauri/src/session_store.rs) -- the
 * seam that changed when this switched away from OS-keychain storage
 * (see this file's module doc for why: an unsigned/ad-hoc-signed build's
 * Keychain "always allow" grant didn't survive a rebuild, reprompting
 * every time). Confirms the adapter calls the new command names, not the
 * old keychain_* ones, and maps their results the way SupportedStorage
 * expects.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const invoke = vi.fn();

vi.mock("@tauri-apps/api/core", () => ({ invoke }));

const { tauriDesktopStorage } = await import("./tauri-storage");

beforeEach(() => {
  invoke.mockReset();
});

describe("tauriDesktopStorage", () => {
  it("getItem calls session_store_get and returns its value", async () => {
    invoke.mockResolvedValue("stored-value");
    const result = await tauriDesktopStorage.getItem("access_token");
    expect(invoke).toHaveBeenCalledWith("session_store_get", { key: "access_token" });
    expect(result).toBe("stored-value");
  });

  it("getItem maps a missing key (null) to null, not undefined or a throw", async () => {
    invoke.mockResolvedValue(null);
    const result = await tauriDesktopStorage.getItem("missing_key");
    expect(result).toBeNull();
  });

  it("setItem calls session_store_set with the key and value", async () => {
    invoke.mockResolvedValue(undefined);
    await tauriDesktopStorage.setItem("refresh_token", "abc123");
    expect(invoke).toHaveBeenCalledWith("session_store_set", {
      key: "refresh_token",
      value: "abc123",
    });
  });

  it("removeItem calls session_store_delete with the key", async () => {
    invoke.mockResolvedValue(undefined);
    await tauriDesktopStorage.removeItem("access_token");
    expect(invoke).toHaveBeenCalledWith("session_store_delete", { key: "access_token" });
  });

  it("never invokes any of the old keychain_* commands", async () => {
    invoke.mockResolvedValue(null);
    await tauriDesktopStorage.getItem("k");
    await tauriDesktopStorage.setItem("k", "v");
    await tauriDesktopStorage.removeItem("k");
    const calledCommands = invoke.mock.calls.map((call) => call[0]);
    expect(calledCommands).not.toContain("keychain_get");
    expect(calledCommands).not.toContain("keychain_set");
    expect(calledCommands).not.toContain("keychain_delete");
  });
});
