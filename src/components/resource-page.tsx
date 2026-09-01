import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Search, Trash2 } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { NoAccess, PageHeader } from "@/components/app-shell";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useMe } from "@/hooks/use-auth";
import { ApiError, api } from "@/lib/api";
import { logAudit } from "@/lib/audit";
import { db, type Row } from "@/lib/db";
import { formatDate, formatMoney, useI18n, type Lang } from "@/lib/i18n";

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.describe();
  if (e instanceof Error) return e.message;
  if (e && typeof e === "object" && "message" in e)
    return String((e as { message: unknown }).message);
  return String(e);
}

export type Bilingual = { en: string; ar: string };

export type ColumnDef = {
  key: string;
  label: Bilingual;
  kind?: "text" | "money" | "date" | "status" | "number" | "percent" | "ref" | "bool";
  refLabel?: Record<string, string> | undefined;
};

export type FieldDef = {
  key: string;
  label: Bilingual;
  kind: "text" | "textarea" | "number" | "date" | "select" | "ref" | "profile" | "bool";
  options?: { value: string; label: Bilingual }[];
  refTable?: string;
  refLabelColumn?: string;
  // `backendPath` sources this ref's dropdown options from our own API
  // instead of Supabase -- required whenever the referenced resource has
  // itself been cut over (its real ids no longer exist in the Supabase
  // table `table` would otherwise query).
  ref?: { table: string; labelCol?: string; backendPath?: string };
  required?: boolean;
  defaultValue?: string | number | null;
  half?: boolean;
};

/**
 * When set, this resource is served by our own FastAPI backend
 * (`basePath`, e.g. "/vendors") instead of Supabase's `table`. `table` is
 * still used as the react-query cache key. Payload shape is intentionally
 * NOT remapped here: `columns`/`fields` for a backend-backed resource use
 * the API's real field names directly (see suppliers.tsx/projects.tsx),
 * so no frontend<->backend translation layer is needed or hidden here.
 * There is deliberately no `remove` support until a DELETE endpoint
 * exists -- omit `perms.remove` for these resources rather than wiring a
 * button to nothing.
 */
export type BackendSource = { basePath: string };

export type ResourceConfig = {
  table: string;
  title: Bilingual;
  description?: Bilingual;
  perms: { view: string[]; create?: string[]; edit?: string[]; remove?: string[] };
  columns: ColumnDef[];
  fields: FieldDef[];
  searchKeys: string[];
  orderBy?: string;
  extraRowActions?: (row: Row, refresh: () => void) => ReactNode;
  toolbar?: ReactNode;
  backend?: BackendSource;
};

function cellValue(row: Row, col: ColumnDef, lang: Lang) {
  const raw = row[col.key];
  switch (col.kind) {
    case "money":
      return <span className="num">{formatMoney(Number(raw ?? 0), lang)}</span>;
    case "date":
      return formatDate(raw as string, lang);
    case "status":
      return <StatusBadge value={raw as string} />;
    case "number":
      return <span className="num">{Number(raw ?? 0).toLocaleString()}</span>;
    case "percent":
      return <span className="num">{Number(raw ?? 0)}%</span>;
    case "bool":
      return raw ? "✓" : "—";
    case "ref":
      return col.refLabel?.[String(raw ?? "")] ?? "—";
    default:
      if (col.refLabel) return col.refLabel[String(raw ?? "")] ?? "—";
      return raw == null || raw === "" ? "—" : String(raw);
  }
}

