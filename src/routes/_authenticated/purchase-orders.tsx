import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Ban, CheckCircle2, ListOrdered, Package, Plus, Search, Send, X } from "lucide-react";
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

// Backed by the backend's real supplier-PO domain (`/purchase-orders`,
// `/purchase-requests`, `/purchase-orders/{id}/receipts`) -- the actual
// ERP procurement concept, not the client-award-evidence record the
// backend used to call PurchaseOrder before that was renamed to
// ClientAwardEvidence. Not built on the generic `ResourcePage`: a PO has
// its own line items (replace-all-on-save, mirroring the pattern
// `ItemsEditor` already used against Supabase) plus a submit/approve/
// receive lifecycle, the same shape as quotations.tsx.

type VendorSummary = { id: number; name: string };
type ProjectSummary = { id: number; name: string; project_code: string | null };
type PoLine = {
  id: number;
  line_no: number;
  description: string;
  unit: string | null;
  quantity: string;
  unit_price: string;
  line_total: string;
  received_quantity: string;
};
type PurchaseOrder = {
  id: number;
  po_number: string;
  vendor: VendorSummary;
  project: ProjectSummary;
  order_date: string | null;
  status: string;
  currency: string;
  vat_rate: string;
  subtotal: string;
  vat_amount: string;
  total: string;
  notes: string | null;
  lines: PoLine[];
};
type Vendor = { id: number; name: string };
type Project = { id: number; name: string; project_code: string | null };

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

export const Route = createFileRoute("/_authenticated/purchase-orders")({
  head: () => ({
    meta: [
      { title: "Purchase orders — VINCO ERP" },
      {
        name: "description",
        content: "Supplier purchase orders with line items, VAT, approval and receiving.",
      },
      { property: "og:title", content: "Purchase orders — VINCO ERP" },
      { property: "og:description", content: "Supplier orders with VAT, approval and receiving." },
    ],
  }),
  component: PurchaseOrdersPage,
});

