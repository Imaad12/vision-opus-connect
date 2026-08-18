import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

const config: ResourceConfig = {
  table: "projects",
  title: { en: "Projects", ar: "المشاريع" },
  description: {
    en: "Delivery portfolio with schedule, value and progress.",
    ar: "محفظة التنفيذ مع الجدول الزمني والقيمة والتقدم.",
  },
  perms: {
    view: ["projects.view"],
    create: ["projects.create"],
    edit: ["projects.edit"],
    remove: ["projects.delete"],
  },
  columns: [
    { key: "project_no", label: { en: "No.", ar: "الرقم" } },
    { key: "name", label: { en: "Project", ar: "المشروع" } },
    { key: "customer_id", label: { en: "Customer", ar: "العميل" }, kind: "ref" },
    { key: "contract_value", label: { en: "Value", ar: "القيمة" }, kind: "money" },
    { key: "progress_percent", label: { en: "Progress", ar: "التقدم" }, kind: "percent" },
    { key: "end_date", label: { en: "End date", ar: "تاريخ الانتهاء" }, kind: "date" },
    { key: "manager_id", label: { en: "Manager", ar: "مدير المشروع" }, kind: "ref" },
    { key: "status", label: { en: "Status", ar: "الحالة" }, kind: "status" },
  ],
  fields: [
    { key: "name", label: { en: "Project name", ar: "اسم المشروع" }, kind: "text", required: true },
    {
      key: "customer_id",
      label: { en: "Customer", ar: "العميل" },
      kind: "ref",
      ref: { table: "customers", labelCol: "name" },
      required: true,
      half: true,
    },
    { key: "manager_id", label: { en: "Project manager", ar: "مدير المشروع" }, kind: "profile", half: true },
    { key: "location", label: { en: "Site location", ar: "موقع المشروع" }, kind: "text", half: true },
    {
      key: "status",
      label: { en: "Status", ar: "الحالة" },
      kind: "select",
      defaultValue: "planning",
      half: true,
      options: [
        { value: "planning", label: { en: "Planning", ar: "تخطيط" } },
        { value: "active", label: { en: "Active", ar: "قائم" } },
        { value: "on_hold", label: { en: "On hold", ar: "معلق" } },
        { value: "completed", label: { en: "Completed", ar: "مكتمل" } },
        { value: "cancelled", label: { en: "Cancelled", ar: "ملغى" } },
      ],
    },
    { key: "start_date", label: { en: "Start date", ar: "تاريخ البداية" }, kind: "date", half: true },
    { key: "end_date", label: { en: "End date", ar: "تاريخ الانتهاء" }, kind: "date", half: true },
    {
      key: "contract_value",
      label: { en: "Contract value (SAR)", ar: "قيمة العقد (ر.س)" },
      kind: "number",
      defaultValue: 0,
      half: true,
    },
    {
      key: "budget_cost",
      label: { en: "Budget cost (SAR)", ar: "الميزانية التقديرية (ر.س)" },
      kind: "number",
      defaultValue: 0,
      half: true,
    },
    {
      key: "progress_percent",
      label: { en: "Progress %", ar: "نسبة الإنجاز %" },
      kind: "number",
      defaultValue: 0,
      half: true,
    },
    { key: "description", label: { en: "Scope of work", ar: "نطاق العمل" }, kind: "textarea" },
  ],
  searchKeys: ["project_no", "name", "location", "description"],
};

export const Route = createFileRoute("/_authenticated/projects")({
  head: () => ({
    meta: [
      { title: "Projects — VINCO ERP" },
      {
        name: "description",
        content:
          "Delivery portfolio for Vision Contracting Co.: contract value, budget, schedule dates and site progress.",
      },
      { property: "og:title", content: "Projects — VINCO ERP" },
      { property: "og:description", content: "Schedule, value and progress across all sites." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
