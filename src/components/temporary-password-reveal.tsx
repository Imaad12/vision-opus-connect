import { Copy } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useI18n } from "@/lib/i18n";

/**
 * The one-time "here is the temporary password" panel shown after
 * creating a VINCO user or resetting one's password (Parts B2/B4) --
 * shared by `add-vinco-user-dialog.tsx`, `reset-vinco-password-dialog.tsx`,
 * and `settings.users.tsx`'s own create dialog so there's exactly one
 * place this warning/copy UI is written, not three slightly different
 * copies.
 *
 * Deliberately dumb: the password is a prop, passed in from whatever the
 * create/reset API call just returned -- this component never fetches,
 * stores, or re-requests it. Once the parent unmounts/replaces this (on
 * "Done"), the password is gone from memory along with it; nothing here
 * persists it (no state, no cache, no URL).
 */
export function TemporaryPasswordReveal({
  username,
  temporaryPassword,
  onDone,
}: {
  username: string;
  temporaryPassword: string;
  onDone: () => void;
}) {
  const { t } = useI18n();
  const [copiedField, setCopiedField] = useState<"username" | "password" | null>(null);

  const copy = (field: "username" | "password", value: string) => {
    // Clipboard access can fail (insecure context, denied permission,
    // some webviews) -- never let that block the admin from reading and
    // manually relaying the value, which is always still visible above.
    navigator.clipboard
      .writeText(value)
      .then(() => {
        setCopiedField(field);
        toast.success(t("common.copied"));
      })
      .catch(() => toast.error(t("common.copy")));
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("users.temp_password.instructions")}</p>

      <div className="space-y-1.5">
        <Label>{t("users.username")}</Label>
        <div className="flex items-center gap-2">
          <Input readOnly value={username} className="font-mono" />
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="shrink-0 gap-1.5"
            onClick={() => copy("username", username)}
          >
            <Copy className="size-3.5" />
            {copiedField === "username" ? t("common.copied") : t("common.copy")}
          </Button>
        </div>
      </div>

      <div className="space-y-1.5">
        <Label>{t("users.temp_password.label")}</Label>
        <div className="flex items-center gap-2">
          <Input readOnly value={temporaryPassword} className="font-mono" />
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="shrink-0 gap-1.5"
            onClick={() => copy("password", temporaryPassword)}
          >
            <Copy className="size-3.5" />
            {copiedField === "password" ? t("common.copied") : t("common.copy")}
          </Button>
        </div>
      </div>

      <p className="rounded-md bg-muted/60 p-2 text-xs text-muted-foreground">
        {t("users.temp_password.warning")}
      </p>

      <DialogFooter>
        <Button type="button" onClick={onDone}>
          {t("common.done")}
        </Button>
      </DialogFooter>
    </div>
  );
}
