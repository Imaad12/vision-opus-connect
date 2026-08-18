import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

const config: ResourceConfig = {
  table: "documents",
  title: { en: "Documents", ar: "المستندات" },
  description: {
    en: "Controlled document register with versions and approvals.",
    ar: "سجل المستندات مع الإصدارات والاعتمادات.",
  },
  perms: {
    view: ["documents.view"],
    create: ["documents.upload"],
    edit: ["documents.edit"],
    remove: ["documents.delete"],
  },
  columns: [
    { key: "title", label: { en: "Title", ar: "العنوان" } },
    { key: "category", label: { en: "Category", ar: "التصنيف" } },
    { key: "project_id", label: { en: "Project", ar: "المشروع" }, kind: "ref" },
    { key: "version", label: { en: "Version", ar: "الإصدار" }, kind: "number" },
    { key: "status", label: { en: "Status", ar: "الحالة" }, kind: "status" },
    { key: "created_at", label: { en: "Uploaded", ar: "تاريخ الرفع" }, kind: "date" },
  ],
  fields: [
    { key: "title", label: { en: "Title", ar: "العنوان" }, kind: "text", required: true },
    {
      key: "category",
      label: { en: "Category", ar: "التصنيف" },
      kind: "select",
      defaultValue: "general",
      half: true,
      options: [
        { value: "general", label: { en: "General", ar: "عام" } },
        { value: "drawing", label: { en: "Drawing", ar: "مخطط" } },
        { value: "contract", label: { en: "Contract", ar: "عقد" } },
        { value: "permit", label: { en: "Permit", ar: "تصريح" } },
        { value: "invoice", label: { en: "Invoice", ar: "فاتورة" } },
        { value: "report", label: { en: "Report", ar: "تقرير" } },
      ],
    },
    {
      key: "project_id",
      label: { en: "Project", ar: "المشروع" },
      kind: "ref",
      ref: { table: "projects", labelCol: "name" },
      half: true,
    },
    { key: "storage_path", label: { en: "Storage path / link", ar: "مسار الحفظ / الرابط" }, kind: "text", required: true },
    { key: "file_name", label: { en: "File name", ar: "اسم الملف" }, kind: "text", half: true },
    { key: "version", label: { en: "Version", ar: "الإصدار" }, kind: "number", defaultValue: 1, half: true },
    { key: "notes", label: { en: "Notes", ar: "ملاحظات" }, kind: "textarea" },
  ],
  searchKeys: ["title", "category", "file_name"],
};

export const Route = createFileRoute("/_authenticated/documents")({
  head: () => ({
    meta: [
      { title: "Documents — VINCO ERP" },
      {
        name: "description",
        content: "Controlled register of drawings, contracts, permits and reports with version and approval tracking.",
      },
      { property: "og:title", content: "Documents — VINCO ERP" },
      { property: "og:description", content: "Document control with versions and approvals." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
