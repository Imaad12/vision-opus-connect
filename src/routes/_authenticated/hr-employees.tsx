import { createFileRoute } from "@tanstack/react-router";

import { ResourcePage, type ResourceConfig } from "@/components/resource-page";

// A new page, not a rewire of the existing `/employees` route -- that
// route manages Supabase's own `profiles`/`user_roles`/`user_scopes`
// (app login identity and RBAC) and stays there deliberately, per the
// standing rule that Supabase remains the source of truth for auth/RBAC.
// This page is the real HR roster: the backend's `Employee` model
// (`/employees`), gated by the real `employees.view`/`employees.manage`
// permissions that existed in the `app_permission` enum but were unused
// until now (the old `/employees` page uses `admin.users`/`admin.roles`
// instead). Payroll (`PayrollRecord`, `/payroll-records`) has no page
// here yet -- see API_ARCHITECTURE.md Milestone 2 notes.
const config: ResourceConfig = {
  table: "hr_employees",
  title: { en: "Employees", ar: "الموظفون" },
  description: {
    en: "HR roster: roles, department and salary -- separate from application login access.",
    ar: "سجل الموارد البشرية: الوظائف والإدارات والرواتب -- منفصل عن صلاحيات الدخول للنظام.",
  },
  perms: {
    view: ["employees.view"],
    create: ["employees.manage"],
    edit: ["employees.manage"],
  },
  backend: { basePath: "/employees" },
  columns: [
    { key: "full_name", label: { en: "Name", ar: "الاسم" } },
    { key: "position", label: { en: "Position", ar: "الوظيفة" } },
    { key: "department", label: { en: "Department", ar: "الإدارة" } },
    { key: "phone", label: { en: "Phone", ar: "الهاتف" } },
    { key: "hire_date", label: { en: "Hire date", ar: "تاريخ التعيين" }, kind: "date" },
    { key: "employment_status", label: { en: "Status", ar: "الحالة" }, kind: "status" },
  ],
  fields: [
    {
      key: "full_name",
      label: { en: "Full name", ar: "الاسم الكامل" },
      kind: "text",
      required: true,
      half: true,
    },
    { key: "position", label: { en: "Position", ar: "الوظيفة" }, kind: "text", half: true },
    { key: "department", label: { en: "Department", ar: "الإدارة" }, kind: "text", half: true },
    { key: "phone", label: { en: "Phone", ar: "الهاتف" }, kind: "text", half: true },
    { key: "email", label: { en: "Email", ar: "البريد" }, kind: "text", half: true },
    { key: "hire_date", label: { en: "Hire date", ar: "تاريخ التعيين" }, kind: "date", half: true },
    {
      key: "termination_date",
      label: { en: "Termination date", ar: "تاريخ انتهاء الخدمة" },
      kind: "date",
      half: true,
    },
    {
      key: "employment_status",
      label: { en: "Status", ar: "الحالة" },
      kind: "select",
      defaultValue: "ACTIVE",
      half: true,
      options: [
        { value: "ACTIVE", label: { en: "Active", ar: "نشط" } },
        { value: "ON_LEAVE", label: { en: "On leave", ar: "في إجازة" } },
        { value: "TERMINATED", label: { en: "Terminated", ar: "منتهي الخدمة" } },
      ],
    },
    {
      key: "base_salary",
      label: { en: "Base salary", ar: "الراتب الأساسي" },
      kind: "number",
      half: true,
    },
    { key: "notes", label: { en: "Notes", ar: "ملاحظات" }, kind: "textarea" },
  ],
  searchKeys: ["full_name", "position", "department", "email"],
};

export const Route = createFileRoute("/_authenticated/hr-employees")({
  head: () => ({
    meta: [
      { title: "Employees — VINCO ERP" },
      {
        name: "description",
        content: "HR roster with department, hire date, status and base salary.",
      },
      { property: "og:title", content: "Employees — VINCO ERP" },
      { property: "og:description", content: "HR roster and employment status." },
    ],
  }),
  component: () => <ResourcePage config={config} />,
});
