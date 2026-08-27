import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

// Backed by the backend's real `Lead` model (`/leads`), not Supabase's
// `leads` table -- a deliberately separate pre-project pipeline, not a
// duplicate of `Project.status` (which also starts at LEAD/TENDERING):
// see `app/models/lead.py`. There is no `leads.delete` in the real
// `app_permission` enum (winning/losing a lead is recorded via `status`,
// not deletion), so no remove is wired. `contact_id` now resolves against
// the backend's own `/contacts` (see contacts.tsx) since Supabase's
// `contacts` table is no longer where new contacts are created.
const config: ResourceConfig = {
  table: "leads",
  title: { en: "Leads", ar: "الفرص" },
  description: {
    en: "Sales pipeline from first enquiry to award.",
    ar: "مسار البيع من الاستفسار حتى الترسية.",
  },
  perms: {
    view: ["leads.view"],
    create: ["leads.create"],
    edit: ["leads.edit"],
  },
  backend: { basePath: "/leads" },
  columns: [
    { key: "title", label: { en: "Opportunity", ar: "الفرصة" } },
    { key: "client_id", label: { en: "Customer", ar: "العميل" }, kind: "ref" },
    { key: "estimated_value", label: { en: "Value", ar: "القيمة" }, kind: "money" },
    { key: "probability", label: { en: "Win %", ar: "احتمال الفوز" }, kind: "percent" },
    {
      key: "expected_close_date",
      label: { en: "Expected close", ar: "الإغلاق المتوقع" },
      kind: "date",
    },
    { key: "status", label: { en: "Stage", ar: "المرحلة" }, kind: "status" },
  ],
  fields: [
    {
      key: "title",
      label: { en: "Opportunity title", ar: "عنوان الفرصة" },
      kind: "text",
      required: true,
    },
    {
      key: "client_id",
      label: { en: "Customer", ar: "العميل" },
      kind: "ref",
      ref: { table: "clients", labelCol: "name", backendPath: "/clients" },
      half: true,
    },
    {
      key: "contact_id",
      label: { en: "Contact", ar: "جهة الاتصال" },
      kind: "ref",
      ref: { table: "contacts", labelCol: "full_name", backendPath: "/contacts" },
      half: true,
    },
    {
      key: "source",
      label: { en: "Source", ar: "المصدر" },
      kind: "select",
      half: true,
      options: [
        { value: "REFERRAL", label: { en: "Referral", ar: "توصية" } },
        { value: "TENDER", label: { en: "Tender", ar: "منافسة" } },
        { value: "WEBSITE", label: { en: "Website", ar: "الموقع" } },
        { value: "EXISTING_CLIENT", label: { en: "Existing client", ar: "عميل حالي" } },
        { value: "OTHER", label: { en: "Other", ar: "أخرى" } },
      ],
    },
    {
      key: "status",
      label: { en: "Stage", ar: "المرحلة" },
      kind: "select",
      defaultValue: "NEW",
      half: true,
      options: [
        { value: "NEW", label: { en: "New", ar: "جديد" } },
        { value: "QUALIFIED", label: { en: "Qualified", ar: "مؤهل" } },
        { value: "PROPOSAL", label: { en: "Proposal", ar: "عرض" } },
        { value: "NEGOTIATION", label: { en: "Negotiation", ar: "تفاوض" } },
        { value: "WON", label: { en: "Won", ar: "مكسوب" } },
        { value: "LOST", label: { en: "Lost", ar: "مفقود" } },
        { value: "ON_HOLD", label: { en: "On hold", ar: "معلق" } },
      ],
    },
    {
      key: "estimated_value",
      label: { en: "Estimated value", ar: "القيمة التقديرية" },
      kind: "number",
      defaultValue: 0,
      half: true,
    },
    {
      key: "probability",
      label: { en: "Win probability %", ar: "نسبة الفوز %" },
      kind: "number",
      defaultValue: 30,
      half: true,
    },
    {
      key: "expected_close_date",
      label: { en: "Expected close date", ar: "تاريخ الإغلاق المتوقع" },
      kind: "date",
      half: true,
    },
    { key: "owner_id", label: { en: "Owner", ar: "المسؤول" }, kind: "profile", half: true },
    {
      key: "description",
      label: { en: "Scope / notes", ar: "النطاق / ملاحظات" },
      kind: "textarea",
    },
    { key: "lost_reason", label: { en: "Lost reason", ar: "سبب الخسارة" }, kind: "text" },
  ],
  searchKeys: ["title", "description"],
};

export const Route = createFileRoute("/_authenticated/leads")({
  head: () => ({
    meta: [
      { title: "Leads — VINCO ERP" },
      {
        name: "description",
        content:
          "Track contracting opportunities by stage, value, win probability and expected award date.",
      },
      { property: "og:title", content: "Leads — VINCO ERP" },
      { property: "og:description", content: "Sales pipeline from enquiry to award." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
