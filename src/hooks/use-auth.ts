import { queryOptions, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { supabase } from "@/integrations/supabase/client";
import { ApiError, api } from "@/lib/api";
import type { AppUserSelf } from "@/lib/vinco-users";

export type AppRole =
  | "super_admin"
  | "general_manager"
  | "sales"
  | "estimation"
  | "project_manager"
  | "procurement"
  | "finance"
  | "hr_admin"
  | "document_controller"
  | "employee"
  | "viewer";

export type Profile = {
  id: string;
  full_name: string;
  email: string | null;
  job_title: string | null;
  department: string | null;
  avatar_url: string | null;
  is_active: boolean;
};

export function useSessionUser() {
  const [userId, setUserId] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    void supabase.auth.getUser().then(({ data }) => {
      if (!active) return;
      setUserId(data.user?.id ?? null);
      setReady(true);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) => {
      setUserId(session?.user?.id ?? null);
    });
    return () => {
      active = false;
      sub.subscription.unsubscribe();
    };
  }, []);

  return { userId, ready };
}

/**
 * Query definition for `useMe()`'s profile/roles/permissions fetch,
 * factored out (react-query's own `queryOptions()` helper) so a route
 * loader can `queryClient.ensureQueryData(meQueryOptions(userId))` to
 * prime the exact same cache entry ahead of a page mounting -- e.g. on
 * nav-link hover, via TanStack Router's `defaultPreloadStaleTime`
 * (router.tsx) -- without duplicating this query's definition and
 * risking it drifting from what `useMe()` itself fetches.
 */
export function meQueryOptions(userId: string | null) {
  return queryOptions({
    queryKey: ["me", userId],
    enabled: Boolean(userId),
    queryFn: async () => {
      const [profileRes, rolesRes, permsRes, overridesRes, scopeRes] = await Promise.all([
        supabase.from("profiles").select("*").eq("id", userId!).maybeSingle(),
        supabase.from("user_roles").select("role").eq("user_id", userId!),
        supabase.from("role_permissions").select("role, permission"),
        supabase.from("user_permissions").select("permission, granted").eq("user_id", userId!),
        supabase.from("user_scopes").select("scope").eq("user_id", userId!).maybeSingle(),
      ]);

      const roles = (rolesRes.data ?? []).map((r) => r.role as AppRole);
      const rolePerms = new Set<string>(
        (permsRes.data ?? [])
          .filter((rp) => roles.includes(rp.role as AppRole))
          .map((rp) => rp.permission as string),
      );
      for (const o of overridesRes.data ?? []) {
        if (o.granted) rolePerms.add(o.permission as string);
        else rolePerms.delete(o.permission as string);
      }
      const isSuper = roles.includes("super_admin");
      const allPerms = new Set<string>(
        isSuper ? (permsRes.data ?? []).map((rp) => rp.permission as string) : [],
      );

      return {
        userId: userId!,
        profile: (profileRes.data ?? null) as Profile | null,
        roles,
        permissions: isSuper ? allPerms : rolePerms,
        scope: (scopeRes.data?.scope ?? "assigned") as "all" | "assigned" | "own",
        isSuper,
      };
    },
  });
}

/**
 * Query definition for `GET /users/me` -- the caller's own native VINCO
 * login row, if any (see `AppUserSelf`). Shared, so the forced
 * first-login gate (`forced-password-change-gate.tsx`) and the
 * self-service Change Password dialog resolve the exact same cache
 * entry rather than issuing two independent fetches, and so a
 * successful password change (either flow) only needs to invalidate
 * this one key.
 */
