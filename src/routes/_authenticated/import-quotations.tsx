import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Loader2, Upload } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
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
import { useMe } from "@/hooks/use-auth";
import { ApiError, api } from "@/lib/api";
import { formatDate, useI18n } from "@/lib/i18n";

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

type ImportBatch = {
  id: number;
  label: string | null;
  staged_count: number;
  resumed_count: number;
  skipped_duplicate_count: number;
  failed_count: number;
  completed_at: string | null;
  created_at: string;
};

type ImportDashboardSummary = {
  total: number;
  processing: number;
  needs_review: number;
  confirmed: number;
  rejected: number;
  failed: number;
  duplicates: number | null;
  purchase_order_count: number;
};

type ImportedDocumentSummary = {
  id: number;
  batch_id: number | null;
  filename: string;
  document_kind: string;
  extraction_status: string;
  review_status: string;
  extraction_error: string | null;
  created_at: string;
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
};

type BatchUploadAccepted = {
  accepted_files: string[];
};

/** Mirrors `app.core.enums.ExtractionStatus` -- extraction hasn't
 * reached a terminal outcome yet, so the frontend should keep polling
 * (see `documentsQuery`/`summaryQuery`'s `refetchInterval` below).
 * PENDING covers both "just staged, not started yet" (effectively
 * instant in practice) and "queued behind other work in this batch's
 * background task". */
const NON_TERMINAL_EXTRACTION_STATUSES = new Set(["PENDING", "EXTRACTING"]);

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

