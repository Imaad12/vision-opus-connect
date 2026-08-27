import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

import { NoAccess, PageHeader } from "@/components/app-shell";
import { StatusBadge } from "@/components/status-badge";
import { useMe } from "@/hooks/use-auth";
import { api } from "@/lib/api";
import { formatMoney, useI18n } from "@/lib/i18n";

// The Management layer (Milestone 3): cash flow, operating income,
// project profitability and vendor spend, all reading from
// `management_service`'s aggregation of the real Invoice/Payment/
// ActualCost/PurchaseOrder/PayrollRecord rows -- no figure here is
// computed client-side. Gated on `finance.reports`, matching every
// endpoint under `/management/*` except the dashboard headline count.

type CashFlow = { cash_in: string; cash_out: string; net_cash_flow: string };
type OperatingIncome = {
  total_actual_profit: string;
  total_payroll_paid: string;
  operating_income: string;
};
type ProjectProfitability = {
  project_id: number;
  project_name: string;
  client_name: string | null;
  status: string;
  contract_value: string | null;
  actual_cost: string | null;
  actual_profit: string | null;
  actual_margin: string | null;
  receivables_outstanding: string;
};
type VendorSpend = {
  vendor_id: number;
  vendor_name: string;
  po_committed_total: string;
  invoiced_total: string;
  paid_total: string;
  payable_outstanding: string;
};

export const Route = createFileRoute("/_authenticated/management")({
  head: () => ({
    meta: [
      { title: "Management report — VINCO ERP" },
      {
        name: "description",
        content: "Cash flow, operating income, project profitability and vendor spend.",
      },
      { property: "og:title", content: "Management report — VINCO ERP" },
      { property: "og:description", content: "Portfolio-wide financial performance." },
    ],
  }),
  component: ManagementPage,
});

