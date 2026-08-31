/**
 * Stable, shared React Query keys for data multiple pages independently
 * fetch from the SAME backend endpoint.
 *
 * Confirmed by code audit (not assumed) that /purchase-orders,
 * /quotations, /projects, /management/cash-flow, and
 * /management/operating-income were each independently keyed 2-4
 * different ways across dashboard/approvals/management/contracts/
 * purchase-orders/quotations -- e.g. dashboard.tsx used
 * ["dashboard-pos"], approvals.tsx used ["approvals-pos"], and
 * purchase-orders.tsx used ["purchase-orders"], all three hitting the
 * identical GET /purchase-orders with no `enabled` interaction between
 * them. Since React Query's cache is keyed purely by this array (never
 * by a caller's own TypeScript response type, which is compile-time
 * only and erased at runtime), using the SAME key across every caller
 * for the same endpoint means navigating between those pages reuses one
 * cache entry -- within staleTime, zero refetch -- instead of each page
 * re-fetching identical data from scratch.
 *
 * Deliberately only the key changes here: each page keeps its own local
 * response type and `enabled` condition (those genuinely differ per
 * caller -- e.g. dashboard gates purchase-orders on `canSeePOs`,
 * approvals gates the same data on `canApprovePOs`), so this is a
 * pure cache-locality fix with zero change to what's fetched, how it's
 * typed, or how it's authorization-gated.
 */
export const QK_PURCHASE_ORDERS = ["purchase-orders"] as const;
export const QK_QUOTATIONS = ["quotations"] as const;
export const QK_PROJECTS = ["projects"] as const;
export const QK_MANAGEMENT_CASH_FLOW = ["management-cash-flow"] as const;
export const QK_MANAGEMENT_OPERATING_INCOME = ["management-operating-income"] as const;
