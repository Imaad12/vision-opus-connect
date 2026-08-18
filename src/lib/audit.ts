import { db } from "@/lib/db";
import { supabase } from "@/integrations/supabase/client";

export async function logAudit(entry: {
  action: string;
  entity_type: string;
  entity_id?: string | null;
  summary?: string | null;
  before_data?: unknown;
  after_data?: unknown;
}) {
  const { data } = await supabase.auth.getUser();
  const user = data.user;
  if (!user) return;
  const { data: profile } = await supabase
    .from("profiles")
    .select("full_name")
    .eq("id", user.id)
    .maybeSingle();

  await db.from("audit_logs").insert({
    actor_id: user.id,
    actor_name: profile?.full_name || user.email,
    action: entry.action,
    entity_type: entry.entity_type,
    entity_id: entry.entity_id ?? null,
    summary: entry.summary ?? null,
    before_data: entry.before_data ?? null,
    after_data: entry.after_data ?? null,
  });
}
