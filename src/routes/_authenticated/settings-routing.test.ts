import { describe, expect, it } from "vitest";

import { Route as SettingsLayoutRoute } from "./settings";
import { Route as SettingsIndexRoute } from "./settings.index";
import { Route as SettingsUsersRoute } from "./settings.users";

/**
 * Regression test for a real production bug: TanStack Router's flat
 * file-based routing nests `settings.users.tsx` under `settings.tsx` by
 * naming convention alone, whether or not `settings.tsx` was written as
 * a layout. `settings.tsx` used to both be that parent AND render the
 * Company Settings page's own content directly, with no `<Outlet />`
 * anywhere -- so `/settings/users` matched the correct route object,
 * but its component was never mounted: the parent's static content was
 * all that ever rendered for any `/settings/*` URL, including the one
 * labeled "Users & Access" in the sidebar.
 *
 * No component-rendering test infra exists in this codebase yet
 * (vitest.config.ts runs in a plain node environment, no jsdom/
 * testing-library) -- this instead directly verifies the three route
 * modules are distinct and structured correctly, which is exactly what
 * broke: three routes collapsing into one rendered page.
 */
describe("settings routing", () => {
  it("settings.tsx is a bare pass-through layout, not a page in its own right", () => {
    const layoutComponent = SettingsLayoutRoute.options.component;
    expect(layoutComponent).toBeDefined();
    // Characterizes the actual bug: the old settings.tsx's component
    // rendered the Company Settings page's own content (and, before
    // that, queried company-settings data) directly, with no
    // `<Outlet />` -- so any `/settings/*` URL only ever showed that
    // static parent content. A real layout route delegates via
    // `<Outlet />` and touches neither this page's data source
    // (`company-settings`, now settings.index's own concern) nor the
    // Users & Access one (`app-users`, settings.users' concern).
    const source = layoutComponent!.toString();
    expect(source).toContain("Outlet");
    expect(source).not.toContain("company-settings");
    expect(source).not.toContain("app-users");
  });

  it("settings.index.tsx (exact /settings) and settings.users.tsx (/settings/users) are distinct components", () => {
    const indexComponent = SettingsIndexRoute.options.component;
    const usersComponent = SettingsUsersRoute.options.component;
    expect(indexComponent).toBeDefined();
    expect(usersComponent).toBeDefined();
    expect(indexComponent).not.toBe(usersComponent);
    expect(indexComponent).not.toBe(SettingsLayoutRoute.options.component);
    expect(usersComponent).not.toBe(SettingsLayoutRoute.options.component);
  });

  it("settings.index.tsx is gated by admin.settings, not admin.users", () => {
    // Only checks the top-level route component's own body (the
    // `me.can(...)` gate) -- the "company-settings" query key itself
    // lives one component deeper (CompanySettingsPanel), not reachable
    // via .toString() on the route's exported component alone.
    const source = SettingsIndexRoute.options.component!.toString();
    expect(source).toContain("admin.settings");
    expect(source).not.toContain("admin.users");
  });

  it("settings.users.tsx is gated by admin.users, not admin.settings", () => {
    const source = SettingsUsersRoute.options.component!.toString();
    expect(source).toContain("admin.users");
    expect(source).not.toContain("admin.settings");
  });

  it("settings.index and settings.users declare distinct page titles", () => {
    // `createFileRoute` doesn't attach `path`/`id` to the raw export
    // itself (those are only set once routeTree.gen.ts calls `.update()`
    // on it), so this checks the one other thing that must differ
    // between the two pages: their own declared <title>. Both `head()`
    // functions here are actually synchronous, zero-arg, and return a
    // plain object -- cast past the generic `(ctx) => Awaitable<...>`
    // signature TanStack Router's types allow in general rather than
    // fighting it, since this test only cares about that real runtime
    // shape.
    type SyncHead = () => { meta?: Array<Record<string, string>> };
    const indexHead = (SettingsIndexRoute.options.head as unknown as SyncHead)();
    const usersHead = (SettingsUsersRoute.options.head as unknown as SyncHead)();
    const indexTitle = indexHead.meta?.find((m) => "title" in m)?.["title"];
    const usersTitle = usersHead.meta?.find((m) => "title" in m)?.["title"];
    expect(indexTitle).toBe("Company settings — VINCO ERP");
    expect(usersTitle).toBe("Users & Access — VINCO ERP");
  });
});
