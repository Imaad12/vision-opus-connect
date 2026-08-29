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
import { api } from "@/lib/api";
import { db, type Row } from "@/lib/db";
import { formatDate, formatMoney, useI18n } from "@/lib/i18n";

type Lead = { status: string; estimated_value: string | null };
type QuotationVersion = { status: string; quoted_value: string | null };
type Project = { status: string; contract_value: string | null };
type Invoice = {
  direction: string;
  amount: string;
  tax_amount: string | null;
  amount_paid: string;
  issued_date: string | null;
};
type PurchaseOrder = { status: string };

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
  const canSeeQuotes = me.can("quotations.view");
  const canSeeProjects = me.can("projects.view");
  const canSeeInvoices = me.can("finance.invoices") || me.can("finance.reports");
  const canSeePOs = me.can("purchasing.po_approve") || me.can("purchasing.po_create");

  const leadsQuery = useQuery({
    queryKey: ["dashboard-leads"],
    enabled: canSeeLeads,
    queryFn: () => api.get<Lead[]>("/leads"),
  });
  const quotesQuery = useQuery({
    queryKey: ["dashboard-quotes"],
    enabled: canSeeQuotes,
    queryFn: () => api.get<QuotationVersion[]>("/quotations"),
  });
  const projectsQuery = useQuery({
    queryKey: ["dashboard-projects"],
    enabled: canSeeProjects,
    queryFn: () => api.get<Project[]>("/projects"),
  });
  const invoicesQuery = useQuery({
    queryKey: ["dashboard-invoices"],
    enabled: canSeeInvoices,
    queryFn: () => api.get<Invoice[]>("/invoices"),
  });
  const posQuery = useQuery({
    queryKey: ["dashboard-pos"],
    enabled: canSeePOs,
    queryFn: () => api.get<PurchaseOrder[]>("/purchase-orders"),
  });

  const canSeeManagement = me.can("finance.reports");
  const operatingIncomeQuery = useQuery({
    queryKey: ["dashboard-operating-income"],
    enabled: canSeeManagement,
    queryFn: () => api.get<{ operating_income: string }>("/management/operating-income"),
  });
  const cashFlowQuery = useQuery({
    queryKey: ["dashboard-cash-flow"],
    enabled: canSeeManagement,
    queryFn: () => api.get<{ net_cash_flow: string }>("/management/cash-flow"),
  });

  // Every KPI below quietly falls back to 0/empty on a failed fetch (a
  // network/CORS/backend-down failure looks identical to "no data yet"
  // otherwise) -- this is the one visible signal that something is
  // actually broken, not just a company with nothing recorded yet.
  const hasFetchError =
    leadsQuery.isError ||
    quotesQuery.isError ||
    projectsQuery.isError ||
    invoicesQuery.isError ||
    posQuery.isError;

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
  const awaiting = (quotesQuery.data ?? []).filter((q) => q.status === "SUBMITTED");
  const activeProjects = (projectsQuery.data ?? []).filter(
    (p) => !["COMPLETED", "CLOSED", "CANCELLED", "LOST"].includes(p.status),
  );
  const clientInvoices = (invoicesQuery.data ?? []).filter((i) => i.direction === "CLIENT");
  const receivables = clientInvoices.reduce(
    (s, i) => s + (Number(i.amount ?? 0) - Number(i.amount_paid ?? 0)),
    0,
  );
  const vatYear = clientInvoices
    .filter((i) => (i.issued_date ?? "").startsWith(String(new Date().getFullYear())))
    .reduce((s, i) => s + Number(i.tax_amount ?? 0), 0);
  const posPending = (posQuery.data ?? []).filter((p) => p.status === "PENDING_APPROVAL");

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
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <Kpi icon={Target} label={t("dash.pipeline")} value={formatMoney(openLeadValue, lang)} />
        <Kpi
          icon={BadgeCheck}
          label={t("dash.awaiting")}
          value={String(awaiting.length)}
          hint={formatMoney(
            awaiting.reduce((s, q) => s + Number(q.quoted_value ?? 0), 0),
            lang,
          )}
        />
        <Kpi
          icon={ClipboardList}
          label={t("dash.active_projects")}
          value={String(activeProjects.length)}
          hint={formatMoney(
            activeProjects.reduce((s, p) => s + Number(p.contract_value ?? 0), 0),
            lang,
          )}
        />
        <Kpi icon={Wallet} label={t("dash.receivables")} value={formatMoney(receivables, lang)} />
        <Kpi icon={Percent} label={t("dash.vat_quarter")} value={formatMoney(vatYear, lang)} />
        <Kpi icon={ShoppingCart} label={t("dash.po_pending")} value={String(posPending.length)} />
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
