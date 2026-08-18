import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

const config: ResourceConfig = {
  table: "contracts",
  title: { en: "Contracts", ar: "العقود" },
  description: {
    en: "Signed agreements, retention and warranty terms.",
    ar: "العقود الموقعة وشروط الضمان والمحتجزات.",
  },
  perms: {
    view: ["contracts.view"],
    create: ["contracts.create"],
    edit: ["contracts.edit"],
    remove: ["contracts.delete"],
  },
  columns: [
    { key: "contract_no", label: { en: "No.", ar: "الرقم" } },
    { key: "title", label: { en: "Title", ar: "العنوان" } },
    { key: "customer_id", label: { en: "Customer", ar: "العميل" }, kind: "ref" },
    { key: "project_id", label: { en: "Project", ar: "المشروع" }, kind: "ref" },
    { key: "value", label: { en: "Value", ar: "القيمة" }, kind: "money" },
    { key: "retention_percent", label: { en: "Retention", ar: "المحتجزات" }, kind: "percent" },
    { key: "end_date", label: { en: "End date", ar: "تاريخ الانتهاء" }, kind: "date" },
    { key: "status", label: { en: "Status", ar: "الحالة" }, kind: "status" },
  ],
  fields: [
    { key: "title", label: { en: "Contract title", ar: "عنوان العقد" }, kind: "text", required: true },
    {
      key: "customer_id",
      label: { en: "Customer", ar: "العميل" },
      kind: "ref",
      ref: { table: "customers", labelCol: "name" },
      required: true,
      half: true,
    },
    {
      key: "project_id",
      label: { en: "Project", ar: "المشروع" },
      kind: "ref",
      ref: { table: "projects", labelCol: "name" },
      half: true,
    },
    {
      key: "status",
      label: { en: "Status", ar: "الحالة" },
      kind: "select",
      defaultValue: "draft",
      half: true,
      options: [
        { value: "draft", label: { en: "Draft", ar: "مسودة" } },
        { value: "active", label: { en: "Active", ar: "ساري" } },
        { value: "completed", label: { en: "Completed", ar: "منتهٍ" } },
        { value: "terminated", label: { en: "Terminated", ar: "مفسوخ" } },
      ],
    },
    { key: "value", label: { en: "Value (SAR)", ar: "القيمة (ر.س)" }, kind: "number", defaultValue: 0, half: true },
    { key: "start_date", label: { en: "Start date", ar: "تاريخ البداية" }, kind: "date", half: true },
    { key: "end_date", label: { en: "End date", ar: "تاريخ الانتهاء" }, kind: "date", half: true },
    { key: "signed_date", label: { en: "Signed date", ar: "تاريخ التوقيع" }, kind: "date", half: true },
    {
      key: "retention_percent",
      label: { en: "Retention %", ar: "نسبة المحتجزات %" },
      kind: "number",
      defaultValue: 5,
      half: true,
    },
    {
      key: "advance_percent",
      label: { en: "Advance payment %", ar: "الدفعة المقدمة %" },
      kind: "number",
      defaultValue: 0,
      half: true,
    },
    {
      key: "warranty_months",
      label: { en: "Warranty (months)", ar: "الضمان (أشهر)" },
      kind: "number",
      defaultValue: 12,
      half: true,
    },
    { key: "payment_terms", label: { en: "Payment terms", ar: "شروط الدفع" }, kind: "textarea" },
    { key: "notes", label: { en: "Notes", ar: "ملاحظات" }, kind: "textarea" },
  ],
  searchKeys: ["contract_no", "title", "payment_terms"],
};

export const Route = createFileRoute("/_authenticated/contracts")({
  head: () => ({
    meta: [
      { title: "Contracts — VINCO ERP" },
      {
        name: "description",
        content:
          "Signed customer contracts with values, retention percentages, advance payments and warranty periods.",
      },
      { property: "og:title", content: "Contracts — VINCO ERP" },
      { property: "og:description", content: "Agreements, retention and warranty terms." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
