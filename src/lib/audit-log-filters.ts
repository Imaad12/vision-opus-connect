/**
 * Pure filtering for the Audit log page (Part 11's "user/actor/action/
 * date" filters) -- factored out for unit testing, matching this
 * codebase's convention (vinco-auth.ts, vinco-access-control.ts).
 */

export type AuditLogRow = {
  id: string;
  actor_id: string | null;
  actor_name: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  summary: string | null;
  created_at: string;
};

export function filterAuditLogs(
  logs: readonly AuditLogRow[],
  options: {
    actor?: string | undefined;
    action?: string | undefined;
    entityType?: string | undefined;
    from?: string | undefined;
    to?: string | undefined;
  },
): AuditLogRow[] {
  return logs.filter((log) => {
    if (options.actor && log.actor_id !== options.actor) return false;
    if (options.action && log.action !== options.action) return false;
    if (options.entityType && log.entity_type !== options.entityType) return false;
    if (options.from && log.created_at < options.from) return false;
    // Compare against the end of the selected day, not its start, so a
    // "to" date is inclusive of everything logged that day.
    if (options.to && log.created_at > `${options.to}T23:59:59.999Z`) return false;
    return true;
  });
}
