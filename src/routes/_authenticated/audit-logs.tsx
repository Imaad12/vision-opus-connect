import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

import { NoAccess, PageHeader } from "@/components/app-shell";
import { useMe } from "@/hooks/use-auth";
import { db, type Row } from "@/lib/db";
import { formatDate, useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/_authenticated/audit-logs")({
  head: () => ({
    meta: [
      { title: "Audit log — VINCO ERP" },
      {
        name: "description",
        content: "Immutable trail of who created, changed, approved or deleted records across the ERP.",
      },
      { property: "og:title", content: "Audit log — VINCO ERP" },
      { property: "og:description", content: "Who changed what, and when." },
    ],
  }),
  component: AuditPage,
});

function AuditPage() {
  const { t, lang } = useI18n();
  const me = useMe();
  const allowed = me.can("admin.audit");

  const logs = useQuery({
    queryKey: ["audit-logs"],
    enabled: allowed,
    queryFn: async () => {
      const { data } = await db.from("audit_logs").select("*").order("created_at", { ascending: false }).limit(300);
      return (data ?? []) as Row[];
    },
  });

  if (!allowed) {
    return (
      <>
        <PageHeader title={t("nav.audit")} />
        <NoAccess />
      </>
    );
  }

  return (
    <>
      <PageHeader title={t("nav.audit")} />
      <div className="surface-panel overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <th className="px-3 py-2.5 text-start">{t("common.details")}</th>
              <th className="px-3 py-2.5 text-start">Actor</th>
              <th className="px-3 py-2.5 text-start">Entity</th>
              <th className="px-3 py-2.5 text-start">Date</th>
            </tr>
          </thead>
          <tbody>
            {(logs.data ?? []).length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-10 text-center text-muted-foreground">
                  {t("common.empty")}
                </td>
              </tr>
            )}
            {(logs.data ?? []).map((log) => (
              <tr key={String(log["id"])} className="border-b border-border/70 last:border-0">
                <td className="px-3 py-2.5">{String(log["summary"] ?? log["action"])}</td>
                <td className="px-3 py-2.5">{String(log["actor_name"] ?? "—")}</td>
                <td className="px-3 py-2.5 text-muted-foreground">
                  {String(log["entity_type"])}
                </td>
                <td className="px-3 py-2.5 whitespace-nowrap text-muted-foreground">
                  {formatDate(log["created_at"] as string, lang)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
