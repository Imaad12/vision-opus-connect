import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { FileText, ListOrdered, Plus, Search, Send, ShieldCheck, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { NoAccess, PageHeader } from "@/components/app-shell";
import { StatusBadge } from "@/components/status-badge";
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
import { formatDate, formatMoney, useI18n } from "@/lib/i18n";
import { QK_PROJECTS, QK_QUOTATIONS } from "@/lib/shared-query-keys";

// This page is deliberately NOT built on the generic `ResourcePage`
// (see resource-page.tsx / customers.tsx / suppliers.tsx / projects.tsx):
// the backend's real quotation domain is a `Quotation` (identity) with
// one or more immutable, priced `QuotationVersion`s, not a single flat
// row. Flattening it to fit the generic table would remove the
// versioning/award audit trail `quotation_service` exists to protect --
// see API_ARCHITECTURE.md (backend repo) section 6.1. Line items (BOQ)
// are shown read-only: they are only ever populated by the document-
// import pipeline, never authored by hand in this UI, exactly like the
// desktop application.

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
  project: ProjectSummary;
};
type QuotationVersion = {
  id: number;
  quotation_id: number;
  version_number: number;
  status: string;
  quoted_value: string | null;
  currency: string;
  issued_date: string | null;
  valid_until: string | null;
  notes: string | null;
  quotation: QuotationSummary;
};
type Project = { id: number; name: string; project_code: string | null };
type BoqLine = {
  id: number;
  line_number: string | null;
  description: string;
  unit: string | null;
  quantity: string | null;
  unit_rate: string | null;
  total: string | null;
  currency: string;
};

const CURRENCIES = ["SAR", "AED", "USD", "EUR", "GBP"];

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.describe();
  if (e instanceof Error) return e.message;
  return String(e);
}

export const Route = createFileRoute("/_authenticated/quotations")({
  head: () => ({
    meta: [
      { title: "Quotations — VINCO ERP" },
      {
        name: "description",
        content: "Priced quotation versions with submit, award and lost/withdrawn tracking.",
      },
      { property: "og:title", content: "Quotations — VINCO ERP" },
      { property: "og:description", content: "Quotation versions, status and award tracking." },
    ],
  }),
  component: QuotationsPage,
});

