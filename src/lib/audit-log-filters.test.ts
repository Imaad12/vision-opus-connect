import { describe, expect, it } from "vitest";

import { filterAuditLogs, type AuditLogRow } from "./audit-log-filters";

function log(overrides: Partial<AuditLogRow> = {}): AuditLogRow {
  return {
    id: "1",
    actor_id: "actor-1",
    actor_name: "Jane Doe",
    action: "role_changed",
    entity_type: "app_users",
    entity_id: "user-1",
    summary: "Changed role",
    created_at: "2026-06-15T10:00:00.000Z",
    ...overrides,
  };
}

describe("filterAuditLogs", () => {
  it("returns everything with no filters", () => {
    const logs = [log({ id: "1" }), log({ id: "2" })];
    expect(filterAuditLogs(logs, {})).toHaveLength(2);
  });

  it("filters by actor", () => {
    const logs = [log({ id: "1", actor_id: "a" }), log({ id: "2", actor_id: "b" })];
    expect(filterAuditLogs(logs, { actor: "a" }).map((l) => l.id)).toEqual(["1"]);
  });

  it("filters by action", () => {
    const logs = [
      log({ id: "1", action: "password_reset" }),
      log({ id: "2", action: "role_changed" }),
    ];
    expect(filterAuditLogs(logs, { action: "password_reset" }).map((l) => l.id)).toEqual(["1"]);
  });

  it("filters by entity type", () => {
    const logs = [
      log({ id: "1", entity_type: "app_users" }),
      log({ id: "2", entity_type: "quotations" }),
    ];
    expect(filterAuditLogs(logs, { entityType: "app_users" }).map((l) => l.id)).toEqual(["1"]);
  });

  it("filters by date range inclusively", () => {
    const logs = [
      log({ id: "1", created_at: "2026-06-14T23:59:00.000Z" }),
      log({ id: "2", created_at: "2026-06-15T12:00:00.000Z" }),
      log({ id: "3", created_at: "2026-06-16T00:01:00.000Z" }),
    ];
    expect(
      filterAuditLogs(logs, { from: "2026-06-15", to: "2026-06-15" }).map((l) => l.id),
    ).toEqual(["2"]);
  });

  it("combines multiple filters", () => {
    const logs = [
      log({ id: "1", actor_id: "a", action: "password_reset" }),
      log({ id: "2", actor_id: "a", action: "role_changed" }),
      log({ id: "3", actor_id: "b", action: "password_reset" }),
    ];
    expect(
      filterAuditLogs(logs, { actor: "a", action: "password_reset" }).map((l) => l.id),
    ).toEqual(["1"]);
  });
});
