import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

import { PageHeader } from "@/components/app-shell";
import { ApprovalActions } from "@/components/doc-actions";
import { StatusBadge } from "@/components/status-badge";
import { db, type Row } from "@/lib/db";
import { formatMoney, useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/_authenticated/approvals")({
  head: () => ({
    meta: [
      { title: "Approvals — VINCO ERP" },
      {
        name: "description",
        content: "One queue for quotations, purchase orders and expenses awaiting an independent approver.",
      },
      { property: "og:title", content: "Approvals — VINCO ERP" },
      { property: "og:description", content: "Pending quotations, purchase orders and expenses." },
    ],
  }),
  component: ApprovalsPage,
});

function ApprovalsPage() {
  const { t, lang } = useI18n();
  const queue = useQuery({
    queryKey: ["approvals"],
    queryFn: async () => {
      const [q, p, e] = await Promise.all([
        db.from("quotations").select("*").eq("status", "submitted"),
        db.from("purchase_orders").select("*").eq("status", "pending_approval"),
        db.from("expenses").select("*").eq("status", "pending"),
      ]);
      return {
        quotations: (q.data ?? []) as Row[],
        purchase_orders: (p.data ?? []) as Row[],
        expenses: (e.data ?? []) as Row[],
      };
    },
  });

  const sections = [
    { table: "quotations", label: t("nav.quotations"), rows: queue.data?.quotations ?? [], noKey: "quote_no", perms: ["quotations.approve"] },
    { table: "purchase_orders", label: t("nav.purchase_orders"), rows: queue.data?.purchase_orders ?? [], noKey: "po_no", perms: ["po.approve"] },
    { table: "expenses", label: t("nav.expenses"), rows: queue.data?.expenses ?? [], noKey: "expense_no", perms: ["expenses.approve"] },
  ];

  return (
    <>
      <PageHeader title={t("nav.approvals")} description={t("common.sod")} />
      <div className="space-y-4">
        {sections.map((s) => (
          <div key={s.table} className="surface-panel overflow-hidden">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <h2 className="text-sm font-semibold">{s.label}</h2>
              <span className="num text-xs text-muted-foreground">{s.rows.length}</span>
            </div>
            {s.rows.length === 0 ? (
              <p className="px-4 py-6 text-sm text-muted-foreground">{t("common.empty")}</p>
            ) : (
              <ul className="divide-y divide-border">
                {s.rows.map((row) => (
                  <li key={String(row["id"])} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        {String(row[s.noKey] ?? "—")} · {String(row["title"] ?? row["description"] ?? "")}
                      </p>
                      <p className="num text-xs text-muted-foreground">
                        {formatMoney(Number(row["total"] ?? row["amount"] ?? 0), lang)}
                      </p>
                    </div>
                    <div className="flex items-center gap-1">
                      <StatusBadge value={String(row["status"])} />
                      <ApprovalActions
                        row={row}
                        table={s.table}
                        submitPerms={[]}
                        approvePerms={s.perms}
                        refresh={() => void queue.refetch()}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
