import { useMutation } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Ban, Send } from "lucide-react";
import { toast } from "sonner";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";
import { Button } from "@/components/ui/button";
import { useMe } from "@/hooks/use-auth";
import { ApiError, api } from "@/lib/api";
import { type Row } from "@/lib/db";
import { useI18n } from "@/lib/i18n";

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.describe();
  if (e instanceof Error) return e.message;
  return String(e);
}

function InvoiceLifecycleActions({ row, refresh }: { row: Row; refresh: () => void }) {
  const { t } = useI18n();
  const me = useMe();
  const canEdit = me.canAny(["finance.invoices"]);
  const status = String(row["status"] ?? "");

  const transition = useMutation({
    mutationFn: (action: string) => api.post(`/invoices/${String(row["id"])}/${action}`, {}),
    onSuccess: () => {
      toast.success(t("common.saved"));
      refresh();
    },
    onError: (e: unknown) => toast.error(errorMessage(e)),
  });

  if (!canEdit) return null;

  return (
    <>
      {status === "DRAFT" && (
        <Button
          variant="ghost"
          size="icon"
          title={t("invoice.issue")}
          disabled={transition.isPending}
          onClick={() => transition.mutate("issue")}
        >
          <Send className="size-4" />
        </Button>
      )}
      {(status === "DRAFT" || status === "ISSUED") && (
        <Button
          variant="ghost"
          size="icon"
          title={t("invoice.cancel")}
          disabled={transition.isPending}
          onClick={() => transition.mutate("cancel")}
        >
          <Ban className="size-4 text-destructive" />
        </Button>
      )}
    </>
  );
}

// Backed by the backend's real `Invoice` model (`/invoices`), not
// Supabase's `invoices` table. Permission is `finance.invoices` -- the
// frontend's real `app_permission` enum has no finer view/create/edit
// split for finance, unlike customers/vendors.
//
// `direction` (CLIENT/VENDOR) replaces the old `type` (sales/purchase)
// field name -- same concept, the backend's real vocabulary. There is no
// backend line-item sub-resource for invoices (`Invoice.amount` is a
// single total, like a quotation's awarded value) -- the previous
// `invoice_items` `ItemsButton` had no backend equivalent and is
// dropped rather than wired to nothing. `amount_paid` is a computed,
// read-only field the API returns alongside the invoice.
const config: ResourceConfig = {
  table: "invoices",
  title: { en: "Invoices", ar: "الفواتير" },
  description: {
    en: "Client and vendor invoices with VAT, retention and collection status.",
    ar: "فواتير العملاء والموردين مع الضريبة والمحتجز وحالة التحصيل.",
  },
  perms: {
    view: ["finance.invoices"],
    create: ["finance.invoices"],
    edit: ["finance.invoices"],
  },
  backend: { basePath: "/invoices" },
  columns: [
    { key: "invoice_number", label: { en: "No.", ar: "الرقم" } },
    { key: "direction", label: { en: "Direction", ar: "الاتجاه" }, kind: "status" },
    { key: "project_id", label: { en: "Project", ar: "المشروع" }, kind: "ref" },
    { key: "amount", label: { en: "Amount", ar: "المبلغ" }, kind: "money" },
    { key: "amount_paid", label: { en: "Paid", ar: "المسدد" }, kind: "money" },
    { key: "due_date", label: { en: "Due", ar: "الاستحقاق" }, kind: "date" },
    { key: "status", label: { en: "Status", ar: "الحالة" }, kind: "status" },
  ],
  fields: [
    {
      key: "direction",
      label: { en: "Direction", ar: "الاتجاه" },
      kind: "select",
      defaultValue: "CLIENT",
      half: true,
      options: [
        { value: "CLIENT", label: { en: "Client (AR)", ar: "عميل (مدين)" } },
        { value: "VENDOR", label: { en: "Vendor (AP)", ar: "مورد (دائن)" } },
      ],
    },
    {
      key: "invoice_number",
      label: { en: "Invoice no.", ar: "رقم الفاتورة" },
      kind: "text",
      half: true,
    },
    {
      key: "project_id",
      label: { en: "Project", ar: "المشروع" },
      kind: "ref",
      ref: { table: "projects", labelCol: "name", backendPath: "/projects" },
      required: true,
      half: true,
    },
    {
      key: "client_id",
      label: { en: "Customer", ar: "العميل" },
      kind: "ref",
      ref: { table: "clients", labelCol: "name", backendPath: "/clients" },
      half: true,
    },
    {
      key: "vendor_id",
      label: { en: "Vendor", ar: "المورد" },
      kind: "ref",
      ref: { table: "vendors", labelCol: "name", backendPath: "/vendors" },
      half: true,
    },
    {
      key: "issued_date",
      label: { en: "Issue date", ar: "تاريخ الإصدار" },
      kind: "date",
      half: true,
    },
    { key: "due_date", label: { en: "Due date", ar: "تاريخ الاستحقاق" }, kind: "date", half: true },
    {
      key: "amount",
      label: { en: "Amount", ar: "المبلغ" },
      kind: "number",
      defaultValue: 0,
      half: true,
    },
    {
      key: "tax_amount",
      label: { en: "Tax amount", ar: "قيمة الضريبة" },
      kind: "number",
      half: true,
    },
    {
      key: "retention_amount",
      label: { en: "Retention amount", ar: "قيمة المحتجز" },
      kind: "number",
      half: true,
    },
    { key: "notes", label: { en: "Notes", ar: "ملاحظات" }, kind: "textarea" },
  ],
  searchKeys: ["invoice_number", "notes"],
  extraRowActions: (row, refresh) => <InvoiceLifecycleActions row={row} refresh={refresh} />,
};

export const Route = createFileRoute("/_authenticated/invoices")({
  head: () => ({
    meta: [
      { title: "Invoices — VINCO ERP" },
      {
        name: "description",
        content:
          "Issue and track sales and purchase invoices with 15% VAT, due dates and payment status.",
      },
      { property: "og:title", content: "Invoices — VINCO ERP" },
      { property: "og:description", content: "VAT invoices with collection tracking." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
