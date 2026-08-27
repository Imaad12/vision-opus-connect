import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

// Backed by the Vision Contracting backend's own database (`Client` /
// `client_service.py`) via `/clients`, not Supabase's `customers` table.
// See API_ARCHITECTURE.md in the backend repo: `Client` today only has
// name/contact_name/contact_email/contact_phone/address/notes, so the
// richer fields Supabase's `customers` table has (VAT/CR numbers,
// industry, region, credit limit, payment terms, an account-owner
// profile link, a status) aren't shown here rather than being silently
// dropped on save. Restoring them is a real decision (extend `Client`,
// or keep those fields Supabase-only) for a later pass, not something
// invented here to keep this form looking the same as before.
const config: ResourceConfig = {
  table: "customers",
  title: { en: "Customers", ar: "العملاء" },
  description: {
    en: "Client accounts.",
    ar: "حسابات العملاء.",
  },
  perms: {
    view: ["customers.view"],
    create: ["customers.create"],
    edit: ["customers.edit"],
  },
  backend: { basePath: "/clients" },
  columns: [
    { key: "name", label: { en: "Name", ar: "الاسم" } },
    { key: "contact_name", label: { en: "Contact", ar: "جهة الاتصال" } },
    { key: "contact_phone", label: { en: "Phone", ar: "الهاتف" } },
    { key: "contact_email", label: { en: "Email", ar: "البريد" } },
  ],
  fields: [
    { key: "name", label: { en: "Name", ar: "الاسم" }, kind: "text", required: true },
    {
      key: "contact_name",
      label: { en: "Contact name", ar: "اسم جهة الاتصال" },
      kind: "text",
      half: true,
    },
    { key: "contact_phone", label: { en: "Phone", ar: "الهاتف" }, kind: "text", half: true },
    { key: "contact_email", label: { en: "Email", ar: "البريد" }, kind: "text", half: true },
    { key: "address", label: { en: "Address", ar: "العنوان" }, kind: "textarea" },
    { key: "notes", label: { en: "Notes", ar: "ملاحظات" }, kind: "textarea" },
  ],
  searchKeys: ["name", "contact_name", "contact_phone", "contact_email"],
};

export const Route = createFileRoute("/_authenticated/customers")({
  head: () => ({
    meta: [
      { title: "Customers — VINCO ERP" },
      {
        name: "description",
        content: "Manage Vision Contracting Co. client accounts.",
      },
      { property: "og:title", content: "Customers — VINCO ERP" },
      { property: "og:description", content: "Client accounts." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
