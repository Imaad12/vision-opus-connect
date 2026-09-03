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

const { api, ApiError, assertApiUrlConfiguredInProduction } = await import("./api");

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

  // Regression for the VINCO desktop Customers page: a blocked CORS
  // preflight and a genuine network outage both surface from fetch() as
  // an opaque TypeError with no HTTP status at all (WKWebView's own
  // message is literally "Load failed") -- this must be tagged distinctly
  // from an HTTP error response and from a timeout, and describe() must
  // name the endpoint instead of only repeating the same opaque text.
  it("tags a raw fetch rejection (no Response) as a network-kind error, not an HTTP one", async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError("Load failed")) as typeof fetch;
    await expect(api.get("/clients")).rejects.toMatchObject({
      status: 0,
      kind: "network",
      method: "GET",
      path: "/clients",
    });
  });

  it("describe() names the endpoint and status for an HTTP error", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Missing permission: customers.view" }), {
        status: 403,
      }),
    ) as typeof fetch;
    try {
      await api.get("/clients");
      throw new Error("expected api.get to reject");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as InstanceType<typeof ApiError>).describe()).toBe(
        "GET /clients — HTTP 403 (insufficient permissions): Missing permission: customers.view",
      );
    }
  });

  it("describe() distinguishes a network failure from an HTTP error for the same endpoint", async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError("Load failed")) as typeof fetch;
    try {
      await api.get("/clients");
      throw new Error("expected api.get to reject");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as InstanceType<typeof ApiError>).describe()).toContain(
        "no response from the server",
      );
      expect((e as InstanceType<typeof ApiError>).describe()).toContain("GET /clients");
    }
  });

  it("patch sends a PATCH request with a JSON body", async () => {
    let capturedInit: RequestInit | undefined;
    global.fetch = vi.fn().mockImplementation((_url, init: RequestInit) => {
      capturedInit = init;
      return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    }) as typeof fetch;

    await api.patch("/imports/documents/1/candidate", { client_name: "ABC Holdings" });

    expect(capturedInit?.method).toBe("PATCH");
    expect(capturedInit?.body).toBe(JSON.stringify({ client_name: "ABC Holdings" }));
  });

  it("getBlob resolves a binary response as a Blob, not parsed JSON", async () => {
    const pngBytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);
    const response = new Response(pngBytes, {
      status: 200,
      headers: { "Content-Type": "image/png" },
    });
    global.fetch = vi.fn().mockResolvedValue(response) as typeof fetch;

    const blob = await api.getBlob("/imports/documents/1/pages/1");
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.size).toBe(4);
  });

  it("getBlob still throws ApiError on a non-ok response, same as request()", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: "Page 99 is out of range." }), { status: 422 }),
      ) as typeof fetch;

    await expect(api.getBlob("/imports/documents/1/pages/99")).rejects.toMatchObject({
      status: 422,
      message: "Page 99 is out of range.",
    });
  });

  it("uploadFiles sends a multipart FormData body without a JSON Content-Type header", async () => {
    let capturedInit: RequestInit | undefined;
    global.fetch = vi.fn().mockImplementation((_url, init: RequestInit) => {
      capturedInit = init;
      return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 201 }));
    }) as typeof fetch;

    const file = new File(["hello"], "quote.txt", { type: "text/plain" });
    await api.uploadFiles("/imports/batches/1/documents", "files", [file]);

    expect(capturedInit?.body).toBeInstanceOf(FormData);
    const body = capturedInit?.body as FormData;
    expect(body.get("files")).toBe(file);
    // Explicitly NOT set -- letting the browser generate its own
    // multipart boundary is the whole point (see api.ts's `isFormData`
    // check); a hardcoded "application/json" here would make the
    // backend fail to parse the multipart body at all.
    const headers = new Headers(capturedInit?.headers);
    expect(headers.get("Content-Type")).not.toBe("application/json");
  });
});

// Regression for a web deployment silently pointing every visitor's
// browser at localhost: API_BASE_URL's own fallback is fine for local
// dev, but must never survive unnoticed into a real production build
// with VITE_API_URL simply never configured (e.g. a Cloudflare Pages
// project whose env vars were never set).
describe("assertApiUrlConfiguredInProduction", () => {
  it("throws when no URL is configured and this is a production build", () => {
    expect(() => assertApiUrlConfiguredInProduction(false, true)).toThrow(
      /VITE_API_URL is not set/,
    );
  });

  it("does not throw when a URL is configured, even in production", () => {
    expect(() => assertApiUrlConfiguredInProduction(true, true)).not.toThrow();
  });

  it("does not throw when no URL is configured outside production (local dev)", () => {
    expect(() => assertApiUrlConfiguredInProduction(false, false)).not.toThrow();
  });
});