export function ResourcePage({ config }: { config: ResourceConfig }) {
  const { lang, t } = useI18n();
  const me = useMe();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<Row | null>(null);
  const [open, setOpen] = useState(false);

  const canView = me.canAny(config.perms.view);
  const canCreate = config.perms.create ? me.canAny(config.perms.create) : false;
  const canEdit = config.perms.edit ? me.canAny(config.perms.edit) : false;
  const canRemove = config.perms.remove ? me.canAny(config.perms.remove) : false;

  const listQuery = useQuery({
    queryKey: ["resource", config.table],
    enabled: canView,
    queryFn: async () => {
      if (config.backend) {
        return await api.get<Row[]>(config.backend.basePath);
      }
      const { data, error } = await db
        .from(config.table)
        .select("*")
        .order(config.orderBy ?? "created_at", { ascending: false })
        .limit(500);
      if (error) throw error;
      return (data ?? []) as Row[];
    },
  });

  const refFields = config.fields.filter((f) => f.kind === "ref" || f.kind === "profile");
  const refQuery = useQuery({
    queryKey: [
      "resource-refs",
      config.table,
      refFields.map((f) => f.refTable ?? f.ref?.table ?? "profiles"),
    ],
    enabled: canView && refFields.length > 0,
    queryFn: async () => {
      const out: Record<string, { id: string; label: string }[]> = {};
      for (const f of refFields) {
        if (f.ref?.backendPath) {
          const labelCol = f.ref.labelCol ?? "name";
          const rows = await api.get<Row[]>(f.ref.backendPath);
          out[f.key] = rows.map((r) => ({ id: String(r["id"]), label: String(r[labelCol] ?? "") }));
          continue;
        }
        const table =
          f.kind === "profile" ? "profiles" : (f.refTable ?? f.ref?.table ?? "profiles");
        const labelCol =
          f.kind === "profile" ? "full_name" : (f.refLabelColumn ?? f.ref?.labelCol ?? "name");
        const { data } = await db.from(table).select(`id, ${labelCol}`).limit(500);
        out[f.key] = ((data ?? []) as unknown as Row[]).map((r) => ({
          id: String(r["id"]),
          label: String(r[labelCol] ?? ""),
        }));
      }
      return out;
    },
  });

  const refLabels = useMemo(() => {
    const map: Record<string, Record<string, string>> = {};
    for (const [key, list] of Object.entries(refQuery.data ?? {})) {
      map[key] = Object.fromEntries(list.map((o) => [o.id, o.label]));
    }
    return map;
  }, [refQuery.data]);

  const saveMutation = useMutation({
    mutationFn: async (values: Row) => {
      const payload: Row = {};
      for (const field of config.fields) {
        const v = values[field.key];
        if (field.kind === "bool") {
          payload[field.key] = Boolean(v);
          continue;
        }
        payload[field.key] = v === "" || v === undefined ? null : v;
      }

      if (config.backend) {
        // Backend-owned resources don't have a Supabase audit_logs entry
        // written for them here -- that trail belongs on the backend
        // itself once it has one (see API_ARCHITECTURE.md), not
        // half-duplicated into Supabase's audit log from the frontend.
        if (editing?.["id"]) {
          await api.put(`${config.backend.basePath}/${String(editing["id"])}`, payload);
        } else {
          await api.post(config.backend.basePath, payload);
        }
        return;
      }

      if (editing?.["id"]) {
        const { error } = await db
          .from(config.table)
          .update(payload)
          .eq("id", String(editing["id"]));
        if (error) throw error;
        await logAudit({
          action: "update",
          entity_type: config.table,
          entity_id: String(editing["id"]),
          summary: `Updated ${config.table} record`,
          before_data: editing,
          after_data: payload,
        });
      } else {
        const { data, error } = await db.from(config.table).insert(payload).select("id").single();
        if (error) throw error;
        await logAudit({
          action: "create",
          entity_type: config.table,
          entity_id: data ? String((data as Row)["id"]) : null,
          summary: `Created ${config.table} record`,
          after_data: payload,
        });
      }
    },
    onSuccess: () => {
      toast.success(t("common.saved"));
      setOpen(false);
      setEditing(null);
      void queryClient.invalidateQueries({ queryKey: ["resource", config.table] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const deleteMutation = useMutation({
    mutationFn: async (row: Row) => {
      const { error } = await db.from(config.table).delete().eq("id", String(row["id"]));
      if (error) throw error;
      await logAudit({
        action: "delete",
        entity_type: config.table,
        entity_id: String(row["id"]),
        summary: `Deleted ${config.table} record`,
        before_data: row,
      });
    },
    onSuccess: () => {
      toast.success(t("common.deleted"));
      void queryClient.invalidateQueries({ queryKey: ["resource", config.table] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (!canView) {
    return (
      <>
        <PageHeader title={config.title[lang]} />
        <NoAccess />
      </>
    );
  }

  const rows = (listQuery.data ?? []).filter((row) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return config.searchKeys.some((k) =>
      String(row[k] ?? "")
        .toLowerCase()
        .includes(q),
    );
  });

  const columns = config.columns.map((c) => ({ ...c, refLabel: refLabels[c.key] ?? c.refLabel }));

  const openNew = () => {
    const draft: Row = {};
    for (const f of config.fields) draft[f.key] = f.defaultValue ?? "";
    setEditing(draft);
    setOpen(true);
  };

  return (
    <>
      <PageHeader
        title={config.title[lang]}
        description={config.description?.[lang]}
        actions={
          <>
            {config.toolbar}
            {canCreate && (
              <Button onClick={openNew} className="gap-1.5">
                <Plus className="size-4" /> {t("common.new")}
              </Button>
            )}
          </>
        }
      />

      <div className="surface-panel overflow-hidden">
        <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
          <Search className="size-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("common.search")}
            className="h-8 border-0 bg-transparent shadow-none focus-visible:ring-0"
          />
          <span className="num text-xs text-muted-foreground">{rows.length}</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/40 text-start">
                {columns.map((c) => (
                  <th
                    key={c.key}
                    className="px-3 py-2.5 text-start text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                  >
                    {c.label[lang]}
                  </th>
                ))}
                {(canEdit || canRemove || config.extraRowActions) && (
                  <th className="px-3 py-2.5 text-end text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {t("common.actions")}
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {listQuery.isLoading && (
                <tr>
                  <td
                    colSpan={columns.length + 1}
                    className="px-3 py-8 text-center text-muted-foreground"
                  >
                    {t("common.loading")}
                  </td>
                </tr>
              )}
              {listQuery.isError && (
                <tr>
                  <td
                    colSpan={columns.length + 1}
                    className="px-3 py-10 text-center text-destructive"
                  >
                    {t("common.load_failed")}: {errorMessage(listQuery.error)}
                  </td>
                </tr>
              )}
              {!listQuery.isLoading && !listQuery.isError && rows.length === 0 && (
                <tr>
                  <td
                    colSpan={columns.length + 1}
                    className="px-3 py-10 text-center text-muted-foreground"
                  >
                    {t("common.empty")}
                  </td>
                </tr>
              )}
              {rows.map((row) => (
                <tr
                  key={String(row["id"])}
                  className="border-b border-border/70 last:border-0 hover:bg-muted/30"
                >
                  {columns.map((c) => (
                    <td key={c.key} className="px-3 py-2.5 align-middle">
                      {cellValue(row, c, lang)}
                    </td>
                  ))}
                  {(canEdit || canRemove || config.extraRowActions) && (
                    <td className="px-3 py-2 text-end whitespace-nowrap">
                      <div className="inline-flex items-center gap-1">
                        {config.extraRowActions?.(row, () =>
                          queryClient.invalidateQueries({ queryKey: ["resource", config.table] }),
                        )}
                        {canEdit && (
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => {
                              setEditing(row);
                              setOpen(true);
                            }}
                          >
                            <Pencil className="size-4" />
                          </Button>
                        )}
                        {canRemove && (
                          <Button
                            variant="ghost"
                            size="icon"
                            disabled={deleteMutation.isPending}
                            onClick={() => {
                              if (window.confirm(t("common.confirm_delete")))
                                deleteMutation.mutate(row);
                            }}
                          >
                            <Trash2 className="size-4 text-destructive" />
                          </Button>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <RecordDialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) setEditing(null);
        }}
        title={config.title[lang]}
        fields={config.fields}
        refs={refQuery.data ?? {}}
        initial={editing ?? {}}
        saving={saveMutation.isPending}
        onSubmit={(values) => saveMutation.mutate(values)}
      />
    </>
  );
}

export function RecordDialog({
  open,
  onOpenChange,
  title,
  fields,
  refs,
  initial,
  saving,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  fields: FieldDef[];
  refs: Record<string, { id: string; label: string }[]>;
  initial: Row;
  saving: boolean;
  onSubmit: (values: Row) => void;
}) {
  const { lang, t } = useI18n();
  const [values, setValues] = useState<Row>(initial);
  const [seed, setSeed] = useState<Row>(initial);

  if (seed !== initial) {
    setSeed(initial);
    setValues(initial);
  }

  const set = (key: string, value: unknown) => setValues((prev) => ({ ...prev, [key]: value }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <form
          className="grid gap-4 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit(values);
          }}
        >
          {fields.map((field) => {
            const value = values[field.key];
            const wide = field.kind === "textarea" || !field.half;
            return (
              <div key={field.key} className={wide ? "sm:col-span-2" : ""}>
                <Label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  {field.label[lang]}
                </Label>
                {field.kind === "bool" ? (
                  <label className="flex h-9 items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="size-4 accent-primary"
                      checked={Boolean(value)}
                      onChange={(e) => set(field.key, e.target.checked)}
                    />
                    <span className="text-muted-foreground">{field.label[lang]}</span>
                  </label>
                ) : field.kind === "textarea" ? (
                  <Textarea
                    value={String(value ?? "")}
                    onChange={(e) => set(field.key, e.target.value)}
                    rows={3}
                  />
                ) : field.kind === "select" ? (
                  <select
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                    value={String(value ?? "")}
                    onChange={(e) => set(field.key, e.target.value)}
                    required={field.required}
                  >
                    <option value="">{t("common.none")}</option>
                    {field.options?.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label[lang]}
                      </option>
                    ))}
                  </select>
                ) : field.kind === "ref" || field.kind === "profile" ? (
                  <select
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                    value={String(value ?? "")}
                    onChange={(e) => set(field.key, e.target.value)}
                    required={field.required}
                  >
                    <option value="">{t("common.none")}</option>
                    {(refs[field.key] ?? []).map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <Input
                    type={
                      field.kind === "number" ? "number" : field.kind === "date" ? "date" : "text"
                    }
                    step={field.kind === "number" ? "any" : undefined}
                    value={String(value ?? "")}
                    required={field.required}
                    onChange={(e) =>
                      set(
                        field.key,
                        field.kind === "number"
                          ? e.target.value === ""
                            ? ""
                            : Number(e.target.value)
                          : e.target.value,
                      )
                    }
                  />
                )}
              </div>
            );
          })}
          <DialogFooter className="sm:col-span-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={saving}>
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
