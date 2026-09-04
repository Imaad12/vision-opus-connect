import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import {
  Archive,
  Ban,
  ChevronLeft,
  ChevronRight,
  FileText,
  Loader2,
  Pencil,
  RotateCw,
  Trash2,
  Upload,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type RefObject,
} from "react";
import { toast } from "sonner";

import { NoAccess, PageHeader } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useMe } from "@/hooks/use-auth";
import { ApiError, api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

/**
 * Standalone, flat route (NOT `quotations.import.tsx`) -- deliberately.
 * TanStack Router's flat file-based routing would otherwise nest a
 * `quotations.import.tsx` under `quotations.tsx` by naming convention
 * alone, exactly the bug `settings.tsx` had (see
 * settings-routing.test.ts) before it was split into a real layout +
 * index. `quotations.tsx` isn't a layout and doesn't render an
 * `<Outlet />`, so repeating that file-naming pattern here would
 * silently swallow this whole page. Reached instead via a real link
 * from the Quotations page's own header action.
 *
 * A thin UI over `backend/app/api/routers/imports.py`, which itself is
 * a thin REST wrapper over the existing, already-built desktop-era
 * import/OCR pipeline (`app/services/import_service.py` et al.) --
 * nothing about extraction/segmentation/matching/confirmation is
 * reimplemented here. Deliberately narrow first pass: single-document
 * review/confirm only (no sequential-segmentation review UI yet -- see
 * this feature's own report).
 */
export const Route = createFileRoute("/_authenticated/import-quotations")({
  head: () => ({
    meta: [
      { title: "Import Historical Quotations — VINCO ERP" },
      {
        name: "description",
        content: "Upload and review historical quotation documents for import.",
      },
    ],
  }),
  component: ImportQuotationsPage,
});

type BatchLifecycleStatus = "EMPTY" | "STAGING" | "PROCESSING" | "COMPLETED" | "ARCHIVED";

type ImportBatch = {
  id: number;
  label: string | null;
  notes: string | null;
  staged_count: number;
  resumed_count: number;
  skipped_duplicate_count: number;
  failed_count: number;
  completed_at: string | null;
  archived_at: string | null;
  created_at: string;
  /** Derived server-side (never a stored column) -- see
   * `app.core.enums.BatchLifecycleStatus`. Governs which of Rename/
   * Delete/Archive/Cancel are offered below. */
  status: BatchLifecycleStatus;
};

type ImportDashboardSummary = {
  total: number;
  /** Job-table-derived (P16) -- how many documents have a QUEUED/
   * PROCESSING `ImportJob` right now. This -- not any
   * `extraction_status` heuristic -- is what drives this page's polling
   * (see `ImportWorkspace`'s queries below): the queue is the real
   * source of truth for "is anything still happening". */
  queued: number;
  processing: number;
  extraction_complete: number;
  needs_review: number;
  confirmed: number;
  rejected: number;
  failed: number;
  duplicates: number | null;
  purchase_order_count: number;
};

type JobStatus = "QUEUED" | "PROCESSING" | "SUCCEEDED" | "FAILED";

export type ImportedDocumentSummary = {
  id: number;
  batch_id: number | null;
  filename: string;
  file_size: number;
  document_kind: string;
  extraction_status: string;
  review_status: string;
  extraction_error: string | null;
  created_at: string;
  /** `null` only for a document staged before the durable queue existed
   * and never retried since -- see `ImportedDocumentSummary`'s own
   * backend docstring. */
  job_status: JobStatus | null;
  job_attempts: number | null;
  job_last_error: string | null;
};

type ImportedQuotationCandidate = {
  quotation_number: string | null;
  quotation_date: string | null;
  client_name: string | null;
  project_name: string | null;
  project_number: string | null;
  description: string | null;
  currency: string | null;
  net_value: string | null;
  tax_value: string | null;
  gross_value: string | null;
  valid_until: string | null;
  payment_terms: string | null;
  notes: string | null;
  field_confidence: Record<string, string>;
};

type ImportedDocumentDetail = ImportedDocumentSummary & {
  resulting_client_id: number | null;
  resulting_project_id: number | null;
  resulting_quotation_id: number | null;
  quotation_candidate: ImportedQuotationCandidate | null;
  /** `null` whenever a page-by-page preview isn't available -- a
   * non-PDF document, or a PDF the backend couldn't open. Never
   * fabricated: the review workspace's preview panel must treat `null`
   * as "no preview", not as "one page" (see `schemas_imports.
   * ImportedDocumentRead.page_count`'s own docstring). */
  page_count: number | null;
};

type BatchUploadAccepted = {
  batch_id: number;
  accepted_files: string[];
  accepted_count: number;
  duplicate_count: number;
  queued_count: number;
  document_ids: number[];
};

/** Mirrors `app.services.import_service._QUOTATION_EDITABLE_FIELDS`
 * exactly -- every extracted quotation field a reviewer is allowed to
 * correct in the workspace below, before confirming. */
const EDITABLE_CANDIDATE_FIELDS = [
  "quotation_number",
  "quotation_date",
  "client_name",
  "project_name",
  "project_number",
  "description",
  "currency",
  "net_value",
  "tax_value",
  "gross_value",
  "valid_until",
  "payment_terms",
  "notes",
] as const;

type EditableCandidateField = (typeof EDITABLE_CANDIDATE_FIELDS)[number];

/** `PATCH /imports/documents/{id}/candidate`'s request body -- every
 * field optional (only fields actually edited are sent, see
 * `ReviewDialog`'s `edited` state below). */
type UpdateQuotationCandidatePayload = Partial<Record<EditableCandidateField, string | null>>;

/** Drives the review workspace's editable form -- one entry per
 * `EDITABLE_CANDIDATE_FIELDS` value, in the order shown to the
 * reviewer. The first six are the mockup's primary fields (Customer/
 * Project/Reference/Date/Valid until/Currency/Subtotal/VAT/Total); the
 * rest are shown as secondary "more details" fields, still fully
 * editable -- nothing on the candidate is hidden from correction. */
const CANDIDATE_FIELD_DEFS: {
  key: EditableCandidateField;
  labelKey: string;
  inputType: "text" | "date" | "textarea";
  primary: boolean;
}[] = [
  { key: "client_name", labelKey: "imp.review.client_name", inputType: "text", primary: true },
  { key: "project_name", labelKey: "imp.review.project_name", inputType: "text", primary: true },
  {
    key: "quotation_number",
    labelKey: "imp.review.field.quotation_number",
    inputType: "text",
    primary: true,
  },
  {
    key: "quotation_date",
    labelKey: "imp.review.field.quotation_date",
    inputType: "date",
    primary: true,
  },
  {
    key: "valid_until",
    labelKey: "imp.review.field.valid_until",
    inputType: "date",
    primary: true,
  },
  { key: "currency", labelKey: "imp.review.field.currency", inputType: "text", primary: true },
  { key: "net_value", labelKey: "imp.review.field.net_value", inputType: "text", primary: true },
  { key: "tax_value", labelKey: "imp.review.field.tax_value", inputType: "text", primary: true },
  {
    key: "gross_value",
    labelKey: "imp.review.field.gross_value",
    inputType: "text",
    primary: true,
  },
  {
    key: "project_number",
    labelKey: "imp.review.field.project_number",
    inputType: "text",
    primary: false,
  },
  {
    key: "payment_terms",
    labelKey: "imp.review.field.payment_terms",
    inputType: "text",
    primary: false,
  },
  {
    key: "description",
    labelKey: "imp.review.field.description",
    inputType: "textarea",
    primary: false,
  },
  { key: "notes", labelKey: "imp.review.notes", inputType: "textarea", primary: false },
];

/** A document whose `ImportJob` is still QUEUED or PROCESSING -- used to
 * decide when to show a spinner and when this page should keep polling
 * (see `summaryQuery`/`documentsQuery`'s `refetchInterval` below). Job
 * status, not `extraction_status`, is the real source of truth for "is
 * anything still happening to this document" now that a durable queue
 * (not a same-process background task) is what actually runs
 * extraction -- see `ImportedDocumentSummary.job_status`'s own comment. */
const ACTIVE_JOB_STATUSES = new Set(["QUEUED", "PROCESSING"]);

/** Extraction outcomes a reviewer can retry (P8) -- a job that ran to
 * completion (`job_status` is terminal, not QUEUED/PROCESSING) but left
 * the document somewhere other than ready-for-review or already
 * decided. */
const RETRYABLE_EXTRACTION_STATUSES = new Set([
  "FAILED",
  "UNSUPPORTED",
  "OCR_REQUIRED",
  "MULTIPLE_QUOTATIONS_DETECTED",
]);

export function isRetryable(document: ImportedDocumentSummary): boolean {
  return (
    RETRYABLE_EXTRACTION_STATUSES.has(document.extraction_status) &&
    !ACTIVE_JOB_STATUSES.has(document.job_status ?? "")
  );
}

/** Human-readable label for each `ExtractionStatus` value, matching the
 * "Uploading... / OCR processing... / Extracting quotation... / Ready
 * for review / Failed — [reason]" progression this feature was asked
 * for. `extraction_error` (when present) is appended separately by the
 * caller, not baked in here, so the same label works whether or not
 * there's a message to show. */
function extractionStatusLabel(status: string, t: (key: string) => string): string {
  switch (status) {
    case "PENDING":
      return t("imp.status.pending");
    case "EXTRACTING":
      return t("imp.status.extracting");
    case "EXTRACTION_COMPLETE":
      return t("imp.status.complete");
    case "OCR_REQUIRED":
      return t("imp.status.ocr_required");
    case "SEGMENTS_PROPOSED":
      return t("imp.status.segments_proposed");
    case "MULTIPLE_QUOTATIONS_DETECTED":
      return t("imp.status.multiple_quotations");
    case "UNSUPPORTED":
      return t("imp.status.unsupported");
    case "FAILED":
      return t("imp.status.failed");
    default:
      return status;
  }
}

/** What the "Extraction" column actually shows for one row -- the
 * queue's own live state (Queued/Processing) takes priority over the
 * document's last-known `extraction_status` whenever a job is actively
 * QUEUED/PROCESSING for it, since that status is about to change and
 * showing a stale terminal-looking label would be misleading. Once the
 * job is done, falls back to `extractionStatusLabel` exactly as before. */
export function documentStatusLabel(
  document: ImportedDocumentSummary,
  t: (key: string) => string,
): string {
  if (document.job_status === "QUEUED") return t("imp.status.queued");
  if (document.job_status === "PROCESSING") return t("imp.status.processing");
  return extractionStatusLabel(document.extraction_status, t);
}

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.describe();
  if (e instanceof Error) return e.message;
  return String(e);
}

