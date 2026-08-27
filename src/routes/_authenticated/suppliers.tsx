import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

// Backed by the backend's own `Vendor` model (`/vendors`), not Supabase's
// `suppliers` table. `Vendor` covers both suppliers and subcontractors
// via `vendor_type`, but doesn't have category/CR number/city/rating/
// IBAN/address/name_ar/a three-state status the way Supabase's table
// did -- those fields aren't shown here rather than being silently
// dropped on save. See API_ARCHITECTURE.md (backend repo) for the full
// gap list; `is_active` (a plain on/off, not the old
// active/inactive/blacklisted) is the closest real equivalent to the old
// status field.
const config: ResourceConfig = {
  table: "suppliers",
  title: { en: "Suppliers", ar: "الموردون" },
  description: {
    en: "Vendors and subcontractors with commercial terms.",
    ar: "الموردون ومقاولو الباطن مع الشروط التجارية.",
  },
  perms: {
    view: ["suppliers.view"],
    create: ["suppliers.create"],
    edit: ["suppliers.edit"],
  },
  backend: { basePath: "/vendors" },
  columns: [
    { key: "name", label: { en: "Name", ar: "الاسم" } },
    {
      key: "vendor_type",
      label: { en: "Type", ar: "النوع" },
      kind: "ref",
      refLabel: { SUPPLIER: "Supplier", SUBCONTRACTOR: "Subcontractor" },
    },
    { key: "tax_number", label: { en: "VAT/tax no.", ar: "الرقم الضريبي" } },
    { key: "contact_phone", label: { en: "Phone", ar: "الهاتف" } },
    { key: "is_active", label: { en: "Active", ar: "نشط" }, kind: "bool" },
  ],
  fields: [
    { key: "name", label: { en: "Name", ar: "الاسم" }, kind: "text", required: true, half: true },
    {
      key: "vendor_type",
      label: { en: "Type", ar: "النوع" },
      kind: "select",
      defaultValue: "SUPPLIER",
      half: true,
      options: [
        { value: "SUPPLIER", label: { en: "Supplier", ar: "مورد" } },
        { value: "SUBCONTRACTOR", label: { en: "Subcontractor", ar: "مقاول باطن" } },
      ],
    },
    {
      key: "contact_name",
      label: { en: "Contact name", ar: "اسم جهة الاتصال" },
      kind: "text",
      half: true,
    },
    {
      key: "tax_number",
      label: { en: "VAT/tax number", ar: "الرقم الضريبي" },
      kind: "text",
      half: true,
    },
    { key: "contact_phone", label: { en: "Phone", ar: "الهاتف" }, kind: "text", half: true },
    { key: "contact_email", label: { en: "Email", ar: "البريد" }, kind: "text", half: true },
    {
      key: "payment_terms",
      label: { en: "Payment terms", ar: "شروط السداد" },
      kind: "text",
      half: true,
    },
    {
      key: "is_active",
      label: { en: "Active", ar: "نشط" },
      kind: "bool",
      defaultValue: 1,
      half: true,
    },
    { key: "notes", label: { en: "Notes", ar: "ملاحظات" }, kind: "textarea" },
  ],
  searchKeys: ["name", "tax_number", "contact_phone", "contact_email"],
};

export const Route = createFileRoute("/_authenticated/suppliers")({
  head: () => ({
    meta: [
      { title: "Suppliers — VINCO ERP" },
      {
        name: "description",
        content: "Vendor and subcontractor register with VAT numbers and payment terms.",
      },
      { property: "og:title", content: "Suppliers — VINCO ERP" },
      { property: "og:description", content: "Vendors and subcontractors with commercial terms." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
