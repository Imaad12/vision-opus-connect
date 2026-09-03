// @vitest-environment jsdom
/**
 * DOM-level coverage for the Client PO document/provenance cell (P8):
 * this is the same "genuine native `<input type=file>`, never a fake
 * trigger" bar P1 set for the historical-import picker, applied to the
 * per-row "attach PO document" affordance on the /client-po page. What's
 * provable here (and not by type-checking alone, per this project's own
 * standard): the upload control only renders when the caller says the
 * viewer may upload, an existing document always wins over showing the
 * control, and selecting a file actually calls the upload endpoint with
 * the right multipart field name and the right client-award-evidence id.
 *
 * Renders `ClientPoDocumentCell` in isolation (not the whole page) --
 * it needs `QueryClientProvider` (useMutation) and `I18nProvider`
 * (useI18n), but nothing from Supabase/router, so those are the only
 * two wrapped around it. `@/lib/api` is mocked so no real network call
 * is ever attempted.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n";

const uploadFiles = vi.fn();

vi.mock("@/lib/api", () => ({
  api: { uploadFiles: (...args: unknown[]) => uploadFiles(...args) },
  ApiError: class ApiError extends Error {
    describe() {
      return this.message;
    }
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { ClientPoDocumentCell, type ClientAwardEvidence } from "./client-po";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function makeEvidence(overrides: Partial<ClientAwardEvidence> = {}): ClientAwardEvidence {
  return {
    id: 7,
    quotation_id: 1,
    po_reference_number: "PO-1",
    po_date: null,
    net_value: null,
    tax_value: null,
    gross_value: null,
    currency: "SAR",
    notes: null,
    awarded_quotation_version_id: null,
    awarded_quotation_version: null,
    project: { id: 1, name: "Project", project_code: null, client: { id: 1, name: "Client" } },
    quotation_reference_number: "Q-1",
    quoted_value: null,
    variance: null,
    source: "manual",
    document: null,
    contracted: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makePdf(name: string): File {
  return new File(["%PDF-1.4 test content"], name, { type: "application/pdf" });
}

function selectFiles(input: HTMLInputElement, files: File[]): void {
  Object.defineProperty(input, "files", { value: files, configurable: true });
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("ClientPoDocumentCell", () => {
  let container: HTMLDivElement;
  let root: Root;
  let queryClient: QueryClient;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    queryClient = new QueryClient();
    uploadFiles.mockReset();
    uploadFiles.mockResolvedValue(makeEvidence({ document: { id: 1, filename: "x.pdf" } }));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    queryClient.clear();
  });

  function renderCell(props: {
    evidence: ClientAwardEvidence;
    canUpload: boolean;
    onUploaded?: () => void;
  }) {
    act(() => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <I18nProvider>
            <ClientPoDocumentCell
              evidence={props.evidence}
              canUpload={props.canUpload}
              onUploaded={props.onUploaded ?? (() => {})}
            />
          </I18nProvider>
        </QueryClientProvider>,
      );
    });
  }

  it("shows the existing document's filename and renders no upload control when a document is already attached", () => {
    renderCell({
      evidence: makeEvidence({ document: { id: 3, filename: "signed-po.pdf" } }),
      canUpload: true,
    });

    expect(container.textContent).toContain("signed-po.pdf");
    expect(container.querySelector('input[type="file"]')).toBeNull();
  });

  it("renders no upload control (and no document) when the viewer lacks permission", () => {
    renderCell({ evidence: makeEvidence({ document: null }), canUpload: false });

    expect(container.querySelector('input[type="file"]')).toBeNull();
  });

  it("renders a real, enabled, PDF-only native file input when the viewer can upload and none exists yet", () => {
    renderCell({ evidence: makeEvidence({ document: null }), canUpload: true });

    const input = container.querySelector('input[type="file"]') as HTMLInputElement | null;
    expect(input).toBeInstanceOf(HTMLInputElement);
    expect(input?.disabled).toBe(false);
    expect(input?.accept).toBe("application/pdf");
  });

  it("selecting a file uploads it to the right client-award-evidence id under field name 'file'", async () => {
    const onUploaded = vi.fn();
    renderCell({ evidence: makeEvidence({ id: 42, document: null }), canUpload: true, onUploaded });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;

    const file = makePdf("client-po.pdf");
    await act(async () => {
      selectFiles(input, [file]);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(uploadFiles).toHaveBeenCalledTimes(1);
    expect(uploadFiles).toHaveBeenCalledWith("/client-award-evidence/42/document", "file", [file]);
    expect(onUploaded).toHaveBeenCalledTimes(1);
  });
});
