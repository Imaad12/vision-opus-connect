import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

// Backed by the backend's real `Payment` model (`/payments`), not
// Supabase's `payments` table. Permission is `finance.payments`, copied
// verbatim from the real `app_permission` enum (the previous
// `payments.view/create/edit/delete` matched no real permission).
// `payment_date` -> `paid_date`, method values are the backend's real
// uppercase vocabulary. `approved_by` has no backend equivalent (`Payment`
// has no such column) and is dropped rather than silently discarded on
// save -- see projects.tsx for the same documented-omission pattern.
// There is deliberately no edit/remove: a recorded payment is a financial
// event, not an editable draft (see `payment_service.create_payment` --
// it recomputes the parent invoice's status the moment it's created).
const config: ResourceConfig = {
  table: "payments",
  title: { en: "Payments", ar: "المدفوعات" },
  description: {
    en: "Receipts and disbursements against invoices.",
    ar: "المقبوضات والمدفوعات مقابل الفواتير.",
  },
  perms: {
    view: ["finance.payments"],
    create: ["finance.payments"],
  },
  backend: { basePath: "/payments" },
  columns: [
    { key: "invoice_id", label: { en: "Invoice", ar: "الفاتورة" }, kind: "ref" },
    { key: "amount", label: { en: "Amount", ar: "المبلغ" }, kind: "money" },
    { key: "paid_date", label: { en: "Date", ar: "التاريخ" }, kind: "date" },
    { key: "method", label: { en: "Method", ar: "الطريقة" } },
    { key: "reference", label: { en: "Reference", ar: "المرجع" } },
    {
      key: "is_retention_release",
      label: { en: "Retention release", ar: "تحرير محتجز" },
      kind: "bool",
    },
  ],
  fields: [
    {
      key: "invoice_id",
      label: { en: "Invoice", ar: "الفاتورة" },
      kind: "ref",
      ref: { table: "invoices", labelCol: "invoice_number", backendPath: "/invoices" },
      required: true,
      half: true,
    },
    {
      key: "amount",
      label: { en: "Amount", ar: "المبلغ" },
      kind: "number",
      defaultValue: 0,
      half: true,
    },
    {
      key: "paid_date",
      label: { en: "Payment date", ar: "تاريخ الدفع" },
      kind: "date",
      half: true,
    },
    {
      key: "method",
      label: { en: "Method", ar: "طريقة الدفع" },
      kind: "select",
      defaultValue: "BANK_TRANSFER",
      half: true,
      options: [
        { value: "BANK_TRANSFER", label: { en: "Bank transfer", ar: "حوالة بنكية" } },
        { value: "CHEQUE", label: { en: "Cheque", ar: "شيك" } },
        { value: "CASH", label: { en: "Cash", ar: "نقدي" } },
        { value: "CARD", label: { en: "Card", ar: "بطاقة" } },
        { value: "OTHER", label: { en: "Other", ar: "أخرى" } },
      ],
    },
    {
      key: "reference",
      label: { en: "Reference / transaction no.", ar: "المرجع / رقم العملية" },
      kind: "text",
    },
    {
      key: "is_retention_release",
      label: { en: "This releases withheld retention", ar: "هذا تحرير لمحتجز سابق" },
      kind: "bool",
    },
    { key: "notes", label: { en: "Notes", ar: "ملاحظات" }, kind: "textarea" },
  ],
  searchKeys: ["reference", "method", "notes"],
};

export const Route = createFileRoute("/_authenticated/payments")({
  head: () => ({
    meta: [
      { title: "Payments — VINCO ERP" },
      {
        name: "description",
        content:
          "Record customer receipts and supplier payments against invoices with approval by a second person.",
      },
      { property: "og:title", content: "Payments — VINCO ERP" },
      { property: "og:description", content: "Receipts and disbursements against invoices." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