function ManagementPage() {
  const { t, lang } = useI18n();
  const me = useMe();
  const allowed = me.can("finance.reports");

  const cashFlowQuery = useQuery({
    queryKey: ["mgmt-cash-flow"],
    enabled: allowed,
    queryFn: () => api.get<CashFlow>("/management/cash-flow"),
  });
  const operatingIncomeQuery = useQuery({
    queryKey: ["mgmt-operating-income"],
    enabled: allowed,
    queryFn: () => api.get<OperatingIncome>("/management/operating-income"),
  });
  const profitabilityQuery = useQuery({
    queryKey: ["mgmt-project-profitability"],
    enabled: allowed,
    queryFn: () => api.get<ProjectProfitability[]>("/management/project-profitability"),
  });
  const vendorSpendQuery = useQuery({
    queryKey: ["mgmt-vendor-spend"],
    enabled: allowed,
    queryFn: () => api.get<VendorSpend[]>("/management/vendor-spend"),
  });

  if (!allowed) {
    return (
      <>
        <PageHeader title={t("mgmt.title")} />
        <NoAccess />
      </>
    );
  }

  const cf = cashFlowQuery.data;
  const oi = operatingIncomeQuery.data;

  return (
    <>
      <PageHeader title={t("mgmt.title")} description={t("mgmt.description")} />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <div className="surface-panel p-4">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            {t("mgmt.cash_in")}
          </p>
          <p className="num mt-2 text-xl font-semibold">
            {formatMoney(Number(cf?.cash_in ?? 0), lang)}
          </p>
        </div>
        <div className="surface-panel p-4">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            {t("mgmt.cash_out")}
          </p>
          <p className="num mt-2 text-xl font-semibold">
            {formatMoney(Number(cf?.cash_out ?? 0), lang)}
          </p>
        </div>
        <div className="surface-panel p-4">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            {t("mgmt.net_cash_flow")}
          </p>
          <p className="num mt-2 text-xl font-semibold">
            {formatMoney(Number(cf?.net_cash_flow ?? 0), lang)}
          </p>
        </div>
        <div className="surface-panel p-4">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            {t("mgmt.total_payroll_paid")}
          </p>
          <p className="num mt-2 text-xl font-semibold">
            {formatMoney(Number(oi?.total_payroll_paid ?? 0), lang)}
          </p>
        </div>
        <div className="surface-panel p-4">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            {t("mgmt.operating_income")}
          </p>
          <p className="num mt-2 text-xl font-semibold">
            {formatMoney(Number(oi?.operating_income ?? 0), lang)}
          </p>
        </div>
      </div>

      <div className="surface-panel mt-4 overflow-hidden">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">{t("mgmt.project_profitability")}</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/40 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <th className="px-3 py-2.5 text-start">{t("mgmt.project")}</th>
                <th className="px-3 py-2.5 text-start">{t("mgmt.client")}</th>
                <th className="px-3 py-2.5 text-start">{t("common.status")}</th>
                <th className="px-3 py-2.5 text-start">{t("mgmt.contract_value")}</th>
                <th className="px-3 py-2.5 text-start">{t("mgmt.actual_cost")}</th>
                <th className="px-3 py-2.5 text-start">{t("mgmt.actual_profit")}</th>
                <th className="px-3 py-2.5 text-start">{t("mgmt.margin")}</th>
                <th className="px-3 py-2.5 text-start">{t("mgmt.receivables")}</th>
              </tr>
            </thead>
            <tbody>
              {(profitabilityQuery.data ?? []).length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-8 text-center text-muted-foreground">
                    {t("common.empty")}
                  </td>
                </tr>
              )}
              {(profitabilityQuery.data ?? []).map((p) => (
                <tr
                  key={p.project_id}
                  className="border-b border-border/70 last:border-0 hover:bg-muted/30"
                >
                  <td className="px-3 py-2.5">{p.project_name}</td>
                  <td className="px-3 py-2.5">{p.client_name ?? "—"}</td>
                  <td className="px-3 py-2.5">
                    <StatusBadge value={p.status} />
                  </td>
                  <td className="num px-3 py-2.5">
                    {formatMoney(Number(p.contract_value ?? 0), lang)}
                  </td>
                  <td className="num px-3 py-2.5">
                    {formatMoney(Number(p.actual_cost ?? 0), lang)}
                  </td>
                  <td className="num px-3 py-2.5">
                    {p.actual_profit != null ? formatMoney(Number(p.actual_profit), lang) : "—"}
                  </td>
                  <td className="num px-3 py-2.5">
                    {p.actual_margin != null ? `${Number(p.actual_margin).toFixed(1)}%` : "—"}
                  </td>
                  <td className="num px-3 py-2.5">
                    {formatMoney(Number(p.receivables_outstanding), lang)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="surface-panel mt-4 overflow-hidden">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">{t("mgmt.vendor_spend")}</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/40 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <th className="px-3 py-2.5 text-start">{t("mgmt.vendor")}</th>
                <th className="px-3 py-2.5 text-start">{t("mgmt.po_committed")}</th>
                <th className="px-3 py-2.5 text-start">{t("mgmt.invoiced")}</th>
                <th className="px-3 py-2.5 text-start">{t("mgmt.paid")}</th>
                <th className="px-3 py-2.5 text-start">{t("mgmt.payable_outstanding")}</th>
              </tr>
            </thead>
            <tbody>
              {(vendorSpendQuery.data ?? []).length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-8 text-center text-muted-foreground">
                    {t("common.empty")}
                  </td>
                </tr>
              )}
              {(vendorSpendQuery.data ?? []).map((v) => (
                <tr
                  key={v.vendor_id}
                  className="border-b border-border/70 last:border-0 hover:bg-muted/30"
                >
                  <td className="px-3 py-2.5">{v.vendor_name}</td>
                  <td className="num px-3 py-2.5">
                    {formatMoney(Number(v.po_committed_total), lang)}
                  </td>
                  <td className="num px-3 py-2.5">{formatMoney(Number(v.invoiced_total), lang)}</td>
                  <td className="num px-3 py-2.5">{formatMoney(Number(v.paid_total), lang)}</td>
                  <td className="num px-3 py-2.5">
                    {formatMoney(Number(v.payable_outstanding), lang)}
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
