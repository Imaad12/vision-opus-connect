import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  ArrowRight,
  BadgeCheck,
  ClipboardList,
  Percent,
  ShoppingCart,
  Target,
  Wallet,
  type LucideIcon,
} from "lucide-react";

import { PageHeader } from "@/components/app-shell";
import { StatusBadge } from "@/components/status-badge";
import { useMe } from "@/hooks/use-auth";
import { api, ApiError } from "@/lib/api";
import { db, type Row } from "@/lib/db";
import { QK_MANAGEMENT_CASH_FLOW, QK_MANAGEMENT_OPERATING_INCOME } from "@/lib/shared-query-keys";
import { formatDate, formatMoney, useI18n } from "@/lib/i18n";

type Lead = { status: string; estimated_value: string | null };

// Everything but the pipeline-by-stage chart (which still needs the raw
// `/leads` rows below) is now one call to the backend's aggregated
// `/dashboard/summary` instead of separately fetching the full
// `/quotations`, `/projects`, `/invoices`, and `/purchase-orders` lists
// just to reduce 2-5 fields per row to a single sum or count -- see
// `app/api/routers/dashboard.py` on the backend for why. A `null` field
// means the signed-in user lacks that section's permission (mirrors the
// old per-query `enabled` gates, computed server-side now instead).
type DashboardSummary = {
  pipeline_value: string | null;
  awaiting_count: number | null;
  awaiting_value: string | null;
  active_projects_count: number | null;
  active_projects_value: string | null;
  receivables: string | null;
  vat_year_to_date: string | null;
  po_pending_count: number | null;
};

export const Route = createFileRoute("/_authenticated/dashboard")({
  head: () => ({
    meta: [
      { title: "Dashboard — VINCO ERP" },
      {
        name: "description",
        content:
          "Company-wide view of pipeline value, quotation approvals, active projects, receivables and VAT for Vision Contracting Co.",
      },
      { property: "og:title", content: "Dashboard — VINCO ERP" },
      {
        property: "og:description",
        content: "Pipeline, approvals, projects, receivables and VAT at a glance.",
      },
    ],
  }),
  component: DashboardPage,
});

