import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

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
    remove: ["suppliers.delete"],
  },
  columns: [
    { key: "name", label: { en: "Name", ar: "الاسم" } },
    { key: "category", label: { en: "Category", ar: "التصنيف" } },
    { key: "vat_number", label: { en: "VAT no.", ar: "الرقم الضريبي" } },
    { key: "phone", label: { en: "Phone", ar: "الهاتف" } },
    { key: "rating", label: { en: "Rating", ar: "التقييم" }, kind: "number" },
    { key: "status", label: { en: "Status", ar: "الحالة" }, kind: "status" },
  ],
  fields: [
    { key: "name", label: { en: "Name (EN)", ar: "الاسم (إنجليزي)" }, kind: "text", required: true, half: true },
    { key: "name_ar", label: { en: "Name (AR)", ar: "الاسم (عربي)" }, kind: "text", half: true },
    {
      key: "category",
      label: { en: "Category", ar: "التصنيف" },
      kind: "select",
      half: true,
      options: [
        { value: "materials", label: { en: "Materials", ar: "مواد" } },
        { value: "subcontractor", label: { en: "Subcontractor", ar: "مقاول باطن" } },
        { value: "equipment", label: { en: "Equipment", ar: "معدات" } },
        { value: "services", label: { en: "Services", ar: "خدمات" } },
      ],
    },
    { key: "vat_number", label: { en: "VAT number", ar: "الرقم الضريبي" }, kind: "text", half: true },
    { key: "cr_number", label: { en: "CR number", ar: "السجل التجاري" }, kind: "text", half: true },
    { key: "city", label: { en: "City", ar: "المدينة" }, kind: "text", half: true },
    { key: "phone", label: { en: "Phone", ar: "الهاتف" }, kind: "text", half: true },
    { key: "email", label: { en: "Email", ar: "البريد" }, kind: "text", half: true },
    {
      key: "payment_terms_days",
      label: { en: "Payment terms (days)", ar: "مدة السداد (يوم)" },
      kind: "number",
      defaultValue: 30,
      half: true,
    },
    { key: "rating", label: { en: "Rating (1-5)", ar: "التقييم (1-5)" }, kind: "number", half: true },
    {
      key: "status",
      label: { en: "Status", ar: "الحالة" },
      kind: "select",
      defaultValue: "active",
      half: true,
      options: [
        { value: "active", label: { en: "Active", ar: "نشط" } },
        { value: "inactive", label: { en: "Inactive", ar: "غير نشط" } },
        { value: "blacklisted", label: { en: "Blacklisted", ar: "محظور" } },
      ],
    },
    { key: "iban", label: { en: "IBAN", ar: "الآيبان" }, kind: "text", half: true },
    { key: "address", label: { en: "Address", ar: "العنوان" }, kind: "textarea" },
    { key: "notes", label: { en: "Notes", ar: "ملاحظات" }, kind: "textarea" },
  ],
  searchKeys: ["name", "name_ar", "category", "city", "vat_number"],
};

export const Route = createFileRoute("/_authenticated/suppliers")({
  head: () => ({
    meta: [
      { title: "Suppliers — VINCO ERP" },
      {
        name: "description",
        content:
          "Vendor and subcontractor register with VAT numbers, payment terms, ratings and banking details.",
      },
      { property: "og:title", content: "Suppliers — VINCO ERP" },
      { property: "og:description", content: "Vendors and subcontractors with commercial terms." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
