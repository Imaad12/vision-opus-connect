import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import {
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
import { db, type Row } from "@/lib/db";
import { formatDate, formatMoney, useI18n } from "@/lib/i18n";

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

  const stats = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: async () => {
      const [leads, quotes, projects, invoices, pos] = await Promise.all([
        db.from("leads").select("id, title, status, estimated_value").limit(500),
        db.from("quotations").select("id, quote_no, title, status, total, created_at").limit(500),
        db.from("projects").select("id, name, status, contract_value, progress_percent").limit(500),
        db.from("invoices").select("id, type, total, amount_paid, vat_amount, status, issue_date").limit(500),
        db.from("purchase_orders").select("id, po_no, status, total").limit(500),
      ]);
      return {
        leads: (leads.data ?? []) as Row[],
        quotes: (quotes.data ?? []) as Row[],
        projects: (projects.data ?? []) as Row[],
        invoices: (invoices.data ?? []) as Row[],
        pos: (pos.data ?? []) as Row[],
      };
    },
  });

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

  const d = stats.data;
  const openLeadValue = (d?.leads ?? [])
    .filter((l) => !["won", "lost"].includes(String(l["status"])))
    .reduce((s, l) => s + Number(l["estimated_value"] ?? 0), 0);
  const awaiting = (d?.quotes ?? []).filter((q) => q["status"] === "submitted");
  const activeProjects = (d?.projects ?? []).filter((p) => p["status"] === "active");
  const salesInvoices = (d?.invoices ?? []).filter((i) => i["type"] === "sales");
  const receivables = salesInvoices.reduce(
    (s, i) => s + (Number(i["total"] ?? 0) - Number(i["amount_paid"] ?? 0)),
    0,
  );
  const vatYear = salesInvoices
    .filter((i) => String(i["issue_date"] ?? "").startsWith(String(new Date().getFullYear())))
    .reduce((s, i) => s + Number(i["vat_amount"] ?? 0), 0);
  const posPending = (d?.pos ?? []).filter((p) => p["status"] === "pending_approval");

  const stageOrder = ["new", "qualified", "proposal", "negotiation", "won", "lost", "on_hold"];
  const byStage = stageOrder
    .map((stage) => ({
      stage,
      count: (d?.leads ?? []).filter((l) => l["status"] === stage).length,
      value: (d?.leads ?? [])
        .filter((l) => l["status"] === stage)
        .reduce((s, l) => s + Number(l["estimated_value"] ?? 0), 0),
    }))
    .filter((s) => s.count > 0);
  const maxStage = Math.max(1, ...byStage.map((s) => s.value));

  return (
    <>
      <PageHeader
        title={t("nav.dashboard")}
        description={`${t("dash.welcome")}, ${me.profile?.full_name ?? ""}`}
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <Kpi icon={Target} label={t("dash.pipeline")} value={formatMoney(openLeadValue, lang)} />
        <Kpi
          icon={BadgeCheck}
          label={t("dash.awaiting")}
          value={String(awaiting.length)}
          hint={formatMoney(
            awaiting.reduce((s, q) => s + Number(q["total"] ?? 0), 0),
            lang,
          )}
        />
        <Kpi
          icon={ClipboardList}
          label={t("dash.active_projects")}
          value={String(activeProjects.length)}
          hint={formatMoney(
            activeProjects.reduce((s, p) => s + Number(p["contract_value"] ?? 0), 0),
            lang,
          )}
        />
        <Kpi icon={Wallet} label={t("dash.receivables")} value={formatMoney(receivables, lang)} />
        <Kpi icon={Percent} label={t("dash.vat_quarter")} value={formatMoney(vatYear, lang)} />
        <Kpi icon={ShoppingCart} label={t("dash.po_pending")} value={String(posPending.length)} />
      </div>

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