function Kpi({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="surface-panel p-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{label}</p>
        <Icon className="size-4 text-accent" />
      </div>
      <p className="num mt-3 text-2xl font-semibold">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function DashboardPage() {
  const { t, lang } = useI18n();
  const me = useMe();

  // Backed by the real backend now: leads/quotations/projects/invoices/
  // purchase-orders all stopped receiving new rows in Supabase once each
  // was cut over (Phase A, Milestone 1, Milestone 2) -- this dashboard
  // had been silently stale against those Supabase tables since.
  const canSeeLeads = me.can("leads.view");

  const leadsQuery = useQuery({
    queryKey: ["dashboard-leads"],
    enabled: canSeeLeads,
    queryFn: () => api.get<Lead[]>("/leads"),
  });
  const summaryQuery = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: () => api.get<DashboardSummary>("/dashboard/summary"),
  });

  const canSeeManagement = me.can("finance.reports");
  const operatingIncomeQuery = useQuery({
    queryKey: QK_MANAGEMENT_OPERATING_INCOME,
    enabled: canSeeManagement,
    queryFn: () => api.get<{ operating_income: string }>("/management/operating-income"),
  });
  const cashFlowQuery = useQuery({
    queryKey: QK_MANAGEMENT_CASH_FLOW,
    enabled: canSeeManagement,
    queryFn: () => api.get<{ net_cash_flow: string }>("/management/cash-flow"),
  });

  // Every KPI below quietly falls back to 0/empty on a failed fetch (a
  // network/CORS/backend-down failure looks identical to "no data yet"
  // otherwise) -- this is the one visible signal that something is
  // actually broken, not just a company with nothing recorded yet. All
  // four backend-routed queries are included (operatingIncome/cashFlow
  // were previously left out, so a failure there degraded silently to
  // "$0" with zero indication anything was wrong) and the first real
  // error's own status/endpoint is shown, not just a generic phrase --
  // "data may be incomplete" alone gave no way to tell a genuine outage
  // from a permissions gap or a stale desktop build pointed at the wrong
  // API URL.
  const fetchErrors = [leadsQuery, summaryQuery, operatingIncomeQuery, cashFlowQuery]
    .map((q) => q.error)
    .filter((e): e is NonNullable<typeof e> => e != null);
  const hasFetchError = fetchErrors.length > 0;
  const firstFetchError = fetchErrors[0];

  const audit = useQuery({
    queryKey: ["dashboard-audit"],
    enabled: me.can("admin.audit"),
    queryFn: async () => {
      const { data } = await db
        .from("audit_logs")
        .select("*")
        .order("created_at", { ascending: false })
        .limit(8);
      return (data ?? []) as Row[];
    },
  });

  const leads = leadsQuery.data ?? [];
  const openLeadValue = leads
    .filter((l) => !["WON", "LOST"].includes(l.status))
    .reduce((s, l) => s + Number(l.estimated_value ?? 0), 0);
  const summary = summaryQuery.data;
  const awaitingCount = summary?.awaiting_count ?? 0;
  const awaitingValue = Number(summary?.awaiting_value ?? 0);
  const activeProjectsCount = summary?.active_projects_count ?? 0;
  const activeProjectsValue = Number(summary?.active_projects_value ?? 0);
  const receivables = Number(summary?.receivables ?? 0);
  const vatYear = Number(summary?.vat_year_to_date ?? 0);
  const posPendingCount = summary?.po_pending_count ?? 0;

  const stageOrder = ["NEW", "QUALIFIED", "PROPOSAL", "NEGOTIATION", "WON", "LOST", "ON_HOLD"];
  const byStage = stageOrder
    .map((stage) => ({
      stage,
      count: leads.filter((l) => l.status === stage).length,
      value: leads
        .filter((l) => l.status === stage)
        .reduce((s, l) => s + Number(l.estimated_value ?? 0), 0),
    }))
    .filter((s) => s.count > 0);
  const maxStage = Math.max(1, ...byStage.map((s) => s.value));

  return (
    <>
      <PageHeader
        title={t("nav.dashboard")}
        description={`${t("dash.welcome")}, ${me.profile?.full_name ?? ""}`}
      />

      {hasFetchError && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {t("common.load_failed")} — {t("dash.data_may_be_incomplete")}
          {firstFetchError instanceof ApiError && (
            <div className="mt-1 font-mono text-xs opacity-80">{firstFetchError.describe()}</div>
          )}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <Kpi icon={Target} label={t("dash.pipeline")} value={formatMoney(openLeadValue, lang)} />
        <Kpi
          icon={BadgeCheck}
          label={t("dash.awaiting")}
          value={String(awaitingCount)}
          hint={formatMoney(awaitingValue, lang)}
        />
        <Kpi
          icon={ClipboardList}
          label={t("dash.active_projects")}
          value={String(activeProjectsCount)}
          hint={formatMoney(activeProjectsValue, lang)}
        />
        <Kpi icon={Wallet} label={t("dash.receivables")} value={formatMoney(receivables, lang)} />
        <Kpi icon={Percent} label={t("dash.vat_quarter")} value={formatMoney(vatYear, lang)} />
        <Kpi icon={ShoppingCart} label={t("dash.po_pending")} value={String(posPendingCount)} />
      </div>

      {canSeeManagement && (
        <div className="surface-panel mt-4 flex flex-wrap items-center justify-between gap-4 p-4">
          <div className="flex flex-wrap items-center gap-6">
            <div>
              <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                {t("dash.operating_income")}
              </p>
              <p className="num mt-1 text-xl font-semibold">
                {formatMoney(Number(operatingIncomeQuery.data?.operating_income ?? 0), lang)}
              </p>
            </div>
            <div>
              <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                {t("dash.net_cash_flow")}
              </p>
              <p className="num mt-1 text-xl font-semibold">
                {formatMoney(Number(cashFlowQuery.data?.net_cash_flow ?? 0), lang)}
              </p>
            </div>
          </div>
          <Link
            to="/management"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline"
          >
            {t("dash.view_management")} <ArrowRight className="size-4" />
          </Link>
        </div>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="surface-panel p-4">
          <h2 className="text-sm font-semibold">{t("dash.pipeline_stage")}</h2>
          <div className="mt-4 space-y-3">
            {byStage.length === 0 && (
              <p className="text-sm text-muted-foreground">{t("common.empty")}</p>
            )}
            {byStage.map((s) => (
              <div key={s.stage}>
                <div className="mb-1 flex items-center justify-between text-xs">
                  <StatusBadge value={s.stage} />
                  <span className="num text-muted-foreground">{formatMoney(s.value, lang)}</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary"
                    style={{ width: `${Math.max(4, (s.value / maxStage) * 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="surface-panel p-4">
          <h2 className="text-sm font-semibold">{t("dash.recent_activity")}</h2>
          <ul className="mt-3 divide-y divide-border text-sm">
            {(audit.data ?? []).length === 0 && (
              <li className="py-3 text-muted-foreground">{t("common.empty")}</li>
            )}
            {(audit.data ?? []).map((log) => (
              <li key={String(log["id"])} className="flex items-start justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <p className="truncate font-medium">
                    {String(log["action"])} · {String(log["entity_type"])}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {String(log["actor_name"] ?? "—")}
                  </p>
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {formatDate(log["created_at"] as string, lang)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}
