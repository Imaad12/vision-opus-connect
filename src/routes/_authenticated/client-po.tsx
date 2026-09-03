import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { FileSignature, Paperclip, Search } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { NoAccess, PageHeader } from "@/components/app-shell";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useMe } from "@/hooks/use-auth";
import { ApiError, api } from "@/lib/api";
import { formatDate, formatMoney, useI18n } from "@/lib/i18n";
import { QK_CLIENT_AWARD_EVIDENCE } from "@/lib/shared-query-keys";

/**
 * "POs Awarded by Client" -- the CLIENT-award-evidence domain
 * (`app.models.client_award_evidence.ClientAwardEvidence`), a
 * completely separate concept from the Supplier `/purchase-orders`
 * page (`purchase-orders.tsx`): this is evidence a CLIENT awarded work
 * TO Vision Contracting; that other page is Vision Contracting
 * ordering FROM a supplier. See that backend model's own module
 * docstring and `app.api.routers.client_award_evidence`'s docstring
 * for the full distinction -- never merge these two screens or their
 * data.
 *
 * Reached both from the main nav (Sales section) and from a "View
 * Client PO" link on the Quotations page/dialog once one is recorded
 * against a given quotation -- see quotations.tsx.
 */

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.describe();
  if (e instanceof Error) return e.message;
  return String(e);
}

type ClientSummary = { id: number; name: string };
type ProjectSummary = {
  id: number;
  name: string;
  project_code: string | null;
  client: ClientSummary;
};
type QuotationSummary = {
  id: number;
  project_id: number;
  reference_number: string | null;
  title: string | null;
};
type AwardedQuotationVersion = { id: number; status: string; quotation: QuotationSummary };

export type ClientAwardEvidence = {
  id: number;
  quotation_id: number;
  po_reference_number: string;
  po_date: string | null;
  net_value: string | null;
  tax_value: string | null;
  gross_value: string | null;
  currency: string;
  notes: string | null;
  awarded_quotation_version_id: number | null;
  awarded_quotation_version: AwardedQuotationVersion | null;
  project: ProjectSummary;
  quotation_reference_number: string | null;
  quoted_value: string | null;
  variance: string | null;
  source: "manual" | "imported";
  document: { id: number; filename: string } | null;
  contracted: boolean;
  created_at: string;
  updated_at: string;
};

export const Route = createFileRoute("/_authenticated/client-po")({
  head: () => ({
    meta: [
      { title: "POs Awarded by Client — VINCO ERP" },
      {
        name: "description",
        content: "Client purchase orders recorded as evidence that a quotation was awarded.",
      },
      { property: "og:title", content: "POs Awarded by Client — VINCO ERP" },
      {
        property: "og:description",
        content: "Client award/PO evidence and variance vs. quoted value.",
      },
    ],
  }),
  component: ClientPoPage,
});

