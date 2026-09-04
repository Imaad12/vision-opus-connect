/**
 * Unit coverage for the pure queue/status-derivation helpers backing the
 * historical-import queue UI (P7/P8 of the ingestion-reliability pass):
 * which extraction outcomes are retryable, what label a row's Status
 * column shows, and file-size formatting. No DOM/react-query needed --
 * these are plain functions, tested directly.
 */
import { describe, expect, it } from "vitest";

import {
  documentStatusLabel,
  formatFileSize,
  isRetryable,
  type ImportedDocumentSummary,
} from "./import-quotations";

const t = (key: string) => key;

function makeDocument(overrides: Partial<ImportedDocumentSummary> = {}): ImportedDocumentSummary {
  return {
    id: 1,
    batch_id: 1,
    filename: "quote.pdf",
    file_size: 1024,
    document_kind: "QUOTATION",
    extraction_status: "PENDING",
    review_status: "NEEDS_REVIEW",
    extraction_error: null,
    created_at: "2026-01-01T00:00:00Z",
    job_status: "QUEUED",
    job_attempts: 0,
    job_last_error: null,
    ...overrides,
  };
}

describe("isRetryable", () => {
  it("is not retryable while a job is still queued or processing, even if extraction previously failed", () => {
    expect(isRetryable(makeDocument({ extraction_status: "FAILED", job_status: "QUEUED" }))).toBe(
      false,
    );
    expect(
      isRetryable(makeDocument({ extraction_status: "FAILED", job_status: "PROCESSING" })),
    ).toBe(false);
  });

  it("is retryable once a job has finished and left the document FAILED/UNSUPPORTED/OCR_REQUIRED", () => {
    for (const status of [
      "FAILED",
      "UNSUPPORTED",
      "OCR_REQUIRED",
      "MULTIPLE_QUOTATIONS_DETECTED",
    ]) {
      expect(
        isRetryable(makeDocument({ extraction_status: status, job_status: "SUCCEEDED" })),
      ).toBe(true);
    }
  });

  it("is not retryable once extraction genuinely completed", () => {
    expect(
      isRetryable(
        makeDocument({ extraction_status: "EXTRACTION_COMPLETE", job_status: "SUCCEEDED" }),
      ),
    ).toBe(false);
  });

  it("treats a null job_status (a document staged before the queue existed) the same as terminal", () => {
    expect(isRetryable(makeDocument({ extraction_status: "FAILED", job_status: null }))).toBe(true);
  });
});

describe("documentStatusLabel", () => {
  it("shows the live queue state while a job is active, even if extraction_status looks stale", () => {
    expect(
      documentStatusLabel(makeDocument({ job_status: "QUEUED", extraction_status: "PENDING" }), t),
    ).toBe("imp.status.queued");
    expect(
      documentStatusLabel(
        makeDocument({ job_status: "PROCESSING", extraction_status: "PENDING" }),
        t,
      ),
    ).toBe("imp.status.processing");
  });

  it("falls back to the extraction status label once the job is no longer active", () => {
    expect(
      documentStatusLabel(
        makeDocument({ job_status: "SUCCEEDED", extraction_status: "EXTRACTION_COMPLETE" }),
        t,
      ),
    ).toBe("imp.status.complete");
    expect(
      documentStatusLabel(makeDocument({ job_status: "FAILED", extraction_status: "FAILED" }), t),
    ).toBe("imp.status.failed");
  });
});

describe("formatFileSize", () => {
  it("formats bytes, kilobytes, and megabytes appropriately", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(2048)).toBe("2.0 KB");
    expect(formatFileSize(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});
