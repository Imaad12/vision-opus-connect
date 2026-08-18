import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { db, type Row } from "@/lib/db";
import { formatMoney, useI18n } from "@/lib/i18n";

export type ItemsTarget = {
  parentTable: string;
  itemsTable: string;
  parentColumn: string;
  parentId: string;
  vatRate: number;
  discountAmount?: number;
  readOnly?: boolean;
};

type Draft = {
  id?: string;
  description: string;
  unit: string;
  quantity: number;
  unit_price: number;
};

export function ItemsEditor({
  target,
  open,
  onOpenChange,
}: {
  target: ItemsTarget;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const { t, lang } = useI18n();
  const queryClient = useQueryClient();
  const [drafts, setDrafts] = useState<Draft[] | null>(null);

  const itemsQuery = useQuery({
    queryKey: ["items", target.itemsTable, target.parentId],
    enabled: open,
    queryFn: async () => {
      const { data, error } = await db
        .from(target.itemsTable)
        .select("*")
        .eq(target.parentColumn, target.parentId)
        .order("line_no", { ascending: true });
      if (error) throw error;
      return (data ?? []) as Row[];
    },
  });

  const rows: Draft[] =
    drafts ??
    (itemsQuery.data ?? []).map((r) => ({
      id: String(r["id"]),
      description: String(r["description"] ?? ""),
      unit: String(r["unit"] ?? "no"),
      quantity: Number(r["quantity"] ?? 1),
      unit_price: Number(r["unit_price"] ?? 0),
    }));

  const subtotal = rows.reduce((s, r) => s + r.quantity * r.unit_price, 0);
  const discount = Number(target.discountAmount ?? 0);
  const vat = ((subtotal - discount) * Number(target.vatRate ?? 15)) / 100;
  const total = subtotal - discount + vat;

  const save = useMutation({
    mutationFn: async () => {
      const existing = (itemsQuery.data ?? []).map((r) => String(r["id"]));
      const keep = rows.filter((r) => r.id).map((r) => r.id as string);
      const removed = existing.filter((id) => !keep.includes(id));
      if (removed.length) {
        const { error } = await db.from(target.itemsTable).delete().in("id", removed);
        if (error) throw error;
      }
      for (let i = 0; i < rows.length; i++) {
        const r = rows[i]!;
        const payload: Row = {
          [target.parentColumn]: target.parentId,
          line_no: i + 1,
          description: r.description,
          unit: r.unit || "no",
          quantity: r.quantity,
          unit_price: r.unit_price,
        };
        if (r.id) {
          const { error } = await db.from(target.itemsTable).update(payload).eq("id", r.id);
          if (error) throw error;
        } else {
          const { error } = await db.from(target.itemsTable).insert(payload);
          if (error) throw error;
        }
      }
      const parentPayload: Row = { subtotal, vat_amount: vat, total };
      const { error: perr } = await db
        .from(target.parentTable)
        .update(parentPayload)
        .eq("id", target.parentId);
      if (perr) throw perr;
    },
    onSuccess: () => {
      toast.success(t("common.saved"));
      setDrafts(null);
      void queryClient.invalidateQueries({ queryKey: ["items", target.itemsTable, target.parentId] });
      void queryClient.invalidateQueries({ queryKey: ["resource", target.parentTable] });
      onOpenChange(false);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const update = (index: number, patch: Partial<Draft>) =>
    setDrafts(rows.map((r, i) => (i === index ? { ...r, ...patch } : r)));

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) setDrafts(null);
        onOpenChange(v);
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("items.title")}</DialogTitle>
        </DialogHeader>

        <div className="space-y-2">
          <div className="hidden gap-2 px-1 text-xs font-medium text-muted-foreground sm:grid sm:grid-cols-[1fr_5rem_5rem_7rem_7rem_2rem]">
            <span>{t("items.description")}</span>
            <span>{t("items.unit")}</span>
            <span>{t("items.qty")}</span>
            <span>{t("items.price")}</span>
            <span>{t("items.line_total")}</span>
            <span />
          </div>

          {rows.map((r, i) => (
            <div
              key={r.id ?? `new-${i}`}
              className="grid gap-2 rounded-md border border-border p-2 sm:grid-cols-[1fr_5rem_5rem_7rem_7rem_2rem] sm:border-0 sm:p-0"
            >
              <Input
                value={r.description}
                disabled={target.readOnly}
                onChange={(e) => update(i, { description: e.target.value })}
                placeholder={t("items.description")}
              />
              <Input
                value={r.unit}
                disabled={target.readOnly}
                onChange={(e) => update(i, { unit: e.target.value })}
              />
              <Input
                type="number"
                step="any"
                value={r.quantity}
                disabled={target.readOnly}
                onChange={(e) => update(i, { quantity: Number(e.target.value) })}
              />
              <Input
                type="number"
                step="any"
                value={r.unit_price}
                disabled={target.readOnly}
                onChange={(e) => update(i, { unit_price: Number(e.target.value) })}
              />
              <div className="num flex h-9 items-center justify-end px-2 text-sm">
                {formatMoney(r.quantity * r.unit_price, lang)}
              </div>
              {!target.readOnly && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => setDrafts(rows.filter((_, idx) => idx !== i))}
                >
                  <Trash2 className="size-4 text-destructive" />
                </Button>
              )}
            </div>
          ))}

          {!target.readOnly && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() =>
                setDrafts([...rows, { description: "", unit: "no", quantity: 1, unit_price: 0 }])
              }
            >
              <Plus className="size-4" /> {t("items.add")}
            </Button>
          )}
        </div>

        <div className="mt-4 space-y-1 border-t border-border pt-3 text-sm">
          <Totals label={t("items.subtotal")} value={formatMoney(subtotal, lang)} />
          {discount > 0 && (
            <Totals label={t("items.discount")} value={`- ${formatMoney(discount, lang)}`} />
          )}
          <Totals
            label={`${t("items.vat")} (${target.vatRate}%)`}
            value={formatMoney(vat, lang)}
          />
          <Totals label={t("items.total")} value={formatMoney(total, lang)} strong />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.close")}
          </Button>
          {!target.readOnly && (
            <Button onClick={() => save.mutate()} disabled={save.isPending}>
              {t("common.save")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Totals({
  label,
  value,
  strong,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <div className={`flex justify-between ${strong ? "text-base font-semibold" : ""}`}>
      <span className="text-muted-foreground">{label}</span>
      <span className="num">{value}</span>
    </div>
  );
}
