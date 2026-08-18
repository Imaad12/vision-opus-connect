import { createFileRoute } from "@tanstack/react-router";

import { ItemsButton } from "@/components/doc-actions";
import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

const config: ResourceConfig = {
  table: "invoices",
  title: { en: "Invoices", ar: "الفواتير" },
  description: {
    en: "Sales and purchase invoices with 15% VAT and collection status.",
    ar: "فواتير البيع والشراء مع ضريبة ١٥٪ وحالة التحصيل.",
  },
  perms: {
    view: ["invoices.view"],
    create: ["invoices.create"],
    edit: ["invoices.edit"],
    remove: ["invoices.delete"],
  },
  columns: [
    { key: "invoice_no", label: { en: "No.", ar: "الرقم" } },
    { key: "type", label: { en: "Type", ar: "النوع" }, kind: "status" },
    { key: "customer_id", label: { en: "Customer", ar: "العميل" }, kind: "ref" },
    { key: "project_id", label: { en: "Project", ar: "المشروع" }, kind: "ref" },
    { key: "total", label: { en: "Total", ar: "الإجمالي" }, kind: "money" },
    { key: "amount_paid", label: { en: "Paid", ar: "المسدد" }, kind: "money" },
    { key: "due_date", label: { en: "Due", ar: "الاستحقاق" }, kind: "date" },
    { key: "status", label: { en: "Status", ar: "الحالة" }, kind: "status" },
  ],
  fields: [
    {
      key: "type",
      label: { en: "Invoice type", ar: "نوع الفاتورة" },
      kind: "select",
      defaultValue: "sales",
      half: true,
      options: [
        { value: "sales", label: { en: "Sales (customer)", ar: "بيع (عميل)" } },
        { value: "purchase", label: { en: "Purchase (supplier)", ar: "شراء (مورد)" } },
      ],
    },
    {
      key: "customer_id",
      label: { en: "Customer", ar: "العميل" },
      kind: "ref",
      ref: { table: "customers", labelCol: "name" },
      half: true,
    },
    {
      key: "supplier_id",
      label: { en: "Supplier", ar: "المورد" },
      kind: "ref",
      ref: { table: "suppliers", labelCol: "name" },
      half: true,
    },
    {
      key: "project_id",
      label: { en: "Project", ar: "المشروع" },
      kind: "ref",
      ref: { table: "projects", labelCol: "name" },
      half: true,
    },
    { key: "issue_date", label: { en: "Issue date", ar: "تاريخ الإصدار" }, kind: "date", half: true },
    { key: "due_date", label: { en: "Due date", ar: "تاريخ الاستحقاق" }, kind: "date", half: true },
    { key: "vat_rate", label: { en: "VAT rate %", ar: "نسبة الضريبة %" }, kind: "number", defaultValue: 15, half: true },
    {
      key: "status",
      label: { en: "Status", ar: "الحالة" },
      kind: "select",
      defaultValue: "draft",
      half: true,
      options: [
        { value: "draft", label: { en: "Draft", ar: "مسودة" } },
        { value: "issued", label: { en: "Issued", ar: "صادرة" } },
        { value: "partially_paid", label: { en: "Partially paid", ar: "مسددة جزئياً" } },
        { value: "paid", label: { en: "Paid", ar: "مسددة" } },
        { value: "overdue", label: { en: "Overdue", ar: "متأخرة" } },
        { value: "cancelled", label: { en: "Cancelled", ar: "ملغاة" } },
      ],
    },
    { key: "notes", label: { en: "Notes", ar: "ملاحظات" }, kind: "textarea" },
  ],
  searchKeys: ["invoice_no", "notes"],
  extraRowActions: (row) => (
    <ItemsButton
      row={row}
      parentTable="invoices"
      itemsTable="invoice_items"
      parentColumn="invoice_id"
      editable={String(row["status"]) === "draft"}
    />
  ),
};

export const Route = createFileRoute("/_authenticated/invoices")({
  head: () => ({
    meta: [
      { title: "Invoices — VINCO ERP" },
      {
        name: "description",
        content: "Issue and track sales and purchase invoices with 15% VAT, due dates and payment status.",
      },
      { property: "og:title", content: "Invoices — VINCO ERP" },
      { property: "og:description", content: "VAT invoices with collection tracking." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
