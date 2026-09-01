/**
 * Covers src/lib/api.ts's error-handling paths that don't need a real
 * backend: non-ok responses, a timed-out request (simulated -- not an
 * actual 30s wait), and 401 triggering the app's existing sign-out ->
 * re-auth flow. See that file's comments for why each of these matters
 * for an internal ERP (infinite loading on a hung backend, duplicate
 * writes on a timed-out mutation, users stranded on an expired session).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getSession = vi.fn();
const signOut = vi.fn();

vi.mock("@/integrations/supabase/client", () => ({
  supabase: {
    auth: {
      getSession,
      signOut,
    },
  },
}));

const { api, ApiError } = await import("./api");

const originalFetch = global.fetch;

beforeEach(() => {
  getSession.mockReset().mockResolvedValue({ data: { session: null } });
  signOut.mockReset().mockResolvedValue({ error: null });
});

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("api client error handling", () => {
  it("returns parsed JSON on a successful response", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ ok: true }), { status: 200 }),
      ) as typeof fetch;
    await expect(api.get("/whatever")).resolves.toEqual({ ok: true });
  });

  it("throws ApiError with the backend's detail message on a non-ok response", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Missing permission: customers.view" }), {
        status: 403,
      }),
    ) as typeof fetch;
    await expect(api.get("/customers")).rejects.toMatchObject({
      status: 403,
      message: "Missing permission: customers.view",
    });
  });

  it("falls back to statusText when the error body isn't JSON", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(
        new Response("<html>gateway error</html>", { status: 502 }),
      ) as typeof fetch;
    await expect(api.get("/whatever")).rejects.toBeInstanceOf(ApiError);
  });

  it("signs out on a 401 so the app's existing re-auth flow takes over", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: "Missing bearer token." }), { status: 401 }),
      ) as typeof fetch;
    await expect(api.get("/customers")).rejects.toMatchObject({ status: 401 });
    expect(signOut).toHaveBeenCalledOnce();
  });

  it("does not sign out twice for two concurrent 401s", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: "Missing bearer token." }), { status: 401 }),
      ) as typeof fetch;
    await Promise.allSettled([api.get("/a"), api.get("/b")]);
    expect(signOut).toHaveBeenCalledOnce();
  });

  it("reports a GET timeout as safely retryable", async () => {
    global.fetch = vi
      .fn()
      .mockRejectedValue(
        new DOMException("The operation was aborted due to timeout", "TimeoutError"),
      ) as typeof fetch;
    await expect(api.get("/customers")).rejects.toMatchObject({
      message: expect.stringContaining("try again"),
    });
  });

  it("does not tell the caller a timed-out write is safe to retry", async () => {
    global.fetch = vi
      .fn()
      .mockRejectedValue(
        new DOMException("The operation was aborted due to timeout", "TimeoutError"),
      ) as typeof fetch;
    await expect(api.post("/invoices", {})).rejects.toMatchObject({
      message: expect.stringContaining("may or may not have been saved"),
    });
  });
});
