import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

const config: ResourceConfig = {
  table: "contacts",
  title: { en: "Contacts", ar: "جهات الاتصال" },
  description: {
    en: "People linked to customer accounts.",
    ar: "الأشخاص المرتبطون بحسابات العملاء.",
  },
  perms: {
    view: ["customers.view"],
    create: ["customers.create"],
    edit: ["customers.edit"],
    remove: ["customers.delete"],
  },
  columns: [
    { key: "full_name", label: { en: "Name", ar: "الاسم" } },
    { key: "customer_id", label: { en: "Customer", ar: "العميل" }, kind: "ref" },
    { key: "job_title", label: { en: "Job title", ar: "المسمى" } },
    { key: "phone", label: { en: "Phone", ar: "الهاتف" } },
    { key: "email", label: { en: "Email", ar: "البريد" } },
    { key: "is_primary", label: { en: "Primary", ar: "رئيسي" }, kind: "bool" },
  ],
  fields: [
    {
      key: "customer_id",
      label: { en: "Customer", ar: "العميل" },
      kind: "ref",
      ref: { table: "customers", labelCol: "name" },
      required: true,
      half: true,
    },
    { key: "full_name", label: { en: "Full name", ar: "الاسم الكامل" }, kind: "text", required: true, half: true },
    { key: "job_title", label: { en: "Job title", ar: "المسمى الوظيفي" }, kind: "text", half: true },
    { key: "department", label: { en: "Department", ar: "الإدارة" }, kind: "text", half: true },
    { key: "phone", label: { en: "Phone", ar: "الهاتف" }, kind: "text", half: true },
    { key: "email", label: { en: "Email", ar: "البريد" }, kind: "text", half: true },
    { key: "is_primary", label: { en: "Primary contact", ar: "جهة الاتصال الرئيسية" }, kind: "bool", half: true },
    { key: "notes", label: { en: "Notes", ar: "ملاحظات" }, kind: "textarea" },
  ],
  searchKeys: ["full_name", "job_title", "phone", "email"],
};

export const Route = createFileRoute("/_authenticated/contacts")({
  head: () => ({
    meta: [
      { title: "Contacts — VINCO ERP" },
      {
        name: "description",
        content: "Customer-side contacts, roles and primary points of contact for each account.",
      },
      { property: "og:title", content: "Contacts — VINCO ERP" },
      { property: "og:description", content: "People linked to each customer account." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
