import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";

import { AddVincoUserDialog } from "@/components/add-vinco-user-dialog";
import { ResourcePage, type ResourceConfig } from "@/components/resource-page";
import { Button } from "@/components/ui/button";
import { useMe } from "@/hooks/use-auth";
import { api } from "@/lib/api";
import { logAudit } from "@/lib/audit";
import { type Row } from "@/lib/db";
import { useI18n } from "@/lib/i18n";
import type { AppUser } from "@/lib/vinco-users";

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
//
// "Give VINCO access" per row (below) reuses `ResourceConfig`'s existing
// `extraRowActions` extension point -- no changes to the shared
// `ResourcePage`/`RecordDialog` components were needed for this.

/** One employee's VINCO-access action/status cell -- rendered via
 * `extraRowActions`, not a change to `ResourcePage` itself. */
function EmployeeVincoAccessCell({ employee, onLinked }: { employee: Row; onLinked: () => void }) {
  const { t } = useI18n();
  const me = useMe();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const canProvision = me.can("admin.users");

  const usersQuery = useQuery({
    queryKey: ["app-users"],
    enabled: canProvision,
    queryFn: () => api.get<AppUser[]>("/users"),
  });

  if (!canProvision) return null;

  const employeeId = Number(employee["id"]);
  const linked = (usersQuery.data ?? []).find((u) => u.employee_id === employeeId);

  if (!linked) {
    return (
      <>
        <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
          {t("users.give_access")}
        </Button>
        <AddVincoUserDialog
          open={open}
          onOpenChange={setOpen}
          defaultEmployeeId={employeeId}
          onCreated={(user) => {
            void queryClient.invalidateQueries({ queryKey: ["app-users"] });
            void logAudit({
              action: "user_created",
              entity_type: "app_users",
              entity_id: user.id,
              summary: `Created VINCO login ${user.username} for ${String(employee["full_name"] ?? "")}`,
            });
            onLinked();
          }}
        />
      </>
    );
  }

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className={linked.is_active ? "text-emerald-600" : "text-muted-foreground"}>
        {linked.is_active ? t("users.access_active") : t("users.access_inactive")}
      </span>
      <Button variant="ghost" size="sm" asChild>
        <Link to="/employees">
          {linked.is_active ? t("users.manage_access") : t("users.reactivate_access")}
        </Link>
      </Button>
    </div>
  );
}

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
  extraRowActions: (row, refresh) => <EmployeeVincoAccessCell employee={row} onLinked={refresh} />,
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