function ClientPoPage() {
  const { t, lang } = useI18n();
  const me = useMe();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");

  const canView = me.can("quotations.view");
  const canCreateContract = me.can("contracts.create");
  // Same permission the backend's `attach_client_award_evidence_document`
  // route requires (`_RECORD_PERMISSION`, shared with recording the PO
  // itself) -- see client_award_evidence.py's router docstring.
  const canUploadDocument = me.can("quotations.approve");

  const listQuery = useQuery({
    queryKey: QK_CLIENT_AWARD_EVIDENCE,
    enabled: canView,
    queryFn: () => api.get<ClientAwardEvidence[]>("/client-award-evidence"),
  });

  const refreshEvidence = () =>
    void queryClient.invalidateQueries({ queryKey: QK_CLIENT_AWARD_EVIDENCE });

  const createContract = useMutation({
    mutationFn: (projectId: number) => api.post(`/projects/${projectId}/contracts`, {}),
    onSuccess: () => {
      toast.success(t("common.saved"));
      refreshEvidence();
    },
    onError: (e: unknown) => toast.error(errorMessage(e)),
  });

  if (!canView) {
    return (
      <>
        <PageHeader title={t("nav.client_po")} />
        <NoAccess />
      </>
    );
  }

  const rows = (listQuery.data ?? []).filter((e) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return [
      e.po_reference_number,
      e.quotation_reference_number,
      e.project.name,
      e.project.client.name,
    ].some((f) => (f ?? "").toLowerCase().includes(q));
  });

  const statusOf = (e: ClientAwardEvidence) => (e.contracted ? "contracted" : "client_po_recorded");

  return (
    <>
      <PageHeader title={t("nav.client_po")} description={t("client_po.description")} />

      <div className="surface-panel overflow-hidden">
        <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
          <Search className="size-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("common.search")}
            className="h-8 border-0 bg-transparent shadow-none focus-visible:ring-0"
          />
          <span className="num text-xs text-muted-foreground">{rows.length}</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/40 text-start text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <th className="px-3 py-2.5 text-start">{t("client_po.po_number")}</th>
                <th className="px-3 py-2.5 text-start">{t("client_po.po_date")}</th>
                <th className="px-3 py-2.5 text-start">{t("quote.client")}</th>
                <th className="px-3 py-2.5 text-start">{t("quote.project")}</th>
                <th className="px-3 py-2.5 text-start">{t("client_po.quotation_ref")}</th>
                <th className="px-3 py-2.5 text-start">{t("client_po.awarded_value")}</th>
                <th className="px-3 py-2.5 text-start">{t("client_po.variance")}</th>
                <th className="px-3 py-2.5 text-start">{t("client_po.vat")}</th>
                <th className="px-3 py-2.5 text-start">{t("client_po.total_value")}</th>
                <th className="px-3 py-2.5 text-start">{t("common.status")}</th>
                <th className="px-3 py-2.5 text-start">{t("client_po.source")}</th>
                <th className="px-3 py-2.5 text-start">{t("client_po.document")}</th>
                <th className="px-3 py-2.5 text-end">{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {listQuery.isLoading && (
                <tr>
                  <td colSpan={13} className="px-3 py-8 text-center text-muted-foreground">
                    {t("common.loading")}
                  </td>
                </tr>
              )}
              {listQuery.isError && (
                <tr>
                  <td colSpan={13} className="px-3 py-8 text-center text-destructive">
                    {t("common.load_failed")}: {errorMessage(listQuery.error)}
                  </td>
                </tr>
              )}
              {!listQuery.isLoading && !listQuery.isError && rows.length === 0 && (
                <tr>
                  <td colSpan={13} className="px-3 py-10 text-center text-muted-foreground">
                    {t("common.empty")}
                  </td>
                </tr>
              )}
              {rows.map((e) => (
                <tr
                  key={e.id}
                  className="border-b border-border/70 last:border-0 hover:bg-muted/30"
                >
                  <td className="px-3 py-2.5 font-medium">{e.po_reference_number}</td>
                  <td className="px-3 py-2.5">{formatDate(e.po_date, lang)}</td>
                  <td className="px-3 py-2.5">{e.project.client.name}</td>
                  <td className="px-3 py-2.5">{e.project.name}</td>
                  <td className="px-3 py-2.5">{e.quotation_reference_number ?? "—"}</td>
                  <td className="num px-3 py-2.5">
                    {e.net_value !== null ? formatMoney(Number(e.net_value), lang) : "—"}
                  </td>
                  <td
                    className={
                      e.variance !== null && Number(e.variance) !== 0
                        ? "num px-3 py-2.5 text-[color:var(--warning)]"
                        : "num px-3 py-2.5 text-muted-foreground"
                    }
                  >
                    {e.variance !== null ? formatMoney(Number(e.variance), lang) : "—"}
                  </td>
                  <td className="num px-3 py-2.5">
                    {e.tax_value !== null ? formatMoney(Number(e.tax_value), lang) : "—"}
                  </td>
                  <td className="num px-3 py-2.5">
                    {e.gross_value !== null ? formatMoney(Number(e.gross_value), lang) : "—"}
                  </td>
                  <td className="px-3 py-2.5">
                    <StatusBadge value={statusOf(e)} />
                  </td>
                  <td className="px-3 py-2.5 text-xs text-muted-foreground">
                    {e.source === "imported"
                      ? t("client_po.source.imported")
                      : t("client_po.source.manual")}
                  </td>
                  <td className="px-3 py-2.5">
                    <ClientPoDocumentCell
                      evidence={e}
                      canUpload={canUploadDocument}
                      onUploaded={refreshEvidence}
                    />
                  </td>
                  <td className="px-3 py-2.5 text-end">
                    {!e.contracted && canCreateContract && (
                      <Button
                        variant="ghost"
                        size="icon"
                        title={t("client_po.create_contract")}
                        disabled={createContract.isPending}
                        onClick={() => createContract.mutate(e.project.id)}
                      >
                        <FileSignature className="size-4" />
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

/**
 * Document/provenance cell (P8): the file itself is written to the same
 * durable-storage location every other imports document already uses
 * (`settings.imports_storage_dir` -- see `attach_client_award_evidence_document`
 * in the backend router). This is a real native `<input type="file">`
 * wrapped in a `<label>` (the browser's own file-picker trigger -- no
 * scripted `ref.click()` proxy), just visually hidden (`sr-only`, not
 * `display:none`) so it renders as a small text link instead of the
 * default file-input chrome. Upload is synchronous and single-file, per
 * the backend route's own docstring (no OCR/extraction runs on it).
 */
export function ClientPoDocumentCell({
  evidence,
  canUpload,
  onUploaded,
}: {
  evidence: ClientAwardEvidence;
  canUpload: boolean;
  onUploaded: () => void;
}) {
  const { t } = useI18n();

  const upload = useMutation({
    mutationFn: (file: File) =>
      api.uploadFiles<ClientAwardEvidence>(
        `/client-award-evidence/${evidence.id}/document`,
        "file",
        [file],
      ),
    onSuccess: () => {
      toast.success(t("common.saved"));
      onUploaded();
    },
    onError: (e: unknown) => toast.error(errorMessage(e)),
  });

  if (evidence.document) {
    return <span className="text-xs text-muted-foreground">{evidence.document.filename}</span>;
  }

  if (!canUpload) {
    return <span className="text-xs text-muted-foreground">{t("client_po.no_document")}</span>;
  }

  return (
    <label className="inline-flex cursor-pointer items-center gap-1 text-xs text-primary hover:underline">
      <Paperclip className="size-3.5" />
      {upload.isPending ? t("common.loading") : t("client_po.upload_document")}
      <input
        type="file"
        accept="application/pdf"
        className="sr-only"
        disabled={upload.isPending}
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) upload.mutate(file);
        }}
      />
    </label>
  );
}
