import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { NoAccess, PageHeader } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { db } from "@/lib/db";
import { logAudit } from "@/lib/audit";
import { useMe } from "@/hooks/use-auth";
import { useI18n } from "@/lib/i18n";
import type { Tables, TablesUpdate } from "@/integrations/supabase/types";

/**
 * Real, editable Super Admin settings center -- was pure display text
 * (hardcoded rows) until now.
 *
 * Backed by `public.company_settings` (a real, seeded Supabase table --
 * see `supabase/migrations/20260818103802_*.sql`), NOT
 * `backend/app/models/company.py`'s `Company` (a different, unrelated
 * single-row table with no VAT field, used only by the desktop-era
 * financial engine, and with no read/write path from this frontend at
 * all). Read/write goes straight through the Supabase client + RLS
 * (`company_settings_select`/`company_settings_update`, both already
 * gated `admin.settings` -- see that migration), exactly like every
 * other generic CRUD screen in this app (`resource-page.tsx`) -- no new
 * backend endpoint needed, and this page's own `me.can("admin.settings")`
 * gate below matches the RLS policy exactly rather than duplicating a
 * looser or stricter rule client-side.
 *
 * Document numbering (`next_doc_number()`/`doc_counters`) and
 * separation-of-duties approval rules are real, live systems (see that
 * same migration) but are NOT stored as editable data anywhere --
 * numbering's format is a literal in a SECURITY DEFINER SQL function,
 * and SoD is enforced by fixed DB triggers, not a rule table. Making
 * either configurable would need a real schema change to a function
 * that already generates real, live document numbers -- out of scope
 * here (see this session's own report); both are shown below as
 * accurate, read-only system information instead of fabricated form
 * fields.
 */
export const Route = createFileRoute("/_authenticated/settings/")({
  head: () => ({
    meta: [
      { title: "Company settings — VINCO ERP" },
      {
        name: "description",
        content:
          "Company identity, VAT rate and document numbering conventions used across VINCO ERP.",
      },
      { property: "og:title", content: "Company settings — VINCO ERP" },
      { property: "og:description", content: "Company identity, VAT rate and numbering." },
    ],
  }),
  component: SettingsPage,
});

type CompanySettings = Tables<"company_settings">;

function SettingsPage() {
  const { t } = useI18n();
  const me = useMe();

  if (!me.can("admin.settings")) {
    return (
      <>
        <PageHeader title={t("nav.settings")} />
        <NoAccess />
      </>
    );
  }

  return <CompanySettingsPanel />;
}

function CompanySettingsPanel() {
  const { t } = useI18n();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["company-settings"],
    queryFn: async (): Promise<CompanySettings> => {
      const { data, error } = await db.from("company_settings").select("*").limit(1).maybeSingle();
      if (error) throw error;
      if (!data) throw new Error("No company_settings row found.");
      return data as CompanySettings;
    },
  });

  return (
    <>
      <PageHeader title={t("nav.settings")} />

      {query.isLoading && (
        <div className="surface-panel p-8 text-center text-sm text-muted-foreground">
          {t("common.loading")}
        </div>
      )}

      {query.isError && (
        <div className="surface-panel p-8 text-center text-sm text-destructive">
          {t("common.load_failed")}:{" "}
          {query.error instanceof Error ? query.error.message : String(query.error)}
        </div>
      )}

      {query.data && (
        <div className="space-y-6">
          <CompanySettingsForm
            key={query.data.id}
            settings={query.data}
            onSaved={() => void queryClient.invalidateQueries({ queryKey: ["company-settings"] })}
          />
          <SystemInfoPanel />
        </div>
      )}
    </>
  );
}

