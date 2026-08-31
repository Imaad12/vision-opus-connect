import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Ban, CheckCircle2, Play, Plus, Search } from "lucide-react";
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
import { QK_PROJECTS } from "@/lib/shared-query-keys";

// Backed by the backend's own Contract domain (`/contracts`), created
// only from an already-AWARDED project (see the backend's
// contract_service.create_contract). Not built on the generic
// `ResourcePage`: creation is nested under a project
// (`POST /projects/{id}/contracts`) and "editing" is a set of lifecycle
// transitions (activate/complete/terminate), not a free-form field edit
// -- see API_ARCHITECTURE.md. There is deliberately no amendment/
// versioning here; a post-signing value change is a project variation,
// not a contract edit.

type ClientSummary = { id: number; name: string };
type ProjectSummary = {
  id: number;
  name: string;
  project_code: string | null;
  client: ClientSummary;
};
type Contract = {
  id: number;
  project_id: number;
  project: ProjectSummary;
  contract_number: string | null;
  value: string;
  currency: string;
  status: string;
  signed_date: string | null;
  start_date: string | null;
  end_date: string | null;
  notes: string | null;
};
type Project = { id: number; name: string; project_code: string | null; status: string };

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

export const Route = createFileRoute("/_authenticated/contracts")({
  head: () => ({
    meta: [
      { title: "Contracts — VINCO ERP" },
      {
        name: "description",
        content: "Signed customer contracts created from awarded quotations.",
      },
      { property: "og:title", content: "Contracts — VINCO ERP" },
      { property: "og:description", content: "Contracts and their lifecycle." },
    ],
  }),
  component: ContractsPage,
});

function ContractsPage() {
  const { t, lang } = useI18n();
  const me = useMe();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [newOpen, setNewOpen] = useState(false);

  const canView = me.can("contracts.view");
  const canCreate = me.can("contracts.create");
  const canEdit = me.can("contracts.edit");

  const listQuery = useQuery({
    queryKey: ["contracts"],
    enabled: canView,
    queryFn: () => api.get<Contract[]>("/contracts"),
  });

  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["contracts"] });

  const transition = useMutation({
    mutationFn: (args: { contractId: number; action: string }) =>
      api.post(`/contracts/${args.contractId}/${args.action}`, {}),
    onSuccess: () => {
      toast.success(t("common.saved"));
      refresh();
    },
    onError: (e: unknown) => toast.error(errorMessage(e)),
  });

  if (!canView) {
    return (
      <>
        <PageHeader title={t("nav.contracts")} />
        <NoAccess />
      </>
    );
  }

  const rows = (listQuery.data ?? []).filter((c) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return [c.contract_number, c.project.name, c.project.client.name].some((f) =>
      (f ?? "").toLowerCase().includes(q),
    );
  });

  return (
    <>
      <PageHeader
        title={t("nav.contracts")}
        actions={
          canCreate && (
            <Button onClick={() => setNewOpen(true)} className="gap-1.5">
              <Plus className="size-4" /> {t("quote.create_contract")}
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
                <th className="px-3 py-2.5 text-start">{t("contract.number")}</th>
                <th className="px-3 py-2.5 text-start">{t("quote.project")}</th>
                <th className="px-3 py-2.5 text-start">{t("quote.client")}</th>
                <th className="px-3 py-2.5 text-start">{t("common.total")}</th>
                <th className="px-3 py-2.5 text-start">{t("contract.signed_date")}</th>
                <th className="px-3 py-2.5 text-start">{t("common.status")}</th>
                <th className="px-3 py-2.5 text-end">{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {listQuery.isLoading && (
                <tr>
                  <td colSpan={7} className="px-3 py-8 text-center text-muted-foreground">
                    {t("common.loading")}
                  </td>
                </tr>
              )}
              {!listQuery.isLoading && rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-10 text-center text-muted-foreground">
                    {t("common.empty")}
                  </td>
                </tr>
              )}
              {rows.map((c) => (
                <tr
                  key={c.id}
                  className="border-b border-border/70 last:border-0 hover:bg-muted/30"
                >
                  <td className="px-3 py-2.5">{c.contract_number ?? "—"}</td>
                  <td className="px-3 py-2.5">{c.project.name}</td>
                  <td className="px-3 py-2.5">{c.project.client.name}</td>
                  <td className="num px-3 py-2.5">{formatMoney(Number(c.value), lang)}</td>
                  <td className="px-3 py-2.5">{formatDate(c.signed_date, lang)}</td>
                  <td className="px-3 py-2.5">
                    <StatusBadge value={c.status} />
                  </td>
                  <td className="px-3 py-2 text-end whitespace-nowrap">
                    <div className="inline-flex items-center gap-1">
                      {c.status === "DRAFT" && canEdit && (
                        <Button
                          variant="ghost"
                          size="icon"
                          title={t("contract.activate")}
                          disabled={transition.isPending}
                          onClick={() =>
                            transition.mutate({ contractId: c.id, action: "activate" })
                          }
                        >
                          <Play className="size-4 text-[color:var(--success)]" />
                        </Button>
                      )}
                      {c.status === "ACTIVE" && canEdit && (
                        <Button
                          variant="ghost"
                          size="icon"
                          title={t("contract.complete")}
                          disabled={transition.isPending}
                          onClick={() =>
                            transition.mutate({ contractId: c.id, action: "complete" })
                          }
                        >
                          <CheckCircle2 className="size-4 text-[color:var(--success)]" />
                        </Button>
                      )}
                      {(c.status === "DRAFT" || c.status === "ACTIVE") && canEdit && (
                        <Button
                          variant="ghost"
                          size="icon"
                          title={t("contract.terminate")}
                          disabled={transition.isPending}
                          onClick={() =>
                            transition.mutate({ contractId: c.id, action: "terminate" })
                          }
                        >
                          <Ban className="size-4 text-destructive" />
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <NewContractDialog open={newOpen} onOpenChange={setNewOpen} onCreated={refresh} />
    </>
  );
}

function NewContractDialog({
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
  const [contractNumber, setContractNumber] = useState("");
  const [signedDate, setSignedDate] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [notes, setNotes] = useState("");

  const projectsQuery = useQuery({
    queryKey: QK_PROJECTS,
    enabled: open,
    queryFn: () => api.get<Project[]>("/projects"),
  });

  const reset = () => {
    setProjectId("");
    setContractNumber("");
    setSignedDate("");
    setStartDate("");
    setEndDate("");
    setNotes("");
  };

  const create = useMutation({
    mutationFn: () =>
      api.post(`/projects/${projectId}/contracts`, {
        contract_number: contractNumber || null,
        signed_date: signedDate || null,
        start_date: startDate || null,
        end_date: endDate || null,
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

  const awardedProjects = (projectsQuery.data ?? []).filter((p) => p.status === "AWARDED");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("quote.create_contract")}</DialogTitle>
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
              {awardedProjects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.project_code ? `${p.project_code} — ${p.name}` : p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="sm:col-span-2">
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("contract.number")}
            </Label>
            <Input value={contractNumber} onChange={(e) => setContractNumber(e.target.value)} />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("contract.signed_date")}
            </Label>
            <Input type="date" value={signedDate} onChange={(e) => setSignedDate(e.target.value)} />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("common.start_date")}
            </Label>
            <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("common.end_date")}
            </Label>
            <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
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
