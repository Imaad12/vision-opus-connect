import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Check, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { NoAccess, PageHeader } from "@/components/app-shell";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useMe } from "@/hooks/use-auth";
import { ApiError, api } from "@/lib/api";
import { formatMoney, useI18n } from "@/lib/i18n";
import { QK_PURCHASE_ORDERS, QK_QUOTATIONS } from "@/lib/shared-query-keys";

// Rebuilt against the real backend: the previous version read Supabase's
// `quotations`/`purchase_orders`/`expenses` tables directly, all three of
// which stopped receiving new rows once those pages were cut over to the
// FastAPI backend (Phase A, Milestone 1, Milestone 2 respectively) --
// this queue had been silently empty since. There is deliberately no
// Expenses section: `ActualCost`/`cost_service` has no submit/approve
// lifecycle (only a plain `payment_status`), so the "approved by a second
// person" expense workflow the old UI implied does not exist server-side
// yet -- a real gap, called out here rather than wired to nothing.

type QuotationVersion = {
  id: number;
  status: string;
  quoted_value: string | null;
  currency: string;
  quotation: { reference_number: string | null; title: string | null; project: { name: string } };
};

type PurchaseOrder = {
  id: number;
  po_number: string;
  status: string;
  total: string;
  vendor: { name: string };
  project: { name: string };
};

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

export const Route = createFileRoute("/_authenticated/approvals")({
  head: () => ({
    meta: [
      { title: "Approvals — VINCO ERP" },
      {
        name: "description",
        content: "One queue for quotations and purchase orders awaiting an independent approver.",
      },
      { property: "og:title", content: "Approvals — VINCO ERP" },
      { property: "og:description", content: "Pending quotations and purchase orders." },
    ],
  }),
  component: ApprovalsPage,
});

