import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

// Backed by the backend's own `Project` model (`/projects`), not
// Supabase's `projects` table. The customer dropdown resolves against
// the backend's own `/clients` (see `customers.tsx`), not Supabase's
// `customers` table -- the two have entirely different ids, so mixing
// them would silently point a project at the wrong customer.
//
// Not shown here, on purpose: `manager_id`, `location`, `budget_cost`,
// `progress_percent` (no backend equivalent yet), and a directly
// editable `contract_value` -- the backend only ever sets that once, via
// awarding a quotation (see the Quotations screen once wired), never
// through a direct project edit. It's shown read-only below instead of
// silently accepting and dropping an edited value.
// `status` uses the backend's real lifecycle (LEAD/TENDERING/SUBMITTED/
// AWARDED/LOST/IN_PROGRESS/ON_HOLD/COMPLETED/CLOSED/CANCELLED), not
// Supabase's planning/active/on_hold/completed/archived/cancelled.
const config: ResourceConfig = {
  table: "projects",
  title: { en: "Projects", ar: "المشاريع" },
  description: {
    en: "Delivery portfolio with schedule and status.",
    ar: "محفظة التنفيذ مع الجدول الزمني والحالة.",
  },
  perms: {
    view: ["projects.view"],
    create: ["projects.create"],
    edit: ["projects.edit"],
  },
  backend: { basePath: "/projects" },
  columns: [
    { key: "project_code", label: { en: "No.", ar: "الرقم" } },
    { key: "name", label: { en: "Project", ar: "المشروع" } },
    { key: "client_id", label: { en: "Customer", ar: "العميل" }, kind: "ref" },
    { key: "contract_value", label: { en: "Contract value", ar: "قيمة العقد" }, kind: "money" },
    { key: "start_date", label: { en: "Start date", ar: "تاريخ البداية" }, kind: "date" },
    {
      key: "planned_completion_date",
      label: { en: "Expected completion", ar: "الانتهاء المتوقع" },
      kind: "date",
    },
    { key: "status", label: { en: "Status", ar: "الحالة" }, kind: "status" },
  ],
  fields: [
    { key: "name", label: { en: "Project name", ar: "اسم المشروع" }, kind: "text", required: true },
    {
      key: "client_id",
      label: { en: "Customer", ar: "العميل" },
      kind: "ref",
      ref: { table: "clients", labelCol: "name", backendPath: "/clients" },
      required: true,
      half: true,
    },
    {
      key: "project_code",
      label: { en: "Project no.", ar: "رقم المشروع" },
      kind: "text",
      half: true,
    },
    {
      key: "status",
      label: { en: "Status", ar: "الحالة" },
      kind: "select",
      defaultValue: "LEAD",
      half: true,
      options: [
        { value: "LEAD", label: { en: "Lead", ar: "فرصة" } },
        { value: "TENDERING", label: { en: "Tendering", ar: "مناقصة" } },
        { value: "SUBMITTED", label: { en: "Submitted", ar: "مُقدَّم" } },
        { value: "AWARDED", label: { en: "Awarded", ar: "مُرسى" } },
        { value: "LOST", label: { en: "Lost", ar: "خسارة" } },
        { value: "IN_PROGRESS", label: { en: "In progress", ar: "قيد التنفيذ" } },
        { value: "ON_HOLD", label: { en: "On hold", ar: "معلق" } },
        { value: "COMPLETED", label: { en: "Completed", ar: "مكتمل" } },
        { value: "CLOSED", label: { en: "Closed", ar: "مغلق" } },
        { value: "CANCELLED", label: { en: "Cancelled", ar: "ملغى" } },
      ],
    },
    {
      key: "start_date",
      label: { en: "Start date", ar: "تاريخ البداية" },
      kind: "date",
      half: true,
    },
    {
      key: "planned_completion_date",
      label: { en: "Expected completion", ar: "الانتهاء المتوقع" },
      kind: "date",
      half: true,
    },
    { key: "description", label: { en: "Scope of work", ar: "نطاق العمل" }, kind: "textarea" },
    { key: "notes", label: { en: "Notes", ar: "ملاحظات" }, kind: "textarea" },
  ],
  searchKeys: ["project_code", "name", "description"],
};

export const Route = createFileRoute("/_authenticated/projects")({
  head: () => ({
    meta: [
      { title: "Projects — VINCO ERP" },
      {
        name: "description",
        content:
          "Delivery portfolio for Vision Contracting Co.: schedule, status and contract value.",
      },
      { property: "og:title", content: "Projects — VINCO ERP" },
      { property: "og:description", content: "Schedule and status across all sites." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