function QuotationsPage() {
  const { t, lang } = useI18n();
  const me = useMe();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [newOpen, setNewOpen] = useState(false);
  const [revisionTarget, setRevisionTarget] = useState<QuotationVersion | null>(null);
  const [awardTarget, setAwardTarget] = useState<QuotationVersion | null>(null);
  const [boqTarget, setBoqTarget] = useState<QuotationVersion | null>(null);

  const canView = me.can("quotations.view");
  const canCreate = me.can("quotations.create");
  const canSubmit = me.can("quotations.submit");
  const canEdit = me.can("quotations.edit");
  const canApprove = me.can("quotations.approve");

  const listQuery = useQuery({
    queryKey: QK_QUOTATIONS,
    enabled: canView,
    queryFn: () => api.get<QuotationVersion[]>("/quotations"),
  });

  const refresh = () => void queryClient.invalidateQueries({ queryKey: QK_QUOTATIONS });

  const transition = useMutation({
    mutationFn: (args: { versionId: number; action: string; body?: unknown }) =>
      api.post(`/quotation-versions/${args.versionId}/${args.action}`, args.body ?? {}),
    onSuccess: () => {
      toast.success(t("common.saved"));
      refresh();
    },
    onError: (e: unknown) => toast.error(errorMessage(e)),
  });

  if (!canView) {
    return (
      <>
        <PageHeader title={t("nav.quotations")} />
        <NoAccess />
      </>
    );
  }

  const rows = (listQuery.data ?? []).filter((v) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return [
      v.quotation.reference_number,
      v.quotation.title,
      v.quotation.project.name,
      v.quotation.project.client.name,
    ].some((f) => (f ?? "").toLowerCase().includes(q));
  });

  return (
    <>
      <PageHeader
        title={t("nav.quotations")}
        actions={
          canCreate && (
            <Button onClick={() => setNewOpen(true)} className="gap-1.5">
              <Plus className="size-4" /> {t("quote.new")}
            </Button>
          )
        }
      />

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
                <th className="px-3 py-2.5 text-start">{t("quote.reference")}</th>
                <th className="px-3 py-2.5 text-start">{t("quote.title_field")}</th>
                <th className="px-3 py-2.5 text-start">{t("quote.project")}</th>
                <th className="px-3 py-2.5 text-start">{t("quote.client")}</th>
                <th className="px-3 py-2.5 text-start">{t("quote.version")}</th>
                <th className="px-3 py-2.5 text-start">{t("quote.quoted_value")}</th>
                <th className="px-3 py-2.5 text-start">{t("quote.valid_until")}</th>
                <th className="px-3 py-2.5 text-start">{t("common.status")}</th>
                <th className="px-3 py-2.5 text-end">{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {listQuery.isLoading && (
                <tr>
                  <td colSpan={9} className="px-3 py-8 text-center text-muted-foreground">
                    {t("common.loading")}
                  </td>
                </tr>
              )}
              {!listQuery.isLoading && rows.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-3 py-10 text-center text-muted-foreground">
                    {t("common.empty")}
                  </td>
                </tr>
              )}
              {rows.map((v) => {
                const versionStatus = v.status;
                return (
                  <tr
                    key={v.id}
                    className="border-b border-border/70 last:border-0 hover:bg-muted/30"
                  >
                    <td className="px-3 py-2.5">{v.quotation.reference_number ?? "—"}</td>
                    <td className="px-3 py-2.5">{v.quotation.title ?? "—"}</td>
                    <td className="px-3 py-2.5">{v.quotation.project.name}</td>
                    <td className="px-3 py-2.5">{v.quotation.project.client.name}</td>
                    <td className="num px-3 py-2.5">v{v.version_number}</td>
                    <td className="num px-3 py-2.5">
                      {formatMoney(Number(v.quoted_value ?? 0), lang)}
                    </td>
                    <td className="px-3 py-2.5">{formatDate(v.valid_until, lang)}</td>
                    <td className="px-3 py-2.5">
                      <StatusBadge value={versionStatus} />
                    </td>
                    <td className="px-3 py-2 text-end whitespace-nowrap">
                      <div className="inline-flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          title={t("quote.view_boq")}
                          onClick={() => setBoqTarget(v)}
                        >
                          <ListOrdered className="size-4" />
                        </Button>
                        {canCreate && (
                          <Button
                            variant="ghost"
                            size="icon"
                            title={t("quote.new_revision")}
                            onClick={() => setRevisionTarget(v)}
                          >
                            <FileText className="size-4" />
                          </Button>
                        )}
                        {versionStatus === "DRAFT" && canSubmit && (
                          <Button
                            variant="ghost"
                            size="icon"
                            title={t("quote.submit")}
                            disabled={transition.isPending}
                            onClick={() => transition.mutate({ versionId: v.id, action: "submit" })}
                          >
                            <Send className="size-4" />
                          </Button>
                        )}
                        {versionStatus === "SUBMITTED" && canApprove && (
                          <Button
                            variant="ghost"
                            size="icon"
                            title={t("quote.award")}
                            onClick={() => setAwardTarget(v)}
                          >
                            <ShieldCheck className="size-4 text-[color:var(--success)]" />
                          </Button>
                        )}
                        {(versionStatus === "DRAFT" || versionStatus === "SUBMITTED") &&
                          canEdit && (
                            <Button
                              variant="ghost"
                              size="icon"
                              title={t("quote.lose")}
                              disabled={transition.isPending}
                              onClick={() => transition.mutate({ versionId: v.id, action: "lose" })}
                            >
                              <X className="size-4 text-destructive" />
                            </Button>
                          )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <NewQuotationDialog open={newOpen} onOpenChange={setNewOpen} onCreated={refresh} />
      <RevisionDialog
        version={revisionTarget}
        onOpenChange={(o) => !o && setRevisionTarget(null)}
        onCreated={refresh}
      />
      <AwardDialog
        version={awardTarget}
        onOpenChange={(o) => !o && setAwardTarget(null)}
        onAwarded={refresh}
      />
      <BoqDialog version={boqTarget} onOpenChange={(o) => !o && setBoqTarget(null)} />
    </>
  );
}

function NewQuotationDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCreated: () => void;
}) {
  const { t } = useI18n();
  const [projectId, setProjectId] = useState("");
  const [referenceNumber, setReferenceNumber] = useState("");
  const [title, setTitle] = useState("");
  const [quotedValue, setQuotedValue] = useState("");
  const [currency, setCurrency] = useState("SAR");
  const [issuedDate, setIssuedDate] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [notes, setNotes] = useState("");

  const projectsQuery = useQuery({
    queryKey: QK_PROJECTS,
    enabled: open,
    queryFn: () => api.get<Project[]>("/projects"),
  });

  const reset = () => {
    setProjectId("");
    setReferenceNumber("");
    setTitle("");
    setQuotedValue("");
    setCurrency("SAR");
    setIssuedDate("");
    setValidUntil("");
    setNotes("");
  };

  const create = useMutation({
    mutationFn: () =>
      api.post(`/projects/${projectId}/quotations`, {
        reference_number: referenceNumber || null,
        title: title || null,
        quoted_value: quotedValue || null,
        currency,
        issued_date: issuedDate || null,
        valid_until: validUntil || null,
        notes: notes || null,
      }),
    onSuccess: () => {
      toast.success(t("common.saved"));
      reset();
      onOpenChange(false);
      onCreated();
    },
    onError: (e: unknown) => toast.error(errorMessage(e)),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t("quote.new")}</DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-4 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <div className="sm:col-span-2">
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("quote.project")}
            </Label>
            <select
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              required
            >
              <option value="">{t("common.none")}</option>
              {(projectsQuery.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.project_code ? `${p.project_code} — ${p.name}` : p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="sm:col-span-2">
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("quote.title_field")}
            </Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("quote.reference")}
            </Label>
            <Input value={referenceNumber} onChange={(e) => setReferenceNumber(e.target.value)} />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("quote.quoted_value")}
            </Label>
            <Input
              type="number"
              step="any"
              value={quotedValue}
              onChange={(e) => setQuotedValue(e.target.value)}
            />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("quote.currency")}
            </Label>
            <select
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
            >
              {CURRENCIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("quote.issue_date")}
            </Label>
            <Input type="date" value={issuedDate} onChange={(e) => setIssuedDate(e.target.value)} />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("quote.valid_until")}
            </Label>
            <Input type="date" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} />
          </div>
          <div className="sm:col-span-2">
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("quote.notes")}
            </Label>
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
          </div>
          <DialogFooter className="sm:col-span-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={create.isPending || !projectId}>
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RevisionDialog({
  version,
  onOpenChange,
  onCreated,
}: {
  version: QuotationVersion | null;
  onOpenChange: (v: boolean) => void;
  onCreated: () => void;
}) {
  const { t } = useI18n();
  const [quotedValue, setQuotedValue] = useState("");
  const [currency, setCurrency] = useState("SAR");
  const [issuedDate, setIssuedDate] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [notes, setNotes] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api.post(`/quotations/${version?.quotation_id}/revisions`, {
        quoted_value: quotedValue || null,
        currency,
        issued_date: issuedDate || null,
        valid_until: validUntil || null,
        notes: notes || null,
      }),
    onSuccess: () => {
      toast.success(t("common.saved"));
      onOpenChange(false);
      onCreated();
    },
    onError: (e: unknown) => toast.error(errorMessage(e)),
  });

  return (
    <Dialog open={version !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("quote.new_revision")}</DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-4 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <div>
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("quote.quoted_value")}
            </Label>
            <Input
              type="number"
              step="any"
              value={quotedValue}
              onChange={(e) => setQuotedValue(e.target.value)}
            />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("quote.currency")}
            </Label>
            <select
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
            >
              {CURRENCIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("quote.issue_date")}
            </Label>
            <Input type="date" value={issuedDate} onChange={(e) => setIssuedDate(e.target.value)} />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("quote.valid_until")}
            </Label>
            <Input type="date" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} />
          </div>
          <div className="sm:col-span-2">
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("quote.notes")}
            </Label>
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
          </div>
          <DialogFooter className="sm:col-span-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AwardDialog({
  version,
  onOpenChange,
  onAwarded,
}: {
  version: QuotationVersion | null;
  onOpenChange: (v: boolean) => void;
  onAwarded: () => void;
}) {
  const { t } = useI18n();
  const [contractValue, setContractValue] = useState("");

  const award = useMutation({
    mutationFn: () =>
      api.post(`/quotation-versions/${version?.id}/award`, { contract_value: contractValue }),
    onSuccess: () => {
      toast.success(t("doc.approved"));
      setContractValue("");
      onOpenChange(false);
      onAwarded();
    },
    onError: (e: unknown) => toast.error(errorMessage(e)),
  });

  return (
    <Dialog open={version !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t("quote.confirm_award")}</DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            award.mutate();
          }}
        >
          <div>
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("quote.contract_value")}
            </Label>
            <Input
              type="number"
              step="any"
              min={0}
              value={contractValue}
              onChange={(e) => setContractValue(e.target.value)}
              required
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={award.isPending}>
              {t("quote.award")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function BoqDialog({
  version,
  onOpenChange,
}: {
  version: QuotationVersion | null;
  onOpenChange: (v: boolean) => void;
}) {
  const { t, lang } = useI18n();

  const boqQuery = useQuery({
    queryKey: ["boq-lines", version?.id],
    enabled: version !== null,
    queryFn: () => api.get<BoqLine[]>(`/quotation-versions/${version?.id}/boq-lines`),
  });

  return (
    <Dialog open={version !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("quote.boq_title")}</DialogTitle>
        </DialogHeader>
        {(boqQuery.data ?? []).length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">{t("quote.no_boq")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
                <th className="px-2 py-2 text-start">{t("items.description")}</th>
                <th className="px-2 py-2 text-start">{t("items.unit")}</th>
                <th className="px-2 py-2 text-start">{t("items.qty")}</th>
                <th className="px-2 py-2 text-start">{t("items.price")}</th>
                <th className="px-2 py-2 text-start">{t("items.line_total")}</th>
              </tr>
            </thead>
            <tbody>
              {(boqQuery.data ?? []).map((line) => (
                <tr key={line.id} className="border-b border-border/70 last:border-0">
                  <td className="px-2 py-2">{line.description}</td>
                  <td className="px-2 py-2">{line.unit ?? "—"}</td>
                  <td className="num px-2 py-2">{line.quantity ?? "—"}</td>
                  <td className="num px-2 py-2">
                    {formatMoney(Number(line.unit_rate ?? 0), lang)}
                  </td>
                  <td className="num px-2 py-2">{formatMoney(Number(line.total ?? 0), lang)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
