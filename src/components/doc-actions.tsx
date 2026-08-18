import { useQueryClient } from "@tanstack/react-query";
import { Check, ListOrdered, Send, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ItemsEditor } from "@/components/items-editor";
import { Button } from "@/components/ui/button";
import { useMe } from "@/hooks/use-auth";
import { logAudit } from "@/lib/audit";
import { db, type Row } from "@/lib/db";
import { useI18n } from "@/lib/i18n";

export function ItemsButton({
  row,
  parentTable,
  itemsTable,
  parentColumn,
  editable,
}: {
  row: Row;
  parentTable: string;
  itemsTable: string;
  parentColumn: string;
  editable: boolean;
}) {
  const [open, setOpen] = useState(false);
  const { t } = useI18n();
  return (
    <>
      <Button variant="ghost" size="sm" className="gap-1.5" onClick={() => setOpen(true)}>
        <ListOrdered className="size-4" /> {t("doc.items")}
      </Button>
      <ItemsEditor
        open={open}
        onOpenChange={setOpen}
        target={{
          parentTable,
          itemsTable,
          parentColumn,
          parentId: String(row["id"]),
          vatRate: Number(row["vat_rate"] ?? 15),
          discountAmount: Number(row["discount_amount"] ?? 0),
          readOnly: !editable,
        }}
      />
    </>
  );
}

export function ApprovalActions({
  row,
  table,
  approvePerms,
  submitPerms,
  refresh,
}: {
  row: Row;
  table: string;
  approvePerms: string[];
  submitPerms: string[];
  refresh: () => void;
}) {
  const { t } = useI18n();
  const me = useMe();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const status = String(row["status"] ?? "");
  const id = String(row["id"]);

  const run = async (patch: Row, action: string) => {
    setBusy(true);
    const { error } = await db.from(table).update(patch).eq("id", id);
    setBusy(false);
    if (error) {
      toast.error(error.message.includes("separation") ? t("common.sod") : error.message);
      return;
    }
    await logAudit({
      action,
      entity_type: table,
      entity_id: id,
      summary: `${action} ${table}`,
      before_data: { status },
      after_data: patch,
    });
    toast.success(
      action === "submit" ? t("doc.submitted") : action === "approve" ? t("doc.approved") : t("doc.rejected"),
    );
    refresh();
    void queryClient.invalidateQueries({ queryKey: ["approvals"] });
  };

  const canSubmit = me.canAny(submitPerms);
  const canApprove = me.canAny(approvePerms);
  const pending = status === "submitted" || status === "pending_approval";
  const submitTo = table === "purchase_orders" ? "pending_approval" : "submitted";

  return (
    <>
      {status === "draft" && canSubmit && (
        <Button
          variant="ghost"
          size="sm"
          className="gap-1.5"
          disabled={busy}
          onClick={() =>
            void run(
              table === "quotations"
                ? { status: submitTo, submitted_by: me.userId, submitted_at: new Date().toISOString() }
                : { status: submitTo, submitted_at: new Date().toISOString() },
              "submit",
            )
          }
        >
          <Send className="size-4" /> {t("common.submit")}
        </Button>
      )}
      {pending && canApprove && (
        <>
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5 text-[color:var(--success)]"
            disabled={busy}
            onClick={() =>
              void run(
                { status: "approved", approved_by: me.userId, approved_at: new Date().toISOString() },
                "approve",
              )
            }
          >
            <Check className="size-4" /> {t("common.approve")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5 text-destructive"
            disabled={busy}
            onClick={() => {
              const reason = window.prompt(t("doc.reject_reason")) ?? "";
              void run(
                table === "quotations"
                  ? {
                      status: "rejected",
                      rejected_by: me.userId,
                      rejected_at: new Date().toISOString(),
                      rejection_reason: reason,
                    }
                  : { status: "rejected" },
                "reject",
              );
            }}
          >
            <X className="size-4" /> {t("common.reject")}
          </Button>
        </>
      )}
    </>
  );
}
