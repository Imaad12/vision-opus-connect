import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

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
    remove: ["leads.delete"],
  },
  columns: [
    { key: "title", label: { en: "Opportunity", ar: "الفرصة" } },
    { key: "customer_id", label: { en: "Customer", ar: "العميل" }, kind: "ref" },
    { key: "estimated_value", label: { en: "Value", ar: "القيمة" }, kind: "money" },
    { key: "probability", label: { en: "Win %", ar: "احتمال الفوز" }, kind: "percent" },
    { key: "expected_close_date", label: { en: "Expected close", ar: "الإغلاق المتوقع" }, kind: "date" },
    { key: "owner_id", label: { en: "Owner", ar: "المسؤول" }, kind: "ref" },
    { key: "status", label: { en: "Stage", ar: "المرحلة" }, kind: "status" },
  ],
  fields: [
    { key: "title", label: { en: "Opportunity title", ar: "عنوان الفرصة" }, kind: "text", required: true },
    {
      key: "customer_id",
      label: { en: "Customer", ar: "العميل" },
      kind: "ref",
      ref: { table: "customers", labelCol: "name" },
      half: true,
    },
    {
      key: "contact_id",
      label: { en: "Contact", ar: "جهة الاتصال" },
      kind: "ref",
      ref: { table: "contacts", labelCol: "full_name" },
      half: true,
    },
    {
      key: "source",
      label: { en: "Source", ar: "المصدر" },
      kind: "select",
      half: true,
      options: [
        { value: "referral", label: { en: "Referral", ar: "توصية" } },
        { value: "tender", label: { en: "Tender", ar: "منافسة" } },
        { value: "website", label: { en: "Website", ar: "الموقع" } },
        { value: "existing_client", label: { en: "Existing client", ar: "عميل حالي" } },
        { value: "other", label: { en: "Other", ar: "أخرى" } },
      ],
    },
    {
      key: "status",
      label: { en: "Stage", ar: "المرحلة" },
      kind: "select",
      defaultValue: "new",
      half: true,
      options: [
        { value: "new", label: { en: "New", ar: "جديد" } },
        { value: "qualified", label: { en: "Qualified", ar: "مؤهل" } },
        { value: "proposal", label: { en: "Proposal", ar: "عرض" } },
        { value: "negotiation", label: { en: "Negotiation", ar: "تفاوض" } },
        { value: "won", label: { en: "Won", ar: "مكسوب" } },
        { value: "lost", label: { en: "Lost", ar: "مفقود" } },
        { value: "on_hold", label: { en: "On hold", ar: "معلق" } },
      ],
    },
    {
      key: "estimated_value",
      label: { en: "Estimated value (SAR)", ar: "القيمة التقديرية (ر.س)" },
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
    { key: "description", label: { en: "Scope / notes", ar: "النطاق / ملاحظات" }, kind: "textarea" },
    { key: "lost_reason", label: { en: "Lost reason", ar: "سبب الخسارة" }, kind: "text" },
  ],
  searchKeys: ["title", "description", "source"],
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
