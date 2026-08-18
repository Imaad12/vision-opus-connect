import { createFileRoute } from "@tanstack/react-router";

import { NoAccess, PageHeader } from "@/components/app-shell";
import { useMe } from "@/hooks/use-auth";
import { useI18n } from "@/lib/i18n";

export const Route = createFileRoute("/_authenticated/settings")({
  head: () => ({
    meta: [
      { title: "Company settings — VINCO ERP" },
      {
        name: "description",
        content: "Company identity, VAT rate and document numbering conventions used across VINCO ERP.",
      },
      { property: "og:title", content: "Company settings — VINCO ERP" },
      { property: "og:description", content: "Company identity, VAT rate and numbering." },
    ],
  }),
  component: SettingsPage,
});

function SettingsPage() {
  const { t } = useI18n();
  const me = useMe();

  if (!me.can("admin.settings")) {
    return (
      <>
        <PageHeader title={t("nav.settings")} />
        <NoAccess />
      </>
    );
  }

  const rows = [
    { label: "Company", value: "Vision Contracting Co. · شركة الرؤية للمقاولات" },
    { label: "Country", value: "Kingdom of Saudi Arabia" },
    { label: "Currency", value: "SAR (﷼)" },
    { label: "Standard VAT rate", value: "15%" },
    { label: "Quotation numbering", value: "QT-YYYY-#####" },
    { label: "Purchase order numbering", value: "PO-YYYY-#####" },
    { label: "Invoice numbering", value: "INV-YYYY-#####" },
    { label: "Approval rule", value: "Separation of duties enforced in the database" },
  ];

  return (
    <>
      <PageHeader title={t("nav.settings")} />
      <div className="surface-panel divide-y divide-border">
        {rows.map((r) => (
          <div key={r.label} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
            <span className="text-muted-foreground">{r.label}</span>
            <span className="font-medium">{r.value}</span>
          </div>
        ))}
      </div>
    </>
  );
}