function ImportQuotationsPage() {
  const { t } = useI18n();
  const me = useMe();

  if (!me.can("quotations.create")) {
    return (
      <>
        <PageHeader title={t("imp.title")} />
        <NoAccess />
      </>
    );
  }

  return <ImportWorkspace />;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const BATCH_STATUS_BADGE_VARIANT: Record<
  BatchLifecycleStatus,
  "outline" | "secondary" | "destructive"
> = {
  EMPTY: "outline",
  STAGING: "secondary",
  PROCESSING: "secondary",
  COMPLETED: "outline",
  ARCHIVED: "outline",
};

function ImportWorkspace() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedBatchId, setSelectedBatchId] = useState<number | null>(null);
  const [newBatchLabel, setNewBatchLabel] = useState("");
  const [reviewing, setReviewing] = useState<number | null>(null);
  const [editingBatch, setEditingBatch] = useState(false);
  // Tracked in React state (not read from the ref only at submit time) so
  // the UI can show what's actually selected and gate the Upload button on
  // it -- previously nothing displayed the selection at all, and Upload
  // stayed enabled with zero files chosen (a silent no-op on click, easily
  // mistaken for "the picker isn't working"). `fileInputRef` itself is
  // still needed too: clearing `input.value` after a successful upload is
  // the only way to actually reset a native file input's selection.
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);

  const batchesQuery = useQuery({
    queryKey: ["import-batches"],
    queryFn: () => api.get<ImportBatch[]>("/imports/batches"),
  });

  const createBatchMutation = useMutation({
    mutationFn: (label: string) =>
      api.post<ImportBatch>("/imports/batches", { label: label.trim() || null }),
    onSuccess: (batch) => {
      setNewBatchLabel("");
      setSelectedBatchId(batch.id);
      void queryClient.invalidateQueries({ queryKey: ["import-batches"] });
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  const summaryQuery = useQuery({
    queryKey: ["import-batch-summary", selectedBatchId],
    enabled: selectedBatchId !== null,
    queryFn: () => api.get<ImportDashboardSummary>(`/imports/batches/${selectedBatchId}/summary`),
    // The queue (not any per-document heuristic) decides whether this
    // page keeps polling: once `queued + processing` reaches zero, every
    // document this batch's upload(s) created has genuinely finished its
    // pipeline run -- there is nothing left that could still change.
    // 4s (P7's "3-5 seconds while jobs are active") replaces the
    // previous 1.5s interval; combined with the durable queue actually
    // draining (instead of a BackgroundTask that could silently die and
    // poll forever), this is both gentler on the backend and, per this
    // feature's own root-cause finding, less likely to visibly interfere
    // with the native file picker while a reviewer is mid-selection.
    refetchInterval: (query) => {
      const s = query.state.data;
      return s && s.queued + s.processing > 0 ? 4000 : false;
    },
  });

  const documentsQuery = useQuery({
    queryKey: ["import-batch-documents", selectedBatchId],
    enabled: selectedBatchId !== null,
    queryFn: () =>
      api.get<ImportedDocumentSummary[]>(`/imports/batches/${selectedBatchId}/documents`),
    refetchInterval: () => {
      const s = summaryQuery.data;
      return s && s.queued + s.processing > 0 ? 4000 : false;
    },
  });

  const invalidateBatch = () => {
    void queryClient.invalidateQueries({ queryKey: ["import-batch-summary", selectedBatchId] });
    void queryClient.invalidateQueries({ queryKey: ["import-batch-documents", selectedBatchId] });
    void queryClient.invalidateQueries({ queryKey: ["import-batches"] });
  };

  const uploadMutation = useMutation({
    mutationFn: (files: File[]) =>
      api.uploadFiles<BatchUploadAccepted>(
        `/imports/batches/${selectedBatchId}/documents`,
        "files",
        files,
      ),
    onSuccess: (result) => {
      const parts = [`${result.accepted_count} ${t("imp.upload.accepted_suffix")}`];
      if (result.duplicate_count > 0)
        parts.push(`${result.duplicate_count} ${t("imp.summary.duplicates").toLowerCase()}`);
      toast.success(parts.join(", "));
      invalidateBatch();
      if (fileInputRef.current) fileInputRef.current.value = "";
      setSelectedFiles([]);
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  const retryMutation = useMutation({
    mutationFn: (documentId: number) => api.post(`/imports/documents/${documentId}/retry`, {}),
    onSuccess: () => {
      toast.success(t("imp.action.retried_note"));
      invalidateBatch();
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  const archiveMutation = useMutation({
    mutationFn: (batchId: number) =>
      api.post<ImportBatch>(`/imports/batches/${batchId}/archive`, {}),
    onSuccess: () => {
      toast.success(t("common.saved"));
      void queryClient.invalidateQueries({ queryKey: ["import-batches"] });
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  const cancelMutation = useMutation({
    mutationFn: (batchId: number) =>
      api.post<ImportBatch>(`/imports/batches/${batchId}/cancel`, {}),
    onSuccess: () => {
      toast.success(t("common.saved"));
      invalidateBatch();
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  const deleteMutation = useMutation({
    mutationFn: (batchId: number) => api.delete(`/imports/batches/${batchId}`),
    onSuccess: () => {
      toast.success(t("common.saved"));
      setSelectedBatchId(null);
      void queryClient.invalidateQueries({ queryKey: ["import-batches"] });
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  const handleFilesChosen = (e: ChangeEvent<HTMLInputElement>) => {
    setSelectedFiles(Array.from(e.target.files ?? []));
  };

  const handleUpload = (e: FormEvent) => {
    e.preventDefault();
    // Reads from state (populated by the input's own onChange), not from
    // `fileInputRef.current.files` at submit time -- both point at the
    // same underlying FileList in practice, but state is what the button's
    // `disabled` check below also uses, so there's exactly one source of
    // truth for "are files selected" rather than two that could disagree.
    if (selectedFiles.length === 0 || selectedBatchId === null) return;
    uploadMutation.mutate(selectedFiles);
  };

  const summary = summaryQuery.data;
  const documents = documentsQuery.data ?? [];
  const selectedBatch = (batchesQuery.data ?? []).find((b) => b.id === selectedBatchId) ?? null;
  const isArchived = selectedBatch?.status === "ARCHIVED";
  const isProcessing = selectedBatch?.status === "PROCESSING";

  return (
    <>
      <PageHeader title={t("imp.title")} description={t("imp.description")} />

      <div className="space-y-6">
        <div className="surface-panel space-y-4 p-4">
          <p className="text-sm font-medium">{t("imp.batch.title")}</p>
          <div className="flex flex-wrap items-center gap-2">
            <select
              className="h-9 min-w-[220px] rounded-md border border-input bg-background px-2 text-sm"
              value={selectedBatchId ?? ""}
              onChange={(e) => setSelectedBatchId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">{t("imp.batch.select")}</option>
              {(batchesQuery.data ?? []).map((b) => (
                <option key={b.id} value={b.id}>
                  #{b.id} {b.label ?? ""} ({b.staged_count} staged)
                </option>
              ))}
            </select>

            {selectedBatch && (
              <Badge variant={BATCH_STATUS_BADGE_VARIANT[selectedBatch.status]}>
                {t(`imp.batch.status.${selectedBatch.status}`)}
              </Badge>
            )}

            {selectedBatch && !isArchived && (
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                onClick={() => setEditingBatch(true)}
              >
                <Pencil className="size-3.5" />
                {t("imp.batch.rename")}
              </Button>
            )}
            {selectedBatch &&
              (selectedBatch.status === "EMPTY" || selectedBatch.status === "STAGING") && (
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5 text-destructive"
                  disabled={deleteMutation.isPending}
                  onClick={() => {
                    if (window.confirm(t("imp.batch.confirm_delete")))
                      deleteMutation.mutate(selectedBatch.id);
                  }}
                >
                  <Trash2 className="size-3.5" />
                  {t("imp.batch.delete")}
                </Button>
              )}
            {selectedBatch && isProcessing && (
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                disabled={cancelMutation.isPending}
                onClick={() => {
                  if (window.confirm(t("imp.batch.confirm_cancel")))
                    cancelMutation.mutate(selectedBatch.id);
                }}
              >
                <Ban className="size-3.5" />
                {t("imp.batch.cancel_processing")}
              </Button>
            )}
            {selectedBatch && selectedBatch.status === "COMPLETED" && (
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                disabled={archiveMutation.isPending}
                onClick={() => archiveMutation.mutate(selectedBatch.id)}
              >
                <Archive className="size-3.5" />
                {t("imp.batch.archive")}
              </Button>
            )}

            <Input
              value={newBatchLabel}
              onChange={(e) => setNewBatchLabel(e.target.value)}
              placeholder={t("imp.batch.new_label")}
              className="max-w-xs"
            />
            <Button
              variant="outline"
              disabled={createBatchMutation.isPending}
              onClick={() => createBatchMutation.mutate(newBatchLabel)}
              className="gap-1.5"
            >
              {createBatchMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
              {t("imp.batch.create")}
            </Button>
          </div>
          {isArchived && (
            <p className="text-xs text-muted-foreground">{t("imp.batch.archived_readonly")}</p>
          )}
        </div>

        {selectedBatchId !== null && (
          <>
            {!isArchived && (
              <UploadFilesForm
                fileInputRef={fileInputRef}
                selectedFiles={selectedFiles}
                onFilesChosen={handleFilesChosen}
                onSubmit={handleUpload}
                submitting={uploadMutation.isPending}
                t={t}
              />
            )}

            {summary && (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
                {(
                  [
                    ["imp.summary.total", summary.total],
                    ["imp.summary.queued", summary.queued],
                    ["imp.summary.processing", summary.processing],
                    ["imp.summary.needs_review", summary.needs_review],
                    ["imp.summary.confirmed", summary.confirmed],
                    ["imp.summary.rejected", summary.rejected],
                    ["imp.summary.failed", summary.failed],
                    ["imp.summary.duplicates", summary.duplicates ?? 0],
                  ] as const
                ).map(([labelKey, value]) => (
                  <div key={labelKey} className="surface-panel p-3 text-center">
                    <p className="num text-2xl font-semibold">{value}</p>
                    <p className="text-xs text-muted-foreground">{t(labelKey)}</p>
                  </div>
                ))}
              </div>
            )}

            <div className="surface-panel overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
                    <th className="px-3 py-2.5 text-start">{t("imp.table.filename")}</th>
                    <th className="px-3 py-2.5 text-start">{t("imp.table.size")}</th>
                    <th className="px-3 py-2.5 text-start">{t("imp.table.extraction")}</th>
                    <th className="px-3 py-2.5 text-start">{t("imp.table.review")}</th>
                    <th className="px-3 py-2.5 text-start">{t("imp.table.attempts")}</th>
                    <th className="px-3 py-2.5 text-start">{t("common.actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {documentsQuery.isLoading && (
                    <tr>
                      <td colSpan={6} className="px-3 py-8 text-center text-muted-foreground">
                        {t("common.loading")}
                      </td>
                    </tr>
                  )}
                  {!documentsQuery.isLoading && documents.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-3 py-8 text-center text-muted-foreground">
                        {t("common.empty")}
                      </td>
                    </tr>
                  )}
                  {documents.map((d) => (
                    <tr key={d.id} className="border-b border-border/70 last:border-0">
                      <td className="px-3 py-2.5 font-medium">{d.filename}</td>
                      <td className="num px-3 py-2.5 text-xs text-muted-foreground">
                        {formatFileSize(d.file_size)}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-1.5">
                          {ACTIVE_JOB_STATUSES.has(d.job_status ?? "") && (
                            <Loader2 className="size-3.5 animate-spin text-muted-foreground" />
                          )}
                          <Badge
                            variant={
                              d.extraction_status === "FAILED" ||
                              d.extraction_status === "UNSUPPORTED"
                                ? "destructive"
                                : d.extraction_status === "OCR_REQUIRED"
                                  ? "secondary"
                                  : "outline"
                            }
                          >
                            {documentStatusLabel(d, t)}
                          </Badge>
                        </div>
                        {(d.extraction_error || d.job_last_error) && (
                          <p className="mt-1 text-xs text-muted-foreground">
                            {d.extraction_error ?? d.job_last_error}
                          </p>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <Badge
                          variant={d.review_status === "NEEDS_REVIEW" ? "secondary" : "outline"}
                        >
                          {d.review_status}
                        </Badge>
                      </td>
                      <td className="num px-3 py-2.5 text-xs text-muted-foreground">
                        {d.job_attempts ?? "—"}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-1">
                          <Button variant="outline" size="sm" onClick={() => setReviewing(d.id)}>
                            {t("imp.action.review")}
                          </Button>
                          {isRetryable(d) && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="gap-1"
                              disabled={retryMutation.isPending}
                              onClick={() => retryMutation.mutate(d.id)}
                            >
                              <RotateCw className="size-3.5" />
                              {t("imp.action.retry")}
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      <ReviewDialog
        documentId={reviewing}
        onOpenChange={(open) => !open && setReviewing(null)}
        onChanged={invalidateBatch}
      />
      <BatchEditDialog
        batch={editingBatch ? selectedBatch : null}
        onOpenChange={(open) => setEditingBatch(open)}
        onSaved={() => void queryClient.invalidateQueries({ queryKey: ["import-batches"] })}
      />
    </>
  );
}

/** P10's deliberately minimal "Edit batch" -- label and optional notes,
 * nothing else. */
function BatchEditDialog({
  batch,
  onOpenChange,
  onSaved,
}: {
  batch: ImportBatch | null;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const [label, setLabel] = useState("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (batch) {
      setLabel(batch.label ?? "");
      setNotes(batch.notes ?? "");
    }
  }, [batch]);

  const saveMutation = useMutation({
    mutationFn: () =>
      api.patch<ImportBatch>(`/imports/batches/${batch?.id}`, {
        label: label.trim() || null,
        notes: notes.trim() || null,
      }),
    onSuccess: () => {
      toast.success(t("common.saved"));
      onOpenChange(false);
      onSaved();
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  return (
    <Dialog open={batch !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t("imp.batch.edit_title")}</DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            saveMutation.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="batch-edit-label">{t("imp.batch.label_field")}</Label>
            <Input id="batch-edit-label" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batch-edit-notes">{t("imp.batch.notes_field")}</Label>
            <Textarea
              id="batch-edit-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={saveMutation.isPending}>
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** The batch upload form -- a plain, exported subcomponent (not inlined
 * into `ImportWorkspace`) specifically so it can be rendered and clicked
 * in isolation by a DOM-level test (`import-quotations.upload.test.tsx`)
 * without needing to mock this page's Supabase/react-query/router
 * dependencies. See the file input's own inline comment for why it's a
 * genuine native `<input type="file">` clicked directly, not a hidden
 * input behind a ref.click() proxy. */
export function UploadFilesForm({
  fileInputRef,
  selectedFiles,
  onFilesChosen,
  onSubmit,
  submitting,
  t,
}: {
  fileInputRef: RefObject<HTMLInputElement | null>;
  selectedFiles: File[];
  onFilesChosen: (e: ChangeEvent<HTMLInputElement>) => void;
  onSubmit: (e: FormEvent) => void;
  submitting: boolean;
  t: (key: string) => string;
}) {
  return (
    <form className="surface-panel space-y-3 p-4" onSubmit={onSubmit}>
      <p className="text-sm font-medium">{t("imp.upload.title")}</p>
      <p className="text-xs text-muted-foreground">{t("imp.upload.hint")}</p>
      <div className="flex flex-wrap items-center gap-2">
        {/* A genuine native <input type="file">, clicked directly by
            the user -- deliberately NOT a hidden input behind a
            styled <button> + ref.click() proxy (that indirection is
            exactly what tends to silently break: a wrapping form/
            button swallowing the click, a re-render replacing the
            node, a disabled/overlay state creeping in). Tailwind's
            `file:*` classes style this element's own native
            "Choose Files" button in place, so there is no separate
            click target that can fall out of sync with it -- this
            works identically in Chrome/Safari on macOS and in the
            Tauri desktop WebView, none of which need any special
            handling for a plain file input. */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="application/pdf"
          onChange={onFilesChosen}
          aria-label={t("imp.upload.choose_files")}
          className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-1.5 file:text-sm"
        />
        <Button
          type="submit"
          disabled={submitting || selectedFiles.length === 0}
          className="gap-1.5"
        >
          {submitting ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
          {t("imp.upload.button")}
        </Button>
      </div>
      {selectedFiles.length > 0 && (
        <p className="text-xs text-muted-foreground" data-testid="imp-selected-files">
          {selectedFiles.length} {t("imp.upload.selected_suffix")}:{" "}
          {selectedFiles.map((f) => f.name).join(", ")}
        </p>
      )}
    </form>
  );
}

/** Left-hand pane of the review workspace: the original source document,
 * paged through server-rendered PNGs (`GET /imports/documents/{id}/pages/
 * {n}`, reusing `app.core.document_preview.render_page_preview` exactly
 * as the desktop app's own rendering path -- see that endpoint's own
 * docstring). Fetched as a `Blob` (not a plain `<img src="...">`) because
 * the endpoint is behind the same Bearer-token auth as every other
 * `/imports/*` route, which an `<img>` tag cannot attach on its own.
 *
 * `pageCount === null` means the backend genuinely has no preview to
 * offer (non-PDF, or a PDF it couldn't open) -- shown honestly as "no
 * preview", never faked as a single page. */
function DocumentPreviewPanel({
  documentId,
  pageCount,
}: {
  documentId: number;
  pageCount: number | null;
}) {
  const { t } = useI18n();
  const [page, setPage] = useState(1);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    setPage(1);
  }, [documentId]);

  useEffect(() => {
    if (pageCount === null) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    setLoading(true);
    setLoadError(false);
    api
      .getBlob(`/imports/documents/${documentId}/pages/${page}`)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setImageUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setLoadError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [documentId, page, pageCount]);

  if (pageCount === null) {
    return (
      <div className="flex h-full min-h-[320px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        <FileText className="size-8" />
        {t("imp.review.preview.unavailable")}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex min-h-[320px] flex-1 items-center justify-center overflow-auto rounded-lg border border-border bg-muted/30 p-2">
        {loading && <Loader2 className="size-6 animate-spin text-muted-foreground" />}
        {!loading && loadError && (
          <p className="p-4 text-center text-sm text-destructive">
            {t("imp.review.preview.load_error")}
          </p>
        )}
        {!loading && !loadError && imageUrl && (
          // Server-rendered page image, not an interactive PDF widget --
          // a plain <img> is exactly right here.
          <img
            src={imageUrl}
            alt={`${t("imp.review.preview.page")} ${page}`}
            className="max-h-[65vh] w-auto max-w-full shadow-sm"
          />
        )}
      </div>
      <div className="flex items-center justify-center gap-2 text-sm">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={page <= 1}
          onClick={() => setPage((p) => p - 1)}
        >
          <ChevronLeft className="size-4" />
        </Button>
        <span className="num text-muted-foreground">
          {t("imp.review.preview.page")} {page} {t("imp.review.preview.of")} {pageCount}
        </span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={page >= pageCount}
          onClick={() => setPage((p) => p + 1)}
        >
          <ChevronRight className="size-4" />
        </Button>
      </div>
    </div>
  );
}

/** One editable field in the review workspace's form, driven by
 * `CANDIDATE_FIELD_DEFS`. Shows the field's `ConfidenceLevel` (HIGH/
 * NEEDS_REVIEW/LOW) as a small badge, and visibly flags anything below
 * HIGH so a low-confidence extraction never blends in with a
 * confidently-read one -- exactly the "fields with low confidence
 * should be visibly marked" requirement this workspace exists for. */
function CandidateFieldRow({
  def,
  candidate,
  edited,
  disabled,
  onChange,
}: {
  def: (typeof CANDIDATE_FIELD_DEFS)[number];
  candidate: ImportedQuotationCandidate;
  edited: UpdateQuotationCandidatePayload;
  disabled: boolean;
  onChange: (field: EditableCandidateField, value: string) => void;
}) {
  const { t } = useI18n();
  const key = def.key;
  const editedValue = edited[key];
  const value = editedValue !== undefined ? (editedValue ?? "") : (candidate[key] ?? "");
  const confidence = candidate.field_confidence[key];
  const isLowConfidence = confidence === "LOW" || confidence === "NEEDS_REVIEW";
  const inputId = `review-${key}`;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <Label htmlFor={inputId}>{t(def.labelKey)}</Label>
        {confidence && (
          <Badge
            variant={confidence === "HIGH" ? "outline" : "secondary"}
            className={
              isLowConfidence ? "border-amber-500 text-[10px] text-amber-700" : "text-[10px]"
            }
          >
            {confidence}
          </Badge>
        )}
      </div>
      {def.inputType === "textarea" ? (
        <Textarea
          id={inputId}
          value={value}
          disabled={disabled}
          className={isLowConfidence ? "border-amber-500" : undefined}
          onChange={(e) => onChange(key, e.target.value)}
        />
      ) : (
        <Input
          id={inputId}
          type={def.inputType}
          value={value}
          disabled={disabled}
          className={isLowConfidence ? "border-amber-500" : undefined}
          onChange={(e) => onChange(key, e.target.value)}
        />
      )}
    </div>
  );
}

function ReviewDialog({
  documentId,
  onOpenChange,
  onChanged,
}: {
  documentId: number | null;
  onOpenChange: (open: boolean) => void;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const [includeBoq, setIncludeBoq] = useState(true);
  const [rejectReason, setRejectReason] = useState("");
  const [edited, setEdited] = useState<UpdateQuotationCandidatePayload>({});

  // A fresh document must never inherit another document's unsaved
  // edits/reject-reason -- the previous version of this dialog kept
  // `clientName`/`projectName` state across documents entirely
  // unreset, a real latent bug (switching to review document B could
  // silently carry over document A's typed-but-unsaved override).
  useEffect(() => {
    setEdited({});
    setRejectReason("");
    setIncludeBoq(true);
  }, [documentId]);

  const documentQuery = useQuery({
    queryKey: ["import-document", documentId],
    enabled: documentId !== null,
    queryFn: () => api.get<ImportedDocumentDetail>(`/imports/documents/${documentId}`),
  });

  const document = documentQuery.data;
  const candidate = document?.quotation_candidate ?? null;
  const isDecided =
    document?.review_status === "CONFIRMED" || document?.review_status === "REJECTED";
  const hasEdits = Object.keys(edited).length > 0;

  const handleFieldChange = (field: EditableCandidateField, raw: string) => {
    setEdited((prev) => ({ ...prev, [field]: raw === "" ? null : raw }));
  };

  const saveMutation = useMutation({
    mutationFn: () =>
      api.patch<ImportedDocumentDetail>(`/imports/documents/${documentId}/candidate`, edited),
    onSuccess: () => {
      toast.success(t("imp.review.saved_note"));
      setEdited({});
      onChanged();
      void documentQuery.refetch();
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  const confirmMutation = useMutation({
    mutationFn: async () => {
      // The workspace has a single primary action (matching the
      // reviewer's mental model: correct fields, then confirm) --
      // any pending corrections are saved first so the quotation
      // `confirm_import` creates always reflects exactly what's shown
      // on screen, never a stale pre-edit value.
      if (Object.keys(edited).length > 0) {
        await api.patch<ImportedDocumentDetail>(
          `/imports/documents/${documentId}/candidate`,
          edited,
        );
      }
      const effectiveClientName = (
        (edited.client_name !== undefined ? edited.client_name : candidate?.client_name) ?? ""
      ).trim();
      const effectiveProjectName = (
        (edited.project_name !== undefined ? edited.project_name : candidate?.project_name) ?? ""
      ).trim();
      return api.post<ImportedDocumentDetail>(`/imports/documents/${documentId}/confirm`, {
        new_client_name: effectiveClientName || undefined,
        new_project_name: effectiveProjectName || undefined,
        include_boq: includeBoq,
      });
    },
    onSuccess: () => {
      toast.success(t("imp.review.confirmed_note"));
      setEdited({});
      onChanged();
      void documentQuery.refetch();
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  const rejectMutation = useMutation({
    mutationFn: () =>
      api.post<ImportedDocumentDetail>(`/imports/documents/${documentId}/reject`, {
        reason: rejectReason.trim() || undefined,
      }),
    onSuccess: () => {
      toast.success(t("imp.review.rejected_note"));
      onChanged();
      void documentQuery.refetch();
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  return (
    <Dialog open={documentId !== null} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[92vh] flex-col overflow-hidden sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>{document?.filename ?? t("imp.review.title")}</DialogTitle>
        </DialogHeader>

        {documentQuery.isLoading && (
          <p className="py-6 text-center text-sm text-muted-foreground">{t("common.loading")}</p>
        )}

        {document && (
          <div className="flex flex-1 flex-col gap-4 overflow-hidden">
            <div className="grid flex-1 gap-4 overflow-hidden md:grid-cols-2">
              <DocumentPreviewPanel documentId={document.id} pageCount={document.page_count} />

              <div className="flex flex-col gap-4 overflow-y-auto pe-1">
                <p className="text-xs text-muted-foreground">{t("imp.review.source_note")}</p>

                {!candidate && (
                  <p className="text-sm text-destructive">{t("imp.review.no_candidate")}</p>
                )}

                {candidate && (
                  <div className="space-y-4">
                    <div className="grid gap-3 sm:grid-cols-2">
                      {CANDIDATE_FIELD_DEFS.filter((def) => def.primary).map((def) => (
                        <CandidateFieldRow
                          key={def.key}
                          def={def}
                          candidate={candidate}
                          edited={edited}
                          disabled={isDecided}
                          onChange={handleFieldChange}
                        />
                      ))}
                    </div>

                    <details className="rounded-md border border-border/70 p-3">
                      <summary className="cursor-pointer text-sm font-medium">
                        {t("imp.review.more_fields")}
                      </summary>
                      <div className="mt-3 grid gap-3 sm:grid-cols-2">
                        {CANDIDATE_FIELD_DEFS.filter((def) => !def.primary).map((def) => (
                          <CandidateFieldRow
                            key={def.key}
                            def={def}
                            candidate={candidate}
                            edited={edited}
                            disabled={isDecided}
                            onChange={handleFieldChange}
                          />
                        ))}
                      </div>
                    </details>

                    {!isDecided && (
                      <div className="space-y-3 border-t border-border pt-4">
                        <label className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={includeBoq}
                            onChange={(e) => setIncludeBoq(e.target.checked)}
                          />
                          {t("imp.review.include_boq")}
                        </label>
                        <div className="space-y-1.5">
                          <Label htmlFor="review-reject-reason">
                            {t("imp.review.reject_reason")}
                          </Label>
                          <Input
                            id="review-reject-reason"
                            value={rejectReason}
                            onChange={(e) => setRejectReason(e.target.value)}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {document.review_status === "CONFIRMED" && (
                  <p className="text-sm text-emerald-600">{t("imp.review.confirmed_note")}</p>
                )}
                {document.review_status === "REJECTED" && (
                  <p className="text-sm text-muted-foreground">{t("imp.review.rejected_note")}</p>
                )}
              </div>
            </div>

            {!isDecided && (
              <DialogFooter className="shrink-0 border-t border-border pt-4">
                <Button
                  type="button"
                  variant="outline"
                  disabled={rejectMutation.isPending}
                  onClick={() => rejectMutation.mutate()}
                >
                  {t("imp.review.reject")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={!hasEdits || saveMutation.isPending}
                  onClick={() => saveMutation.mutate()}
                  className="gap-1.5"
                >
                  {saveMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
                  {t("imp.review.save_changes")}
                </Button>
                <Button
                  type="button"
                  disabled={!candidate || confirmMutation.isPending}
                  onClick={() => confirmMutation.mutate()}
                  className="gap-1.5"
                >
                  {confirmMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
                  {t("imp.review.confirm")}
                </Button>
              </DialogFooter>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