export function ownAppUserQueryOptions() {
  return queryOptions({
    queryKey: ["users-me"],
    queryFn: async (): Promise<AppUserSelf | null> => {
      try {
        return await api.get<AppUserSelf>("/users/me");
      } catch (e) {
        // No native VINCO login (e.g. a legacy/Google-linked account) --
        // not an error condition for anything that reads this.
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
    staleTime: Infinity,
    retry: 1,
  });
}

export function useOwnAppUser() {
  return useQuery(ownAppUserQueryOptions());
}

export function useMe() {
  const { userId, ready } = useSessionUser();

  const query = useQuery(meQueryOptions(userId));

  const permissions = query.data?.permissions ?? new Set<string>();

  return {
    ready,
    userId,
    isLoading: query.isLoading,
    profile: query.data?.profile ?? null,
    roles: query.data?.roles ?? [],
    scope: query.data?.scope ?? "assigned",
    isSuper: query.data?.isSuper ?? false,
    can: (perm: string) => permissions.has(perm),
    canAny: (perms: string[]) => perms.some((p) => permissions.has(p)),
    permissions,
  };
}

export const ROLE_LABELS: Record<AppRole, { en: string; ar: string }> = {
  super_admin: { en: "Super Admin", ar: "مسؤول النظام" },
  general_manager: { en: "General Manager", ar: "المدير العام" },
  sales: { en: "Sales / Business Development", ar: "المبيعات وتطوير الأعمال" },
  estimation: { en: "Estimation / Tendering", ar: "التسعير والمناقصات" },
  project_manager: { en: "Project Manager", ar: "مدير مشروع" },
  procurement: { en: "Procurement", ar: "المشتريات" },
  finance: { en: "Finance / Accountant", ar: "المالية والمحاسبة" },
  hr_admin: { en: "HR / Admin", ar: "الموارد البشرية والإدارة" },
  document_controller: { en: "Document Controller", ar: "مراقب المستندات" },
  employee: { en: "Employee / Staff", ar: "موظف" },
  viewer: { en: "Viewer / Auditor", ar: "مراجع (قراءة فقط)" },
};

export const PERMISSION_GROUPS: { key: string; en: string; ar: string; permissions: string[] }[] = [
  {
    key: "customers",
    en: "Customers & contacts",
    ar: "العملاء وجهات الاتصال",
    permissions: [
      "customers.view",
      "customers.create",
      "customers.edit",
      "customers.delete",
      "contacts.view",
      "contacts.create",
      "contacts.edit",
      "contacts.delete",
    ],
  },
  {
    key: "leads",
    en: "Leads / CRM",
    ar: "الفرص البيعية",
    permissions: ["leads.view", "leads.create", "leads.edit", "leads.assign", "leads.close"],
  },
  {
    key: "quotations",
    en: "Quotations",
    ar: "عروض الأسعار",
    permissions: [
      "quotations.view",
      "quotations.create",
      "quotations.edit",
      "quotations.submit",
      "quotations.approve",
      "quotations.reject",
      "quotations.send",
      "quotations.delete",
    ],
  },
  {
    key: "projects",
    en: "Projects & contracts",
    ar: "المشاريع والعقود",
    permissions: [
      "projects.view",
      "projects.create",
      "projects.edit",
      "projects.archive",
      "contracts.view",
      "contracts.create",
      "contracts.edit",
      "contracts.delete",
    ],
  },
  {
    key: "purchasing",
    en: "Purchasing",
    ar: "المشتريات",
    permissions: [
      "suppliers.view",
      "suppliers.create",
      "suppliers.edit",
      "suppliers.delete",
      "purchasing.rfq",
      "purchasing.request",
      "purchasing.po_create",
      "purchasing.po_approve",
      "purchasing.receive",
    ],
  },
  {
    key: "finance",
    en: "Finance",
    ar: "المالية",
    permissions: [
      "finance.invoices",
      "finance.payments",
      "finance.expenses",
      "finance.vat",
      "finance.reports",
    ],
  },
  {
    key: "documents",
    en: "Documents",
    ar: "المستندات",
    permissions: [
      "documents.view",
      "documents.upload",
      "documents.download",
      "documents.delete",
      "documents.approve",
      "documents.versions",
    ],
  },
  {
    key: "admin",
    en: "Administration",
    ar: "الإدارة",
    permissions: [
      "employees.view",
      "employees.manage",
      "admin.users",
      "admin.roles",
      "admin.settings",
      "admin.audit",
    ],
  },
];
