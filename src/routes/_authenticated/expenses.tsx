import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

const config: ResourceConfig = {
  table: "expenses",
  title: { en: "Expenses", ar: "المصروفات" },
  description: {
    en: "Site and overhead spend, approved by a second person.",
    ar: "مصروفات المواقع والإدارة، يعتمدها شخص آخر.",
  },
  perms: {
    view: ["expenses.view"],
    create: ["expenses.create"],
    edit: ["expenses.edit"],
    remove: ["expenses.delete"],
  },
  columns: [
    { key: "expense_no", label: { en: "No.", ar: "الرقم" } },
    { key: "description", label: { en: "Description", ar: "الوصف" } },
    { key: "project_id", label: { en: "Project", ar: "المشروع" }, kind: "ref" },
    { key: "category", label: { en: "Category", ar: "التصنيف" } },
    { key: "amount", label: { en: "Amount", ar: "المبلغ" }, kind: "money" },
    { key: "expense_date", label: { en: "Date", ar: "التاريخ" }, kind: "date" },
    { key: "status", label: { en: "Status", ar: "الحالة" }, kind: "status" },
  ],
  fields: [
    { key: "description", label: { en: "Description", ar: "الوصف" }, kind: "text", required: true },
    {
      key: "project_id",
      label: { en: "Project", ar: "المشروع" },
      kind: "ref",
      ref: { table: "projects", labelCol: "name" },
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
      key: "category",
      label: { en: "Category", ar: "التصنيف" },
      kind: "select",
      half: true,
      options: [
        { value: "materials", label: { en: "Materials", ar: "مواد" } },
        { value: "labor", label: { en: "Labor", ar: "أيدٍ عاملة" } },
        { value: "equipment", label: { en: "Equipment", ar: "معدات" } },
        { value: "transport", label: { en: "Transport", ar: "نقل" } },
        { value: "permits", label: { en: "Permits", ar: "تصاريح" } },
        { value: "overhead", label: { en: "Overhead", ar: "مصروفات إدارية" } },
      ],
    },
    { key: "expense_date", label: { en: "Expense date", ar: "تاريخ المصروف" }, kind: "date", half: true },
    { key: "amount", label: { en: "Amount (SAR)", ar: "المبلغ (ر.س)" }, kind: "number", defaultValue: 0, half: true },
    { key: "vat_amount", label: { en: "VAT (SAR)", ar: "الضريبة (ر.س)" }, kind: "number", defaultValue: 0, half: true },
    {
      key: "payment_method",
      label: { en: "Payment method", ar: "طريقة الدفع" },
      kind: "select",
      half: true,
      options: [
        { value: "bank_transfer", label: { en: "Bank transfer", ar: "حوالة بنكية" } },
        { value: "cash", label: { en: "Cash", ar: "نقدي" } },
        { value: "cheque", label: { en: "Cheque", ar: "شيك" } },
        { value: "card", label: { en: "Card", ar: "بطاقة" } },
      ],
    },
    { key: "notes", label: { en: "Notes", ar: "ملاحظات" }, kind: "textarea" },
  ],
  searchKeys: ["expense_no", "description", "category"],
  orderBy: "expense_date",
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
