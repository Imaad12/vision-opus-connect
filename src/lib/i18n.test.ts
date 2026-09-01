/**
 * formatDate() is called with real, sometimes historically messy row data
 * across the whole app (resource-page.tsx's generic date column,
 * dashboard/audit-logs' "Recent activity", contracts/purchase-orders/
 * quotations' date columns). Root cause of the desktop root-error-boundary
 * crash traced to this: Intl.DateTimeFormat.format() throws
 * RangeError: Invalid time value for any non-empty string that doesn't
 * parse to a real date -- the old `if (!value) return "—"` guard only
 * covered null/empty, not garbage-but-truthy values like a hand-typed
 * "N/A" surviving in an older, loosely-typed date column.
 */
import { describe, expect, it } from "vitest";

import { formatDate } from "./i18n";

describe("formatDate", () => {
  it("formats a valid ISO date string", () => {
    expect(formatDate("2024-03-15", "en")).toBe("15 Mar 2024");
  });

  it("returns an em dash for null/undefined/empty", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDate(undefined)).toBe("—");
    expect(formatDate("")).toBe("—");
  });

  it("does not throw and returns an em dash for an unparseable-but-truthy value (the actual bug)", () => {
    for (const bad of ["N/A", "TBD", "not a date", "0000-00-00", "--"]) {
      expect(() => formatDate(bad)).not.toThrow();
      expect(formatDate(bad)).toBe("—");
    }
  });
});
