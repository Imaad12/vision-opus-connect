import { createFileRoute } from "@tanstack/react-router";

import { ApprovalActions, ItemsButton } from "@/components/doc-actions";
import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

const config: ResourceConfig = {
  table: "quotations",
  title: { en: "Quotations", ar: "عروض الأسعار" },
  description: {
    en: "Priced offers with line items, VAT and two-person approval.",
    ar: "عروض مسعّرة مع البنود والضريبة واعتماد شخص ثانٍ.",
  },
  perms: {
    view: ["quotations.view"],
    create: ["quotations.create"],
    edit: ["quotations.edit"],
    remove: ["quotations.delete"],
  },
  columns: [
    { key: "quote_no", label: { en: "No.", ar: "الرقم" } },
    { key: "title", label: { en: "Title", ar: "العنوان" } },
    { key: "customer_id", label: { en: "Customer", ar: "العميل" }, kind: "ref" },
    { key: "total", label: { en: "Total", ar: "الإجمالي" }, kind: "money" },
    { key: "valid_until", label: { en: "Valid until", ar: "صالح حتى" }, kind: "date" },
    { key: "owner_id", label: { en: "Owner", ar: "المسؤول" }, kind: "ref" },
    { key: "status", label: { en: "Status", ar: "الحالة" }, kind: "status" },
  ],
  fields: [
    { key: "title", label: { en: "Quotation title", ar: "عنوان العرض" }, kind: "text", required: true },
    {
      key: "customer_id",
      label: { en: "Customer", ar: "العميل" },
      kind: "ref",
      ref: { table: "customers", labelCol: "name" },
      required: true,
      half: true,
    },
    {
      key: "lead_id",
      label: { en: "Linked lead", ar: "الفرصة المرتبطة" },
      kind: "ref",
      ref: { table: "leads", labelCol: "title" },
      half: true,
    },
    { key: "owner_id", label: { en: "Owner", ar: "المسؤول" }, kind: "profile", half: true },
    { key: "issue_date", label: { en: "Issue date", ar: "تاريخ الإصدار" }, kind: "date", half: true },
    { key: "valid_until", label: { en: "Valid until", ar: "صالح حتى" }, kind: "date", half: true },
    {
      key: "vat_rate",
      label: { en: "VAT rate %", ar: "نسبة الضريبة %" },
      kind: "number",
      defaultValue: 15,
      half: true,
    },
    {
      key: "discount_amount",
      label: { en: "Discount (SAR)", ar: "الخصم (ر.س)" },
      kind: "number",
      defaultValue: 0,
      half: true,
    },
    { key: "scope", label: { en: "Scope of work", ar: "نطاق العمل" }, kind: "textarea" },
    { key: "terms", label: { en: "Terms & conditions", ar: "الشروط والأحكام" }, kind: "textarea" },
    { key: "notes", label: { en: "Internal notes", ar: "ملاحظات داخلية" }, kind: "textarea" },
  ],
  searchKeys: ["quote_no", "title", "scope"],
  extraRowActions: (row, refresh) => (
    <>
      <ItemsButton
        row={row}
        parentTable="quotations"
        itemsTable="quotation_items"
        parentColumn="quotation_id"
        editable={String(row["status"]) === "draft"}
      />
      <ApprovalActions
        row={row}
        table="quotations"
        submitPerms={["quotations.create", "quotations.edit"]}
        approvePerms={["quotations.approve"]}
        refresh={refresh}
      />
    </>
  ),
};

export const Route = createFileRoute("/_authenticated/quotations")({
  head: () => ({
    meta: [
      { title: "Quotations — VINCO ERP" },
      {
        name: "description",
        content:
          "Build priced quotations with line items and 15% VAT, then route them for independent approval.",
      },
      { property: "og:title", content: "Quotations — VINCO ERP" },
      { property: "og:description", content: "Priced offers with VAT and approval workflow." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