function ApprovalsPage() {
  const { t, lang } = useI18n();
  const me = useMe();
  const queryClient = useQueryClient();
  const [awardTarget, setAwardTarget] = useState<number | null>(null);
  const [contractValue, setContractValue] = useState("");

  const canApproveQuotes = me.can("quotations.approve");
  const canRejectQuotes = me.can("quotations.edit");
  const canApprovePOs = me.can("purchasing.po_approve");

  const refresh = (key: string) => void queryClient.invalidateQueries({ queryKey: [key] });

  const quotationsQuery = useQuery({
    queryKey: QK_QUOTATIONS,
    enabled: canApproveQuotes || canRejectQuotes,
    queryFn: () => api.get<QuotationVersion[]>("/quotations"),
  });

  const poQuery = useQuery({
    queryKey: QK_PURCHASE_ORDERS,
    enabled: canApprovePOs,
    queryFn: () => api.get<PurchaseOrder[]>("/purchase-orders"),
  });

  const award = useMutation({
    mutationFn: (args: { id: number; contract_value: string }) =>
      api.post(`/quotation-versions/${args.id}/award`, { contract_value: args.contract_value }),
    onSuccess: () => {
      toast.success(t("common.saved"));
      setAwardTarget(null);
      setContractValue("");
      refresh(QK_QUOTATIONS[0]);
    },
    onError: (e: unknown) => toast.error(errorMessage(e)),
  });

  const lose = useMutation({
    mutationFn: (id: number) => api.post(`/quotation-versions/${id}/lose`, {}),
    onSuccess: () => {
      toast.success(t("common.saved"));
      refresh(QK_QUOTATIONS[0]);
    },
    onError: (e: unknown) => toast.error(errorMessage(e)),
  });

  const poTransition = useMutation({
    mutationFn: (args: { id: number; action: "approve" | "reject" }) =>
      api.post(`/purchase-orders/${args.id}/${args.action}`, {}),
    onSuccess: () => {
      toast.success(t("common.saved"));
      refresh(QK_PURCHASE_ORDERS[0]);
    },
    onError: (e: unknown) => toast.error(errorMessage(e)),
  });

  if (!canApproveQuotes && !canRejectQuotes && !canApprovePOs) {
    return (
      <>
        <PageHeader title={t("nav.approvals")} />
        <NoAccess />
      </>
    );
  }

  const pendingQuotations = (quotationsQuery.data ?? []).filter((v) => v.status === "SUBMITTED");
  const pendingPOs = (poQuery.data ?? []).filter((po) => po.status === "PENDING_APPROVAL");

  return (
    <>
      <PageHeader title={t("nav.approvals")} description={t("common.sod")} />
      <div className="space-y-4">
        {(canApproveQuotes || canRejectQuotes) && (
          <div className="surface-panel overflow-hidden">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <h2 className="text-sm font-semibold">{t("nav.quotations")}</h2>
              <span className="num text-xs text-muted-foreground">{pendingQuotations.length}</span>
            </div>
            {pendingQuotations.length === 0 ? (
              <p className="px-4 py-6 text-sm text-muted-foreground">{t("common.empty")}</p>
            ) : (
              <ul className="divide-y divide-border">
                {pendingQuotations.map((v) => (
                  <li
                    key={v.id}
                    className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        {v.quotation.reference_number ?? "—"} ·{" "}
                        {v.quotation.title ?? v.quotation.project.name}
                      </p>
                      <p className="num text-xs text-muted-foreground">
                        {formatMoney(Number(v.quoted_value ?? 0), lang)}
                      </p>
                    </div>
                    <div className="flex items-center gap-1">
                      <StatusBadge value={v.status} />
                      {awardTarget === v.id ? (
                        <div className="flex items-center gap-1">
                          <Input
                            type="number"
                            step="any"
                            className="h-8 w-32"
                            placeholder={t("quote.contract_value")}
                            value={contractValue}
                            onChange={(e) => setContractValue(e.target.value)}
                          />
                          <Button
                            size="sm"
                            disabled={award.isPending || !contractValue}
                            onClick={() =>
                              award.mutate({ id: v.id, contract_value: contractValue })
                            }
                          >
                            {t("quote.award")}
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => setAwardTarget(null)}>
                            {t("common.cancel")}
                          </Button>
                        </div>
                      ) : (
                        <>
                          {canApproveQuotes && (
                            <Button
                              variant="ghost"
                              size="icon"
                              title={t("quote.award")}
                              onClick={() => {
                                setAwardTarget(v.id);
                                setContractValue(v.quoted_value ?? "");
                              }}
                            >
                              <Check className="size-4 text-[color:var(--success)]" />
                            </Button>
                          )}
                          {canRejectQuotes && (
                            <Button
                              variant="ghost"
                              size="icon"
                              title={t("quote.lose")}
                              disabled={lose.isPending}
                              onClick={() => lose.mutate(v.id)}
                            >
                              <X className="size-4 text-destructive" />
                            </Button>
                          )}
                        </>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {canApprovePOs && (
          <div className="surface-panel overflow-hidden">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <h2 className="text-sm font-semibold">{t("nav.purchase_orders")}</h2>
              <span className="num text-xs text-muted-foreground">{pendingPOs.length}</span>
            </div>
            {pendingPOs.length === 0 ? (
              <p className="px-4 py-6 text-sm text-muted-foreground">{t("common.empty")}</p>
            ) : (
              <ul className="divide-y divide-border">
                {pendingPOs.map((po) => (
                  <li
                    key={po.id}
                    className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        {po.po_number} · {po.vendor.name} — {po.project.name}
                      </p>
                      <p className="num text-xs text-muted-foreground">
                        {formatMoney(Number(po.total), lang)}
                      </p>
                    </div>
                    <div className="flex items-center gap-1">
                      <StatusBadge value={po.status} />
                      <Button
                        variant="ghost"
                        size="icon"
                        title={t("po.approve")}
                        disabled={poTransition.isPending}
                        onClick={() => poTransition.mutate({ id: po.id, action: "approve" })}
                      >
                        <Check className="size-4 text-[color:var(--success)]" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        title={t("po.reject")}
                        disabled={poTransition.isPending}
                        onClick={() => poTransition.mutate({ id: po.id, action: "reject" })}
                      >
                        <X className="size-4 text-destructive" />
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </>
  );
}
