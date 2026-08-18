import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";

import { NoAccess, PageHeader } from "@/components/app-shell";
import { useMe } from "@/hooks/use-auth";
import { db, type Row } from "@/lib/db";
import { formatMoney, useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/_authenticated/vat")({
  head: () => ({
    meta: [
      { title: "VAT report — VINCO ERP" },
      {
        name: "description",
        content: "Quarterly output and input VAT summary for ZATCA filing at 15%.",
      },
      { property: "og:title", content: "VAT report — VINCO ERP" },
      { property: "og:description", content: "Output VAT, input VAT and net payable by period." },
    ],
  }),
  component: VatPage,
});

function VatPage() {
  const { t, lang } = useI18n();
  const me = useMe();
  const year = new Date().getFullYear();
  const [quarter, setQuarter] = useState(Math.floor(new Date().getMonth() / 3) + 1);
  const from = `${year}-${String((quarter - 1) * 3 + 1).padStart(2, "0")}-01`;
  const toDate = new Date(year, quarter * 3, 0).toISOString().slice(0, 10);

  const allowed = me.canAny(["finance.vat", "finance.reports"]);

  const report = useQuery({
    queryKey: ["vat", from, toDate],
    enabled: allowed,
    queryFn: async () => {
      const [inv, exp] = await Promise.all([
        db.from("invoices").select("type, subtotal, vat_amount, total, issue_date").gte("issue_date", from).lte("issue_date", toDate),
        db.from("expenses").select("amount, vat_amount, expense_date").gte("expense_date", from).lte("expense_date", toDate),
      ]);
      return { invoices: (inv.data ?? []) as Row[], expenses: (exp.data ?? []) as Row[] };
    },
  });

  if (!allowed) {
    return (
      <>
        <PageHeader title={t("vat.title")} />
        <NoAccess />
      </>
    );
  }

  const sales = (report.data?.invoices ?? []).filter((i) => i["type"] === "sales");
  const purchases = (report.data?.invoices ?? []).filter((i) => i["type"] === "purchase");
  const output = sales.reduce((s, i) => s + Number(i["vat_amount"] ?? 0), 0);
  const inputVat =
    purchases.reduce((s, i) => s + Number(i["vat_amount"] ?? 0), 0) +
    (report.data?.expenses ?? []).reduce((s, e) => s + Number(e["vat_amount"] ?? 0), 0);

  return (
    <>
      <PageHeader
        title={t("vat.title")}
        description={`${t("vat.period")}: Q${quarter} ${year}`}
        actions={
          <select
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
            value={quarter}
            onChange={(e) => setQuarter(Number(e.target.value))}
          >
            {[1, 2, 3, 4].map((q) => (
              <option key={q} value={q}>
                Q{q} {year}
              </option>
            ))}
          </select>
        }
      />
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="surface-panel p-4">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">{t("vat.output")}</p>
          <p className="num mt-2 text-2xl font-semibold">{formatMoney(output, lang)}</p>
        </div>
        <div className="surface-panel p-4">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">{t("vat.input")}</p>
          <p className="num mt-2 text-2xl font-semibold">{formatMoney(inputVat, lang)}</p>
        </div>
        <div className="surface-panel p-4">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">{t("vat.net")}</p>
          <p className="num mt-2 text-2xl font-semibold">{formatMoney(output - inputVat, lang)}</p>
        </div>
      </div>
      <p className="mt-4 text-xs text-muted-foreground">
        {sales.length} sales invoices · {purchases.length} purchase invoices ·{" "}
        {(report.data?.expenses ?? []).length} expenses
      </p>
    </>
  );
}
