import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import {
  BadgeCheck,
  Building2,
  ClipboardList,
  Contact,
  FileSignature,
  FileStack,
  FileText,
  Handshake,
  LayoutDashboard,
  Languages,
  LogOut,
  Menu,
  Percent,
  Receipt,
  ScrollText,
  Settings,
  ShieldCheck,
  ShoppingCart,
  Target,
  TrendingUp,
  Truck,
  Users,
  Wallet,
  X,
} from "lucide-react";
import { useState, type ReactNode } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { supabase } from "@/integrations/supabase/client";
import { ROLE_LABELS, useMe } from "@/hooks/use-auth";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type NavItem = {
  to: string;
  labelKey: string;
  icon: typeof Users;
  perms: string[];
};

type NavSection = { titleKey: string; items: NavItem[] };

const SECTIONS: NavSection[] = [
  {
    titleKey: "nav.dashboard",
    items: [{ to: "/dashboard", labelKey: "nav.dashboard", icon: LayoutDashboard, perms: [] }],
  },
  {
    titleKey: "nav.crm",
    items: [
      { to: "/customers", labelKey: "nav.customers", icon: Building2, perms: ["customers.view"] },
      { to: "/contacts", labelKey: "nav.contacts", icon: Contact, perms: ["contacts.view"] },
      { to: "/leads", labelKey: "nav.leads", icon: Target, perms: ["leads.view"] },
    ],
  },
  {
    titleKey: "nav.sales",
    items: [
      {
        to: "/quotations",
        labelKey: "nav.quotations",
        icon: FileText,
        perms: ["quotations.view"],
      },
      {
        to: "/approvals",
        labelKey: "nav.approvals",
        icon: BadgeCheck,
        perms: ["quotations.approve", "quotations.edit", "purchasing.po_approve"],
      },
    ],
  },
  {
    titleKey: "nav.delivery",
    items: [
      { to: "/projects", labelKey: "nav.projects", icon: ClipboardList, perms: ["projects.view"] },
      {
        to: "/contracts",
        labelKey: "nav.contracts",
        icon: FileSignature,
        perms: ["contracts.view"],
      },
    ],
  },
  {
    titleKey: "nav.procurement",
    items: [
      { to: "/suppliers", labelKey: "nav.suppliers", icon: Truck, perms: ["suppliers.view"] },
      {
        to: "/purchase-orders",
        labelKey: "nav.purchase_orders",
        icon: ShoppingCart,
        perms: ["purchasing.po_create", "purchasing.po_approve", "purchasing.request"],
      },
    ],
  },
  {
    titleKey: "nav.finance",
    items: [
      {
        to: "/invoices",
        labelKey: "nav.invoices",
        icon: Receipt,
        perms: ["finance.invoices", "finance.reports"],
      },
      {
        to: "/payments",
        labelKey: "nav.payments",
        icon: Wallet,
        perms: ["finance.payments", "finance.reports"],
      },
      {
        to: "/expenses",
        labelKey: "nav.expenses",
        icon: Handshake,
        perms: ["finance.expenses", "finance.reports"],
      },
      { to: "/vat", labelKey: "nav.vat", icon: Percent, perms: ["finance.vat", "finance.reports"] },
    ],
  },
  {
    titleKey: "nav.management",
    items: [
      {
        to: "/management",
        labelKey: "nav.management",
        icon: TrendingUp,
        perms: ["finance.reports"],
      },
    ],
  },
  {
    titleKey: "nav.people",
    items: [
      {
        to: "/hr-employees",
        labelKey: "nav.hr_employees",
        icon: Users,
        perms: ["employees.view"],
      },
    ],
  },
  {
    titleKey: "nav.documents",
    items: [
      { to: "/documents", labelKey: "nav.documents", icon: FileStack, perms: ["documents.view"] },
    ],
  },
  {
    titleKey: "nav.administration",
    items: [
      {
        to: "/employees",
        labelKey: "nav.employees",
        icon: ShieldCheck,
        perms: ["employees.view", "admin.users", "admin.roles"],
      },
      {
        to: "/settings/users",
        labelKey: "nav.users_access",
        icon: ShieldCheck,
        perms: ["admin.users"],
      },
      { to: "/audit-logs", labelKey: "nav.audit", icon: ScrollText, perms: ["admin.audit"] },
      { to: "/settings", labelKey: "nav.settings", icon: Settings, perms: ["admin.settings"] },
    ],
  },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { t, lang, toggle } = useI18n();
  const me = useMe();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const [mobileOpen, setMobileOpen] = useState(false);

  const handleSignOut = async () => {
    await queryClient.cancelQueries();
    queryClient.clear();
    await supabase.auth.signOut();
    navigate({ to: "/", replace: true });
  };

  const visibleSections = SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((i) => i.perms.length === 0 || me.canAny(i.perms)),
  })).filter((s) => s.items.length > 0);

  const initials = (me.profile?.full_name || me.profile?.email || "V")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  const nav = (
    <nav className="flex h-full flex-col gap-6 overflow-y-auto px-3 py-5">
      <div className="flex items-center gap-3 px-2">
        <div className="grid size-9 place-items-center rounded-md bg-sidebar-primary text-sm font-bold text-sidebar-primary-foreground">
          VC
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-sidebar-foreground">{t("app.short")}</p>
          <p className="truncate text-xs text-sidebar-foreground/60">{t("app.name")}</p>
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-5">
        {visibleSections.map((section) => (
          <div key={section.titleKey}>
            <p className="px-2 pb-1.5 text-[0.68rem] font-semibold uppercase tracking-wider text-sidebar-foreground/45">
              {t(section.titleKey)}
            </p>
            <ul className="space-y-0.5">
              {section.items.map((item) => {
                const active = pathname.startsWith(item.to);
                const Icon = item.icon;
                return (
                  <li key={item.to}>
                    <Link
                      to={item.to}
                      onClick={() => setMobileOpen(false)}
                      className={cn(
                        "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors",
                        active
                          ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                          : "text-sidebar-foreground/75 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
                      )}
                    >
                      <Icon className="size-4 shrink-0" />
                      <span className="truncate">{t(item.labelKey)}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </nav>
  );

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="hidden w-64 shrink-0 border-e border-sidebar-border bg-sidebar lg:block">
        <div className="sticky top-0 h-screen">{nav}</div>
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <div
            className="absolute inset-0 bg-foreground/50"
            onClick={() => setMobileOpen(false)}
            aria-hidden
          />
          <aside className="relative z-10 w-64 bg-sidebar">
            <Button
              variant="ghost"
              size="icon"
              className="absolute end-2 top-2 text-sidebar-foreground"
              onClick={() => setMobileOpen(false)}
            >
              <X className="size-4" />
            </Button>
            {nav}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-card/85 px-4 backdrop-blur">
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={() => setMobileOpen(true)}
          >
            <Menu className="size-5" />
          </Button>

          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              {me.profile?.full_name || t("app.short")}
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {me.roles.map((r) => ROLE_LABELS[r]?.[lang] ?? r).join(" · ") || "—"}
            </p>
          </div>

          <Button variant="outline" size="sm" onClick={toggle} className="gap-1.5">
            <Languages className="size-4" />
            {t("common.language")}
          </Button>

          <Avatar className="size-8">
            <AvatarFallback className="bg-primary text-xs text-primary-foreground">
              {initials}
            </AvatarFallback>
          </Avatar>

          <Button variant="ghost" size="icon" onClick={handleSignOut} title={t("auth.signout")}>
            <LogOut className="size-4" />
          </Button>
        </header>

        <main className="min-w-0 flex-1 p-4 lg:p-6">{children}</main>
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string | undefined;
  actions?: ReactNode | undefined;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function NoAccess() {
  const { t } = useI18n();
  return (
    <div className="surface-panel grid min-h-52 place-items-center p-8 text-center">
      <div>
        <ShieldCheck className="mx-auto mb-3 size-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">{t("common.no_access")}</p>
      </div>
    </div>
  );
}
