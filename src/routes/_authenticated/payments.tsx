import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

const config: ResourceConfig = {
  table: "payments",
  title: { en: "Payments", ar: "المدفوعات" },
  description: {
    en: "Receipts and disbursements against invoices.",
    ar: "المقبوضات والمدفوعات مقابل الفواتير.",
  },
  perms: {
    view: ["payments.view"],
    create: ["payments.create"],
    edit: ["payments.edit"],
    remove: ["payments.delete"],
  },
  columns: [
    { key: "invoice_id", label: { en: "Invoice", ar: "الفاتورة" }, kind: "ref" },
    { key: "amount", label: { en: "Amount", ar: "المبلغ" }, kind: "money" },
    { key: "payment_date", label: { en: "Date", ar: "التاريخ" }, kind: "date" },
    { key: "method", label: { en: "Method", ar: "الطريقة" } },
    { key: "reference", label: { en: "Reference", ar: "المرجع" } },
    { key: "approved_by", label: { en: "Approved by", ar: "اعتمدها" }, kind: "ref" },
  ],
  fields: [
    {
      key: "invoice_id",
      label: { en: "Invoice", ar: "الفاتورة" },
      kind: "ref",
      ref: { table: "invoices", labelCol: "invoice_no" },
      required: true,
      half: true,
    },
    { key: "amount", label: { en: "Amount (SAR)", ar: "المبلغ (ر.س)" }, kind: "number", defaultValue: 0, half: true },
    { key: "payment_date", label: { en: "Payment date", ar: "تاريخ الدفع" }, kind: "date", half: true },
    {
      key: "method",
      label: { en: "Method", ar: "طريقة الدفع" },
      kind: "select",
      defaultValue: "bank_transfer",
      half: true,
      options: [
        { value: "bank_transfer", label: { en: "Bank transfer", ar: "حوالة بنكية" } },
        { value: "cheque", label: { en: "Cheque", ar: "شيك" } },
        { value: "cash", label: { en: "Cash", ar: "نقدي" } },
        { value: "card", label: { en: "Card", ar: "بطاقة" } },
      ],
    },
    { key: "reference", label: { en: "Reference / transaction no.", ar: "المرجع / رقم العملية" }, kind: "text" },
    { key: "approved_by", label: { en: "Approved by", ar: "اعتمدها" }, kind: "profile", half: true },
    { key: "notes", label: { en: "Notes", ar: "ملاحظات" }, kind: "textarea" },
  ],
  searchKeys: ["reference", "method", "notes"],
  orderBy: "payment_date",
};

export const Route = createFileRoute("/_authenticated/payments")({
  head: () => ({
    meta: [
      { title: "Payments — VINCO ERP" },
      {
        name: "description",
        content: "Record customer receipts and supplier payments against invoices with approval by a second person.",
      },
      { property: "og:title", content: "Payments — VINCO ERP" },
      { property: "og:description", content: "Receipts and disbursements against invoices." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
