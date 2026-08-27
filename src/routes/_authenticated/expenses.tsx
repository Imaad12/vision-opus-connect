import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

// Backed by the backend's real `ActualCost` model (`/expenses`), not
// Supabase's `expenses` table. Permission is `finance.expenses` -- the
// frontend's real `app_permission` enum has no `expenses.*` vocabulary at
// all, so the previous `expenses.view/create/edit/delete` config never
// matched a real permission, the same class of bug already found and
// fixed for purchase-orders.tsx/approvals.tsx.
//
// `category` is now a ref against the backend's real `CostCategory`
// lookup table (`/cost-categories`) instead of a hardcoded select --
// categories are business data (see `app/database/seed.py`), not a fixed
// enum. `vat_amount`/`payment_method` have no backend equivalent yet
// (tax is tracked as `tax_amount`, on the same amount/tax_amount shape
// already used by Invoice) and are shown accordingly below; there is
// deliberately no `remove` -- see resource-page.tsx's `BackendSource` doc.
const config: ResourceConfig = {
  table: "expenses",
  title: { en: "Expenses", ar: "المصروفات" },
  description: {
    en: "Site and overhead spend, approved by a second person.",
    ar: "مصروفات المواقع والإدارة، يعتمدها شخص آخر.",
  },
  perms: {
    view: ["finance.expenses"],
    create: ["finance.expenses"],
    edit: ["finance.expenses"],
  },
  backend: { basePath: "/expenses" },
  columns: [
    { key: "description", label: { en: "Description", ar: "الوصف" } },
    { key: "project_id", label: { en: "Project", ar: "المشروع" }, kind: "ref" },
    { key: "cost_category_id", label: { en: "Category", ar: "التصنيف" }, kind: "ref" },
    { key: "amount", label: { en: "Amount", ar: "المبلغ" }, kind: "money" },
    { key: "incurred_date", label: { en: "Date", ar: "التاريخ" }, kind: "date" },
    { key: "payment_status", label: { en: "Payment status", ar: "حالة الدفع" }, kind: "status" },
  ],
  fields: [
    { key: "description", label: { en: "Description", ar: "الوصف" }, kind: "text" },
    {
      key: "project_id",
      label: { en: "Project", ar: "المشروع" },
      kind: "ref",
      ref: { table: "projects", labelCol: "name", backendPath: "/projects" },
      required: true,
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
      key: "cost_category_id",
      label: { en: "Category", ar: "التصنيف" },
      kind: "ref",
      ref: { table: "cost_categories", labelCol: "name", backendPath: "/cost-categories" },
      required: true,
      half: true,
    },
    {
      key: "incurred_date",
      label: { en: "Expense date", ar: "تاريخ المصروف" },
      kind: "date",
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
      key: "tax_amount",
      label: { en: "Tax amount", ar: "قيمة الضريبة" },
      kind: "number",
      half: true,
    },
    {
      key: "payment_status",
      label: { en: "Payment status", ar: "حالة الدفع" },
      kind: "select",
      defaultValue: "UNPAID",
      half: true,
      options: [
        { value: "UNPAID", label: { en: "Unpaid", ar: "غير مدفوع" } },
        { value: "PARTIALLY_PAID", label: { en: "Partially paid", ar: "مدفوع جزئياً" } },
        { value: "PAID", label: { en: "Paid", ar: "مدفوع" } },
      ],
    },
    {
      key: "reference_number",
      label: { en: "Reference no.", ar: "رقم المرجع" },
      kind: "text",
      half: true,
    },
    { key: "notes", label: { en: "Notes", ar: "ملاحظات" }, kind: "textarea" },
  ],
  searchKeys: ["description", "reference_number"],
};

export const Route = createFileRoute("/_authenticated/expenses")({
  head: () => ({
    meta: [
      { title: "Expenses — VINCO ERP" },
      {
        name: "description",
        content:
          "Record site and overhead expenses with VAT, project allocation and second-person approval.",
      },
      { property: "og:title", content: "Expenses — VINCO ERP" },
      { property: "og:description", content: "Site and overhead spend with approval controls." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
