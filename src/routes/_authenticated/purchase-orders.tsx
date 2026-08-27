import { createFileRoute } from "@tanstack/react-router";

import { ApprovalActions, ItemsButton } from "@/components/doc-actions";
import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

const config: ResourceConfig = {
  table: "purchase_orders",
  title: { en: "Purchase orders", ar: "أوامر الشراء" },
  description: {
    en: "Supplier orders with line items, VAT and independent approval.",
    ar: "أوامر الموردين مع البنود والضريبة واعتماد مستقل.",
  },
  perms: {
    view: ["purchasing.po_create", "purchasing.po_approve", "purchasing.request"],
    create: ["purchasing.po_create"],
    edit: ["purchasing.po_create", "purchasing.po_approve", "purchasing.receive"],
    remove: ["purchasing.po_approve"],
  },
  columns: [
    { key: "po_no", label: { en: "No.", ar: "الرقم" } },
    { key: "supplier_id", label: { en: "Supplier", ar: "المورد" }, kind: "ref" },
    { key: "project_id", label: { en: "Project", ar: "المشروع" }, kind: "ref" },
    { key: "total", label: { en: "Total", ar: "الإجمالي" }, kind: "money" },
    { key: "expected_delivery", label: { en: "Expected", ar: "التسليم المتوقع" }, kind: "date" },
    { key: "status", label: { en: "Status", ar: "الحالة" }, kind: "status" },
  ],
  fields: [
    {
      key: "supplier_id",
      label: { en: "Supplier", ar: "المورد" },
      kind: "ref",
      ref: { table: "suppliers", labelCol: "name" },
      required: true,
      half: true,
    },
    {
      key: "project_id",
      label: { en: "Project", ar: "المشروع" },
      kind: "ref",
      ref: { table: "projects", labelCol: "name" },
      half: true,
    },
    { key: "order_date", label: { en: "Order date", ar: "تاريخ الأمر" }, kind: "date", half: true },
    {
      key: "expected_delivery",
      label: { en: "Expected delivery", ar: "التسليم المتوقع" },
      kind: "date",
      half: true,
    },
    { key: "vat_rate", label: { en: "VAT rate %", ar: "نسبة الضريبة %" }, kind: "number", defaultValue: 15, half: true },
    { key: "notes", label: { en: "Notes", ar: "ملاحظات" }, kind: "textarea" },
  ],
  searchKeys: ["po_no", "notes"],
  extraRowActions: (row, refresh) => (
    <>
      <ItemsButton
        row={row}
        parentTable="purchase_orders"
        itemsTable="purchase_order_items"
        parentColumn="purchase_order_id"
        editable={String(row["status"]) === "draft"}
      />
      <ApprovalActions
        row={row}
        table="purchase_orders"
        submitPerms={["purchasing.po_create", "purchasing.receive"]}
        approvePerms={["purchasing.po_approve"]}
        refresh={refresh}
      />
    </>
  ),
};

export const Route = createFileRoute("/_authenticated/purchase-orders")({
  head: () => ({
    meta: [
      { title: "Purchase orders — VINCO ERP" },
      {
        name: "description",
        content: "Raise supplier purchase orders with line items, VAT and separation-of-duties approval.",
      },
      { property: "og:title", content: "Purchase orders — VINCO ERP" },
      { property: "og:description", content: "Supplier orders with VAT and approval controls." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
