import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

// Backed by the backend's real `Contact` model (`/contacts`), not
// Supabase's `contacts` table. Permission and field name are the real
// vocabulary (`contacts.*`, `client_id`) -- the previous config reused
// `customers.*` permissions and a `customer_id` column, which worked
// (those permissions exist) but gated contacts on the wrong resource's
// grant instead of the `contacts.view/create/edit` grant the frontend's
// `app_permission` enum actually defines for this page.
const config: ResourceConfig = {
  table: "contacts",
  title: { en: "Contacts", ar: "جهات الاتصال" },
  description: {
    en: "People linked to customer accounts.",
    ar: "الأشخاص المرتبطون بحسابات العملاء.",
  },
  perms: {
    view: ["contacts.view"],
    create: ["contacts.create"],
    edit: ["contacts.edit"],
  },
  backend: { basePath: "/contacts" },
  columns: [
    { key: "full_name", label: { en: "Name", ar: "الاسم" } },
    { key: "client_id", label: { en: "Customer", ar: "العميل" }, kind: "ref" },
    { key: "job_title", label: { en: "Job title", ar: "المسمى" } },
    { key: "phone", label: { en: "Phone", ar: "الهاتف" } },
    { key: "email", label: { en: "Email", ar: "البريد" } },
    { key: "is_primary", label: { en: "Primary", ar: "رئيسي" }, kind: "bool" },
  ],
  fields: [
    {
      key: "client_id",
      label: { en: "Customer", ar: "العميل" },
      kind: "ref",
      ref: { table: "clients", labelCol: "name", backendPath: "/clients" },
      required: true,
      half: true,
    },
    {
      key: "full_name",
      label: { en: "Full name", ar: "الاسم الكامل" },
      kind: "text",
      required: true,
      half: true,
    },
    {
      key: "job_title",
      label: { en: "Job title", ar: "المسمى الوظيفي" },
      kind: "text",
      half: true,
    },
    { key: "department", label: { en: "Department", ar: "الإدارة" }, kind: "text", half: true },
    { key: "phone", label: { en: "Phone", ar: "الهاتف" }, kind: "text", half: true },
    { key: "email", label: { en: "Email", ar: "البريد" }, kind: "text", half: true },
    {
      key: "is_primary",
      label: { en: "Primary contact", ar: "جهة الاتصال الرئيسية" },
      kind: "bool",
      half: true,
    },
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
