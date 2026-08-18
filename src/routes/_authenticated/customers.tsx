import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

const config: ResourceConfig = {
  table: "customers",
  title: { en: "Customers", ar: "العملاء" },
  description: {
    en: "Client accounts with VAT and commercial registration details.",
    ar: "حسابات العملاء مع بيانات الضريبة والسجل التجاري.",
  },
  perms: {
    view: ["customers.view"],
    create: ["customers.create"],
    edit: ["customers.edit"],
    remove: ["customers.delete"],
  },
  columns: [
    { key: "name", label: { en: "Name", ar: "الاسم" } },
    { key: "city", label: { en: "City", ar: "المدينة" } },
    { key: "vat_number", label: { en: "VAT no.", ar: "الرقم الضريبي" } },
    { key: "phone", label: { en: "Phone", ar: "الهاتف" } },
    { key: "credit_limit", label: { en: "Credit limit", ar: "حد الائتمان" }, kind: "money" },
    { key: "owner_id", label: { en: "Account owner", ar: "مسؤول الحساب" } },
    { key: "status", label: { en: "Status", ar: "الحالة" }, kind: "status" },
  ],
  fields: [
    { key: "name", label: { en: "Name (EN)", ar: "الاسم (إنجليزي)" }, kind: "text", required: true, half: true },
    { key: "name_ar", label: { en: "Name (AR)", ar: "الاسم (عربي)" }, kind: "text", half: true },
    { key: "vat_number", label: { en: "VAT number", ar: "الرقم الضريبي" }, kind: "text", half: true },
    { key: "cr_number", label: { en: "CR number", ar: "السجل التجاري" }, kind: "text", half: true },
    { key: "industry", label: { en: "Sector", ar: "القطاع" }, kind: "text", half: true },
    { key: "city", label: { en: "City", ar: "المدينة" }, kind: "text", half: true },
    { key: "region", label: { en: "Region", ar: "المنطقة" }, kind: "text", half: true },
    { key: "phone", label: { en: "Phone", ar: "الهاتف" }, kind: "text", half: true },
    { key: "email", label: { en: "Email", ar: "البريد" }, kind: "text", half: true },
    { key: "website", label: { en: "Website", ar: "الموقع" }, kind: "text", half: true },
    {
      key: "payment_terms_days",
      label: { en: "Payment terms (days)", ar: "مدة السداد (يوم)" },
      kind: "number",
      defaultValue: 30,
      half: true,
    },
    {
      key: "credit_limit",
      label: { en: "Credit limit (SAR)", ar: "حد الائتمان (ر.س)" },
      kind: "number",
      defaultValue: 0,
      half: true,
    },
    { key: "owner_id", label: { en: "Account owner", ar: "مسؤول الحساب" }, kind: "profile", half: true },
    {
      key: "status",
      label: { en: "Status", ar: "الحالة" },
      kind: "select",
      defaultValue: "active",
      half: true,
      options: [
        { value: "active", label: { en: "Active", ar: "نشط" } },
        { value: "inactive", label: { en: "Inactive", ar: "غير نشط" } },
      ],
    },
    { key: "address", label: { en: "Address", ar: "العنوان" }, kind: "textarea" },
    { key: "notes", label: { en: "Notes", ar: "ملاحظات" }, kind: "textarea" },
  ],
  searchKeys: ["name", "name_ar", "city", "vat_number", "phone", "email"],
};

export const Route = createFileRoute("/_authenticated/customers")({
  head: () => ({
    meta: [
      { title: "Customers — VINCO ERP" },
      {
        name: "description",
        content:
          "Manage Vision Contracting Co. client accounts, VAT and CR numbers, credit limits and account owners.",
      },
      { property: "og:title", content: "Customers — VINCO ERP" },
      { property: "og:description", content: "Client accounts, VAT details and credit limits." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