function CompanySettingsForm({
  settings,
  onSaved,
}: {
  settings: CompanySettings;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const [form, setForm] = useState({
    company_name: settings.company_name,
    company_name_ar: settings.company_name_ar,
    vat_number: settings.vat_number ?? "",
    cr_number: settings.cr_number ?? "",
    address: settings.address ?? "",
    city: settings.city ?? "",
    phone: settings.phone ?? "",
    email: settings.email ?? "",
    currency: settings.currency,
    default_vat_rate: String(settings.default_vat_rate),
  });
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      const vatRate = Number(form.default_vat_rate);
      if (!Number.isFinite(vatRate) || vatRate < 0 || vatRate > 100) {
        throw new Error(t("settings.vat_rate_invalid"));
      }
      const payload: TablesUpdate<"company_settings"> = {
        company_name: form.company_name.trim(),
        company_name_ar: form.company_name_ar.trim(),
        vat_number: form.vat_number.trim() || null,
        cr_number: form.cr_number.trim() || null,
        address: form.address.trim() || null,
        city: form.city.trim() || null,
        phone: form.phone.trim() || null,
        email: form.email.trim() || null,
        currency: form.currency.trim().toUpperCase(),
        default_vat_rate: vatRate,
      };
      const { error: updateError } = await db
        .from("company_settings")
        .update(payload)
        .eq("id", settings.id);
      if (updateError) throw updateError;
      await logAudit({
        action: "update",
        entity_type: "company_settings",
        entity_id: settings.id,
        summary: "Updated company settings",
        before_data: settings,
        after_data: payload,
      });
    },
    onSuccess: () => {
      toast.success(t("common.saved"));
      onSaved();
    },
    onError: (e: unknown) => {
      const message = e instanceof Error ? e.message : String(e);
      setError(message);
      toast.error(message);
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    mutation.mutate();
  };

  const field = (key: keyof typeof form, label: string, opts: { type?: string } = {}) => (
    <div className="space-y-1.5">
      <Label htmlFor={`company-settings-${key}`}>{label}</Label>
      <Input
        id={`company-settings-${key}`}
        type={opts.type ?? "text"}
        value={form[key]}
        onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
      />
    </div>
  );

  return (
    <form className="surface-panel space-y-6 p-4" onSubmit={handleSubmit}>
      <div className="grid gap-4 sm:grid-cols-2">
        {field("company_name", t("settings.company_name"))}
        {field("company_name_ar", t("settings.company_name_ar"))}
        {field("cr_number", t("settings.cr_number"))}
        {field("vat_number", t("settings.vat_number"))}
        {field("currency", t("settings.currency"))}
        <div className="space-y-1.5">
          <Label htmlFor="company-settings-default_vat_rate">{t("settings.vat_rate")}</Label>
          <Input
            id="company-settings-default_vat_rate"
            type="number"
            min={0}
            max={100}
            step="0.01"
            value={form.default_vat_rate}
            onChange={(e) => setForm((f) => ({ ...f, default_vat_rate: e.target.value }))}
          />
        </div>
        {field("phone", t("settings.phone"))}
        {field("email", t("settings.email"), { type: "email" })}
        {field("city", t("settings.city"))}
        {field("address", t("settings.address"))}
      </div>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      <div className="flex justify-end">
        <Button type="submit" disabled={mutation.isPending} className="gap-2">
          {mutation.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
          {t("common.save")}
        </Button>
      </div>
    </form>
  );
}

/** Numbering and approval rules: real, live systems (see this file's
 * top docstring), just not stored as editable data anywhere yet --
 * shown as accurate read-only information rather than fabricated as
 * editable fields. */
function SystemInfoPanel() {
  const { t } = useI18n();
  const rows = [
    { label: t("settings.quotation_numbering"), value: "QT-YYYY-####" },
    { label: t("settings.po_numbering"), value: "PO-YYYY-####" },
    { label: t("settings.invoice_numbering"), value: "INV-YYYY-####" },
    { label: t("settings.approval_rule"), value: t("settings.approval_rule_value") },
  ];
  return (
    <div className="surface-panel">
      <div className="border-b border-border px-4 py-3">
        <p className="text-sm font-medium">{t("settings.system_info_title")}</p>
        <p className="text-xs text-muted-foreground">{t("settings.system_info_description")}</p>
      </div>
      <div className="divide-y divide-border">
        {rows.map((r) => (
          <div
            key={r.label}
            className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm"
          >
            <span className="text-muted-foreground">{r.label}</span>
            <span className="font-medium">{r.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
