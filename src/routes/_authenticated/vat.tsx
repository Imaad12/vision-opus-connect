import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";

import { NoAccess, PageHeader } from "@/components/app-shell";
import { useMe } from "@/hooks/use-auth";
import { api } from "@/lib/api";
import { formatMoney, useI18n } from "@/lib/i18n";

type InvoiceRow = { direction: string; tax_amount: string | null; issued_date: string | null };
type ExpenseRow = { tax_amount: string | null; incurred_date: string | null };

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

  // Backed by the backend's real `/invoices` (`direction`/`tax_amount`/
  // `issued_date`) and `/expenses` (`tax_amount`/`incurred_date`) --
  // Supabase's `invoices`/`expenses` tables are no longer where those
  // records are created, so this report would otherwise silently go
  // stale the moment those two pages were cut over.
  const report = useQuery({
    queryKey: ["vat", from, toDate],
    enabled: allowed,
    queryFn: async () => {
      const [invoices, expenses] = await Promise.all([
        api.get<InvoiceRow[]>("/invoices"),
        api.get<ExpenseRow[]>("/expenses"),
      ]);
      const inRange = (d: string | null) => d != null && d >= from && d <= toDate;
      return {
        invoices: invoices.filter((i) => inRange(i.issued_date)),
        expenses: expenses.filter((e) => inRange(e.incurred_date)),
      };
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

  const sales = (report.data?.invoices ?? []).filter((i) => i.direction === "CLIENT");
  const purchases = (report.data?.invoices ?? []).filter((i) => i.direction === "VENDOR");
  const output = sales.reduce((s, i) => s + Number(i.tax_amount ?? 0), 0);
  const inputVat =
    purchases.reduce((s, i) => s + Number(i.tax_amount ?? 0), 0) +
    (report.data?.expenses ?? []).reduce((s, e) => s + Number(e.tax_amount ?? 0), 0);

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