function PurchaseOrdersPage() {
  const { t, lang } = useI18n();
  const me = useMe();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [newOpen, setNewOpen] = useState(false);
  const [linesTarget, setLinesTarget] = useState<PurchaseOrder | null>(null);
  const [receiveTarget, setReceiveTarget] = useState<PurchaseOrder | null>(null);

  const canView = me.can("purchasing.po_create");
  const canCreate = me.can("purchasing.po_create");
  const canApprove = me.can("purchasing.po_approve");
  const canReceive = me.can("purchasing.receive");

  const listQuery = useQuery({
    queryKey: ["purchase-orders"],
    enabled: canView,
    queryFn: () => api.get<PurchaseOrder[]>("/purchase-orders"),
  });

  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["purchase-orders"] });

  const transition = useMutation({
    mutationFn: (args: { id: number; action: string }) =>
      api.post(`/purchase-orders/${args.id}/${args.action}`, {}),
    onSuccess: () => {
      toast.success(t("common.saved"));
      refresh();
    },
    onError: (e: unknown) => toast.error(errorMessage(e)),
  });

  if (!canView) {
    return (
      <>
        <PageHeader title={t("nav.purchase_orders")} />
        <NoAccess />
      </>
    );
  }

  const rows = (listQuery.data ?? []).filter((po) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return [po.po_number, po.vendor.name, po.project.name].some((f) =>
      (f ?? "").toLowerCase().includes(q),
    );
  });

  return (
    <>
      <PageHeader
        title={t("nav.purchase_orders")}
        actions={
          canCreate && (
            <Button onClick={() => setNewOpen(true)} className="gap-1.5">
              <Plus className="size-4" /> {t("po.new")}
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
                <th className="px-3 py-2.5 text-start">{t("po.number")}</th>
                <th className="px-3 py-2.5 text-start">{t("po.vendor")}</th>
                <th className="px-3 py-2.5 text-start">{t("quote.project")}</th>
                <th className="px-3 py-2.5 text-start">{t("po.total")}</th>
                <th className="px-3 py-2.5 text-start">{t("po.order_date")}</th>
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
              {rows.map((po) => (
                <tr
                  key={po.id}
                  className="border-b border-border/70 last:border-0 hover:bg-muted/30"
                >
                  <td className="px-3 py-2.5">{po.po_number}</td>
                  <td className="px-3 py-2.5">{po.vendor.name}</td>
                  <td className="px-3 py-2.5">{po.project.name}</td>
                  <td className="num px-3 py-2.5">{formatMoney(Number(po.total), lang)}</td>
                  <td className="px-3 py-2.5">{formatDate(po.order_date, lang)}</td>
                  <td className="px-3 py-2.5">
                    <StatusBadge value={po.status} />
                  </td>
                  <td className="px-3 py-2 text-end whitespace-nowrap">
                    <div className="inline-flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        title={t("po.manage_lines")}
                        onClick={() => setLinesTarget(po)}
                      >
                        <ListOrdered className="size-4" />
                      </Button>
                      {po.status === "DRAFT" && canCreate && (
                        <Button
                          variant="ghost"
                          size="icon"
                          title={t("po.submit")}
                          disabled={transition.isPending}
                          onClick={() => transition.mutate({ id: po.id, action: "submit" })}
                        >
                          <Send className="size-4" />
                        </Button>
                      )}
                      {po.status === "PENDING_APPROVAL" && canApprove && (
                        <>
                          <Button
                            variant="ghost"
                            size="icon"
                            title={t("po.approve")}
                            disabled={transition.isPending}
                            onClick={() => transition.mutate({ id: po.id, action: "approve" })}
                          >
                            <CheckCircle2 className="size-4 text-[color:var(--success)]" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            title={t("po.reject")}
                            disabled={transition.isPending}
                            onClick={() => transition.mutate({ id: po.id, action: "reject" })}
                          >
                            <X className="size-4 text-destructive" />
                          </Button>
                        </>
                      )}
                      {(po.status === "APPROVED" || po.status === "PARTIALLY_RECEIVED") &&
                        canReceive && (
                          <Button
                            variant="ghost"
                            size="icon"
                            title={t("po.receive")}
                            onClick={() => setReceiveTarget(po)}
                          >
                            <Package className="size-4" />
                          </Button>
                        )}
                      {(po.status === "DRAFT" ||
                        po.status === "PENDING_APPROVAL" ||
                        po.status === "APPROVED") &&
                        canApprove && (
                          <Button
                            variant="ghost"
                            size="icon"
                            title={t("po.cancel")}
                            disabled={transition.isPending}
                            onClick={() => transition.mutate({ id: po.id, action: "cancel" })}
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

      <NewPurchaseOrderDialog open={newOpen} onOpenChange={setNewOpen} onCreated={refresh} />
      <LinesDialog
        po={linesTarget}
        onOpenChange={(o) => !o && setLinesTarget(null)}
        onSaved={refresh}
      />
      <ReceiveDialog
        po={receiveTarget}
        onOpenChange={(o) => !o && setReceiveTarget(null)}
        onReceived={refresh}
      />
    </>
  );
}

function NewPurchaseOrderDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCreated: () => void;
}) {
  const { t } = useI18n();
  const [poNumber, setPoNumber] = useState("");
  const [vendorId, setVendorId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [orderDate, setOrderDate] = useState("");
  const [vatRate, setVatRate] = useState("15");
  const [notes, setNotes] = useState("");

  const vendorsQuery = useQuery({
    queryKey: ["vendors-picker"],
    enabled: open,
    queryFn: () => api.get<Vendor[]>("/vendors"),
  });
  const projectsQuery = useQuery({
    queryKey: ["projects-picker-po"],
    enabled: open,
    queryFn: () => api.get<Project[]>("/projects"),
  });

  const reset = () => {
    setPoNumber("");
    setVendorId("");
    setProjectId("");
    setOrderDate("");
    setVatRate("15");
    setNotes("");
  };

  const create = useMutation({
    mutationFn: () =>
      api.post("/purchase-orders", {
        po_number: poNumber,
        vendor_id: Number(vendorId),
        project_id: Number(projectId),
        order_date: orderDate || null,
        vat_rate: vatRate,
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
          <DialogTitle>{t("po.new")}</DialogTitle>
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
              {t("po.number")}
            </Label>
            <Input value={poNumber} onChange={(e) => setPoNumber(e.target.value)} required />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("po.vendor")}
            </Label>
            <select
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={vendorId}
              onChange={(e) => setVendorId(e.target.value)}
              required
            >
              <option value="">{t("common.none")}</option>
              {(vendorsQuery.data ?? []).map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          </div>
          <div>
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
          <div>
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("po.order_date")}
            </Label>
            <Input type="date" value={orderDate} onChange={(e) => setOrderDate(e.target.value)} />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t("po.vat_rate")}
            </Label>
            <Input
              type="number"
              step="any"
              value={vatRate}
              onChange={(e) => setVatRate(e.target.value)}
            />
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
            <Button type="submit" disabled={create.isPending || !vendorId || !projectId}>
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

type DraftLine = { description: string; unit: string; quantity: string; unit_price: string };

function LinesDialog({
  po,
  onOpenChange,
  onSaved,
}: {
  po: PurchaseOrder | null;
  onOpenChange: (v: boolean) => void;
  onSaved: () => void;
}) {
  const { t, lang } = useI18n();
  const [drafts, setDrafts] = useState<DraftLine[] | null>(null);

  const rows: DraftLine[] =
    drafts ??
    (po?.lines ?? []).map((l) => ({
      description: l.description,
      unit: l.unit ?? "",
      quantity: l.quantity,
      unit_price: l.unit_price,
    }));

  const readOnly = po?.status !== "DRAFT";
  const subtotal = rows.reduce(
    (s, r) => s + Number(r.quantity || 0) * Number(r.unit_price || 0),
    0,
  );

  const save = useMutation({
    mutationFn: () =>
      api.put(`/purchase-orders/${po?.id}/lines`, {
        lines: rows.map((r) => ({
          description: r.description,
          unit: r.unit || null,
          quantity: r.quantity,
          unit_price: r.unit_price,
        })),
      }),
    onSuccess: () => {
      toast.success(t("common.saved"));
      setDrafts(null);
      onOpenChange(false);
      onSaved();
    },
    onError: (e: unknown) => toast.error(errorMessage(e)),
  });

  const update = (i: number, patch: Partial<DraftLine>) =>
    setDrafts(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  return (
    <Dialog
      open={po !== null}
      onOpenChange={(v) => (!v ? (setDrafts(null), onOpenChange(v)) : onOpenChange(v))}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {t("po.manage_lines")} — {po?.po_number}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-2">
          {rows.length === 0 && <p className="text-sm text-muted-foreground">{t("po.no_lines")}</p>}
          {rows.map((r, i) => (
            <div
              key={i}
              className="grid gap-2 rounded-md border border-border p-2 sm:grid-cols-[1fr_5rem_5rem_7rem_2rem]"
            >
              <Input
                value={r.description}
                disabled={readOnly}
                placeholder={t("items.description")}
                onChange={(e) => update(i, { description: e.target.value })}
              />
              <Input
                value={r.unit}
                disabled={readOnly}
                onChange={(e) => update(i, { unit: e.target.value })}
              />
              <Input
                type="number"
                step="any"
                value={r.quantity}
                disabled={readOnly}
                onChange={(e) => update(i, { quantity: e.target.value })}
              />
              <Input
                type="number"
                step="any"
                value={r.unit_price}
                disabled={readOnly}
                onChange={(e) => update(i, { unit_price: e.target.value })}
              />
              {!readOnly && (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setDrafts(rows.filter((_, idx) => idx !== i))}
                >
                  <X className="size-4 text-destructive" />
                </Button>
              )}
            </div>
          ))}
          {!readOnly && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() =>
                setDrafts([
                  ...rows,
                  { description: "", unit: "no", quantity: "1", unit_price: "0" },
                ])
              }
            >
              <Plus className="size-4" /> {t("items.add")}
            </Button>
          )}
        </div>

        <div className="mt-4 border-t border-border pt-3 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">{t("po.subtotal")}</span>
            <span className="num">{formatMoney(subtotal, lang)}</span>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.close")}
          </Button>
          {!readOnly && (
            <Button onClick={() => save.mutate()} disabled={save.isPending}>
              {t("common.save")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ReceiveDialog({
  po,
  onOpenChange,
  onReceived,
}: {
  po: PurchaseOrder | null;
  onOpenChange: (v: boolean) => void;
  onReceived: () => void;
}) {
  const { t } = useI18n();
  const [quantities, setQuantities] = useState<Record<number, string>>({});
  const [receiptDate, setReceiptDate] = useState(new Date().toISOString().slice(0, 10));

  const receive = useMutation({
    mutationFn: () =>
      api.post(`/purchase-orders/${po?.id}/receipts`, {
        receipt_date: receiptDate,
        lines: Object.entries(quantities)
          .filter(([, qty]) => Number(qty) > 0)
          .map(([lineId, qty]) => ({
            purchase_order_line_id: Number(lineId),
            quantity_received: qty,
          })),
      }),
    onSuccess: () => {
      toast.success(t("common.saved"));
      setQuantities({});
      onOpenChange(false);
      onReceived();
    },
    onError: (e: unknown) => toast.error(errorMessage(e)),
  });

  return (
    <Dialog open={po !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {t("po.receive_title")} — {po?.po_number}
          </DialogTitle>
        </DialogHeader>

        <div className="mb-3">
          <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            {t("common.status")}
          </Label>
          <Input type="date" value={receiptDate} onChange={(e) => setReceiptDate(e.target.value)} />
        </div>

        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
              <th className="px-2 py-2 text-start">{t("items.description")}</th>
              <th className="px-2 py-2 text-start">{t("items.qty")}</th>
              <th className="px-2 py-2 text-start">{t("po.remaining")}</th>
              <th className="px-2 py-2 text-start">{t("po.qty_to_receive")}</th>
            </tr>
          </thead>
          <tbody>
            {(po?.lines ?? []).map((line) => {
              const remaining = Number(line.quantity) - Number(line.received_quantity);
              return (
                <tr key={line.id} className="border-b border-border/70 last:border-0">
                  <td className="px-2 py-2">{line.description}</td>
                  <td className="num px-2 py-2">{line.quantity}</td>
                  <td className="num px-2 py-2">{remaining}</td>
                  <td className="px-2 py-2">
                    <Input
                      type="number"
                      step="any"
                      min={0}
                      max={remaining}
                      disabled={remaining <= 0}
                      value={quantities[line.id] ?? ""}
                      onChange={(e) => setQuantities({ ...quantities, [line.id]: e.target.value })}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => receive.mutate()} disabled={receive.isPending}>
            {t("po.receive")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