function ImportWorkspace() {
  const { t, lang } = useI18n();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedBatchId, setSelectedBatchId] = useState<number | null>(null);
  const [newBatchLabel, setNewBatchLabel] = useState("");
  const [reviewing, setReviewing] = useState<number | null>(null);

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

  const documentsQuery = useQuery({
    queryKey: ["import-batch-documents", selectedBatchId],
    enabled: selectedBatchId !== null,
    queryFn: () =>
      api.get<ImportedDocumentSummary[]>(`/imports/batches/${selectedBatchId}/documents`),
    // Extraction runs in a background task after upload (see the
    // backend router) -- there is no push/websocket channel, so this
    // page polls while anything is still mid-pipeline (PENDING or
    // EXTRACTING) and stops once every document has reached a terminal
    // extraction_status, so the user sees "Uploading... -> OCR
    // processing... -> Ready for review" happen live rather than having
    // to manually refresh.
    refetchInterval: (query) => {
      const documents = query.state.data ?? [];
      const stillProcessing = documents.some((d) =>
        NON_TERMINAL_EXTRACTION_STATUSES.has(d.extraction_status),
      );
      return stillProcessing ? 1500 : false;
    },
  });

  const summaryQuery = useQuery({
    queryKey: ["import-batch-summary", selectedBatchId],
    enabled: selectedBatchId !== null,
    queryFn: () => api.get<ImportDashboardSummary>(`/imports/batches/${selectedBatchId}/summary`),
    refetchInterval: () => {
      const documents = documentsQuery.data ?? [];
      const stillProcessing = documents.some((d) =>
        NON_TERMINAL_EXTRACTION_STATUSES.has(d.extraction_status),
      );
      return stillProcessing ? 1500 : false;
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
      toast.success(`${result.accepted_files.length} ${t("imp.upload.accepted_suffix")}`);
      invalidateBatch();
      if (fileInputRef.current) fileInputRef.current.value = "";
    },
    onError: (e: Error) => toast.error(errorMessage(e)),
  });

  const handleUpload = (e: FormEvent) => {
    e.preventDefault();
    const files = fileInputRef.current?.files;
    if (!files || files.length === 0 || selectedBatchId === null) return;
    uploadMutation.mutate(Array.from(files));
  };

  const summary = summaryQuery.data;
  const documents = documentsQuery.data ?? [];

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
        </div>

        {selectedBatchId !== null && (
          <>
            <form className="surface-panel space-y-3 p-4" onSubmit={handleUpload}>
              <p className="text-sm font-medium">{t("imp.upload.title")}</p>
              <p className="text-xs text-muted-foreground">{t("imp.upload.hint")}</p>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-1.5 file:text-sm"
                />
                <Button type="submit" disabled={uploadMutation.isPending} className="gap-1.5">
                  {uploadMutation.isPending ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Upload className="size-4" />
                  )}
                  {t("imp.upload.button")}
                </Button>
              </div>
            </form>

            {summary && (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                {(
                  [
                    ["imp.summary.total", summary.total],
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
                    <th className="px-3 py-2.5 text-start">{t("imp.table.extraction")}</th>
                    <th className="px-3 py-2.5 text-start">{t("imp.table.review")}</th>
                    <th className="px-3 py-2.5 text-start">{t("common.actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {documentsQuery.isLoading && (
                    <tr>
                      <td colSpan={4} className="px-3 py-8 text-center text-muted-foreground">
                        {t("common.loading")}
                      </td>
                    </tr>
                  )}
                  {!documentsQuery.isLoading && documents.length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-3 py-8 text-center text-muted-foreground">
                        {t("common.empty")}
                      </td>
                    </tr>
                  )}
                  {documents.map((d) => (
                    <tr key={d.id} className="border-b border-border/70 last:border-0">
                      <td className="px-3 py-2.5 font-medium">{d.filename}</td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-1.5">
                          {NON_TERMINAL_EXTRACTION_STATUSES.has(d.extraction_status) && (
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
                            {extractionStatusLabel(d.extraction_status, t)}
                          </Badge>
                        </div>
                        {d.extraction_error && (
                          <p className="mt-1 text-xs text-muted-foreground">{d.extraction_error}</p>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <Badge
                          variant={d.review_status === "NEEDS_REVIEW" ? "secondary" : "outline"}
                        >
                          {d.review_status}
                        </Badge>
                      </td>
                      <td className="px-3 py-2.5">
                        <Button variant="outline" size="sm" onClick={() => setReviewing(d.id)}>
                          {t("imp.action.review")}
                        </Button>
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
        lang={lang}
        onOpenChange={(open) => !open && setReviewing(null)}
        onChanged={invalidateBatch}
      />
    </>
  );
}

function ReviewDialog({
  documentId,
  lang,
  onOpenChange,
  onChanged,
}: {
  documentId: number | null;
  lang: string;
  onOpenChange: (open: boolean) => void;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const [clientName, setClientName] = useState("");
  const [projectName, setProjectName] = useState("");
  const [includeBoq, setIncludeBoq] = useState(true);
  const [rejectReason, setRejectReason] = useState("");

  const documentQuery = useQuery({
    queryKey: ["import-document", documentId],
    enabled: documentId !== null,
    queryFn: () => api.get<ImportedDocumentDetail>(`/imports/documents/${documentId}`),
  });

  const confirmMutation = useMutation({
    mutationFn: () =>
      api.post<ImportedDocumentDetail>(`/imports/documents/${documentId}/confirm`, {
        new_client_name: clientName.trim() || undefined,
        new_project_name: projectName.trim() || undefined,
        include_boq: includeBoq,
      }),
    onSuccess: () => {
      toast.success(t("imp.review.confirmed_note"));
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

  const document = documentQuery.data;
  const candidate = document?.quotation_candidate ?? null;
  const isDecided =
    document?.review_status === "CONFIRMED" || document?.review_status === "REJECTED";

  const field = (label: string, value: string | null, confidenceKey?: string) => {
    if (value === null || value === "") return null;
    const confidence = confidenceKey ? candidate?.field_confidence[confidenceKey] : undefined;
    return (
      <div className="flex items-start justify-between gap-3 border-b border-border/60 py-2 text-sm last:border-0">
        <span className="text-muted-foreground">{label}</span>
        <span className="flex items-center gap-2 text-end font-medium">
          {value}
          {confidence && (
            <Badge
              variant={confidence === "HIGH" ? "outline" : "secondary"}
              className="text-[10px]"
            >
              {confidence}
            </Badge>
          )}
        </span>
      </div>
    );
  };

  return (
    <Dialog open={documentId !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{document?.filename ?? t("imp.review.title")}</DialogTitle>
        </DialogHeader>

        {documentQuery.isLoading && (
          <p className="py-6 text-center text-sm text-muted-foreground">{t("common.loading")}</p>
        )}

        {document && (
          <div className="space-y-4">
            <p className="text-xs text-muted-foreground">{t("imp.review.source_note")}</p>

            {!candidate && (
              <p className="text-sm text-destructive">{t("imp.review.no_candidate")}</p>
            )}

            {candidate && (
              <div className="surface-panel divide-y divide-border px-3">
                {field(t("imp.review.client_name"), candidate.client_name, "client_name")}
                {field(t("imp.review.project_name"), candidate.project_name, "project_name")}
                {field("Quotation #", candidate.quotation_number, "quotation_number")}
                {field(
                  "Date",
                  candidate.quotation_date
                    ? formatDate(candidate.quotation_date, lang as "en" | "ar")
                    : null,
                  "quotation_date",
                )}
                {field("Net", candidate.net_value, "net_value")}
                {field("VAT", candidate.tax_value, "tax_value")}
                {field("Gross", candidate.gross_value, "gross_value")}
              </div>
            )}

            {!isDecided && candidate && (
              <div className="space-y-3 border-t border-border pt-4">
                <div className="space-y-1.5">
                  <Label htmlFor="review-client-name">{t("imp.review.client_name")}</Label>
                  <Input
                    id="review-client-name"
                    value={clientName || candidate.client_name || ""}
                    onChange={(e) => setClientName(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="review-project-name">{t("imp.review.project_name")}</Label>
                  <Input
                    id="review-project-name"
                    value={projectName || candidate.project_name || ""}
                    onChange={(e) => setProjectName(e.target.value)}
                  />
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={includeBoq}
                    onChange={(e) => setIncludeBoq(e.target.checked)}
                  />
                  {t("imp.review.include_boq")}
                </label>
                <div className="space-y-1.5">
                  <Label htmlFor="review-reject-reason">{t("imp.review.reject_reason")}</Label>
                  <Input
                    id="review-reject-reason"
                    value={rejectReason}
                    onChange={(e) => setRejectReason(e.target.value)}
                  />
                </div>
              </div>
            )}

            {document.review_status === "CONFIRMED" && (
              <p className="text-sm text-emerald-600">{t("imp.review.confirmed_note")}</p>
            )}
            {document.review_status === "REJECTED" && (
              <p className="text-sm text-muted-foreground">{t("imp.review.rejected_note")}</p>
            )}

            {!isDecided && (
              <DialogFooter>
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
